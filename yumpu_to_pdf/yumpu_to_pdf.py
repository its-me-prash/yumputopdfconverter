#!/usr/bin/env python3
"""Fetch a Yumpu document so its pages can be read and analysed.

Primary goal: download the page images of a Yumpu document (including
password-protected ones) into a folder so a tool — or a human, or Claude —
can open each page and analyse the content. Building a single PDF is an
optional, secondary step (``--pdf``).

Accepts a full Yumpu reader URL, including the ``?password=`` query parameter
used by protected documents, e.g.::

    python3 yumpu_to_pdf/yumpu_to_pdf.py \\
        "https://www.yumpu.com/de/document/read/71073502/expose-17614/29?password=baurimmo"

Password flow
-------------
Protected Yumpu documents are gated by a form page at
``/<lang>/document/protected/password/<id>?redirect=<reader-path>``. This
script:

1. Visits the reader URL with a cookie-aware client and a browser User-Agent.
2. If that redirects to (or returns) the protection page, it parses the
   password form and POSTs the password — carrying any hidden fields
   (CSRF token, ``redirect``) — so Yumpu sets the access cookie.
3. Confirms access was actually granted (fails loudly otherwise).
4. Scrapes the reader page for the real page-image URL pattern and page
   count, instead of guessing.
5. Downloads each page, validating it is a real image (not an HTML error or
   placeholder), into the output folder.
6. Optionally merges the pages into a PDF (``--pdf``).

Only the Python standard library is needed to download. Building a PDF uses
ImageMagick's ``convert`` if present, otherwise Pillow if installed.

NOTE: The exact protection flow could not be verified against the live site
from the development sandbox (Yumpu hosts are blocked by egress policy there).
The form-POST handling and page scraping are defensive and fall back to
explicit ``--dimensions`` / ``--image`` / ``--pages`` flags if auto-detection
fails. Run it where ``www.yumpu.com`` / ``img.yumpu.com`` are reachable.
"""

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.cookiejar import CookieJar
from urllib.parse import urlparse, parse_qs, urlencode, urljoin
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request
from urllib.error import HTTPError, URLError

DEFAULT_DIMENSIONS = "1215x1600"
DEFAULT_IMAGE_NAME = "composicion-escrita.jpg"
MAX_PAGES = 1000
STOP_AFTER_CONSECUTIVE_FAILURES = 3
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Magic-byte signatures so we never save an HTML error page as a "page image".
IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG
    b"RIFF",                    # WebP (RIFF....WEBP)
    b"GIF8",                    # GIF
)


class _RecordingRedirect(HTTPRedirectHandler):
    """Follows redirects but records the chain so we can detect the
    protection-page bounce."""

    def __init__(self):
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append((code, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_yumpu_url(url):
    """Extract (doc_id, password, slug) from a Yumpu reader/view URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    password = query.get("password", [None])[0]

    # Path looks like /de/document/read/71073502/expose-17614/29
    match = re.search(r"/document/(?:read|view|protected/password)/(\d+)(?:/([^/?#]+))?",
                      parsed.path)
    if not match:
        digits = re.search(r"/(\d{4,})", parsed.path)
        if not digits:
            raise ValueError(
                "Could not find a document id in the URL. Expected something "
                "like https://www.yumpu.com/de/document/read/<id>/<slug>"
            )
        return digits.group(1), password, None

    return match.group(1), password, match.group(2)


def make_opener():
    redirect = _RecordingRedirect()
    opener = build_opener(HTTPCookieProcessor(CookieJar()), redirect)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener, redirect


def _get(opener, url, data=None):
    """GET/POST and return (final_url, status, body_text)."""
    req = Request(url, data=data)
    with opener.open(req, timeout=30) as resp:
        body = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), resp.status, body.decode(charset, errors="replace")


def _find_password_form(body_html, base_url):
    """Locate the password <form> and return (action_url, fields_dict)."""
    # Find a form that contains a password input.
    for form in re.finditer(r"<form\b[^>]*>(.*?)</form>", body_html,
                            re.IGNORECASE | re.DOTALL):
        block = form.group(0)
        inner = form.group(1)
        if not re.search(r'<input[^>]*type=["\']?password', inner, re.IGNORECASE):
            continue
        action_match = re.search(r'action=["\']([^"\']*)["\']', block, re.IGNORECASE)
        action = html.unescape(action_match.group(1)) if action_match else ""
        action_url = urljoin(base_url, action) if action else base_url

        fields = {}
        for inp in re.finditer(r"<input\b[^>]*>", inner, re.IGNORECASE):
            tag = inp.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not name_m:
                continue
            value_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            fields[name_m.group(1)] = html.unescape(value_m.group(1)) if value_m else ""
        return action_url, fields
    return None, None


def _looks_like_password_page(final_url, body_html):
    return (
        "/document/protected/password/" in final_url
        or bool(re.search(r'<input[^>]*type=["\']?password', body_html, re.IGNORECASE))
    )


def authenticate(opener, redirect, url, password):
    """Establish an access session for a (possibly protected) document.

    Returns the final reader-page HTML on success; raises SystemExit on a
    confirmed auth failure.
    """
    redirect.chain.clear()
    try:
        final_url, status, body = _get(opener, url)
    except HTTPError as exc:
        final_url, status, body = exc.geturl(), exc.code, ""
    except URLError as exc:
        raise SystemExit(f"Error: could not reach Yumpu ({exc.reason}).")

    if not _looks_like_password_page(final_url, body):
        return body  # already have access (public doc or query param sufficed)

    if not password:
        raise SystemExit(
            "Error: document is password-protected but no password was given "
            "(add ?password=... to the URL or use --password)."
        )

    action_url, fields = _find_password_form(body, final_url)
    if not action_url:
        # Fall back to the canonical protection endpoint with a redirect field.
        doc_id, _, _ = parse_yumpu_url(url)
        parsed = urlparse(url)
        action_url = (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/{parsed.path.split('/')[1]}/document/protected/password/{doc_id}"
        )
        fields = {"redirect": parsed.path}

    # Set the password into whichever field name the form uses.
    pw_field = next((k for k in fields if k.lower() == "password"), "password")
    fields[pw_field] = password

    post_data = urlencode(fields).encode("utf-8")
    redirect.chain.clear()
    try:
        final_url, status, body = _get(opener, action_url, data=post_data)
    except HTTPError as exc:
        final_url, status, body = exc.geturl(), exc.code, ""
    except URLError as exc:
        raise SystemExit(f"Error: password POST failed ({exc.reason}).")

    if _looks_like_password_page(final_url, body):
        raise SystemExit(
            "Error: password was rejected (still on the protection page). "
            "Check the password."
        )
    return body


def discover_image_pattern(reader_html, doc_id):
    """Scrape the reader HTML for the real (dimensions, image_name) and an
    upper bound on the page count. Returns (dimensions, image_name, pages)
    with None for anything not found."""
    dims = image_name = pages = None

    m = re.search(
        rf"img\.yumpu\.com/{doc_id}/\d+/([0-9]+x[0-9]*)/([^\"'?\s]+\.(?:jpg|jpeg|png|webp))",
        reader_html, re.IGNORECASE,
    )
    if m:
        dims, image_name = m.group(1), m.group(2)

    pm = re.search(r'"(?:number_of_pages|pages|page_count)"\s*:\s*(\d+)', reader_html)
    if pm:
        pages = int(pm.group(1))

    return dims, image_name, pages


def image_url(doc_id, page, dimensions, image_name, password):
    base = f"https://img.yumpu.com/{doc_id}/{page}/{dimensions}/{image_name}"
    if password:
        return base + "?" + urlencode({"password": password})
    return base


def is_image(data):
    return data.startswith(IMAGE_SIGNATURES) or (
        len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )


def download_pages(opener, doc_id, dimensions, image_name, password, pages, outdir):
    files = []
    consecutive_failures = 0
    page = 1
    limit = pages if pages else MAX_PAGES

    while page <= limit:
        url = image_url(doc_id, page, dimensions, image_name, password)
        ext = os.path.splitext(image_name)[1] or ".jpg"
        filename = os.path.join(outdir, f"page{page:04d}{ext}")
        print(f"=== Downloading page {page} ===")
        try:
            req = Request(url)
            with opener.open(req, timeout=30) as resp:
                data = resp.read()
            if not is_image(data):
                raise ValueError("response was not an image (auth/placeholder?)")
            with open(filename, "wb") as fh:
                fh.write(data)
            files.append(filename)
            consecutive_failures = 0
        except (HTTPError, URLError, ValueError) as exc:
            reason = getattr(exc, "code", None) or getattr(exc, "reason", exc)
            print(f"Warning: page {page} failed ({reason}).", file=sys.stderr)
            consecutive_failures += 1
            if not pages and consecutive_failures >= STOP_AFTER_CONSECUTIVE_FAILURES:
                print("Reached the end of the document.", file=sys.stderr)
                break
        page += 1

    return files


def merge_to_pdf(files, output):
    if shutil.which("convert"):
        subprocess.run(["convert", *files, output], check=True)
        return
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "Error: need ImageMagick's 'convert' on PATH or Pillow installed "
            "(pip install pillow) to build the PDF."
        )
    images = [Image.open(f).convert("RGB") for f in files]
    images[0].save(output, save_all=True, append_images=images[1:])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download a Yumpu document's pages (for reading/analysis); "
        "optionally build a PDF."
    )
    parser.add_argument("url", nargs="?",
                        help="Full Yumpu reader URL, may contain ?password=<pw>")
    parser.add_argument("-d", "--doc-id", help="Yumpu document id (instead of a URL)")
    parser.add_argument("--password", help="Document password (overrides the URL's)")
    parser.add_argument("-p", "--pages", type=int, default=0,
                        help="Exact page count (default: auto-detect)")
    parser.add_argument("-s", "--dimensions", help="Image dimensions segment override")
    parser.add_argument("-i", "--image", help="Image file-name segment override")
    parser.add_argument("--outdir", help="Folder to store the page images "
                        "(default: ./<slug-or-id>_pages)")
    parser.add_argument("--pdf", nargs="?", const=True, default=False,
                        help="Also build a PDF (optionally give a file name)")
    args = parser.parse_args(argv)

    password = args.password
    slug = None
    reader_url = args.url
    if args.url:
        doc_id, url_password, slug = parse_yumpu_url(args.url)
        password = password or url_password
    elif args.doc_id:
        doc_id = args.doc_id
    else:
        parser.error("provide a Yumpu URL or --doc-id")

    outdir = args.outdir or os.path.abspath(f"{slug or doc_id}_pages")
    os.makedirs(outdir, exist_ok=True)

    opener, redirect = make_opener()

    dimensions = args.dimensions
    image_name = args.image
    pages = args.pages

    if reader_url:
        reader_html = authenticate(opener, redirect, reader_url, password)
        d_dims, d_name, d_pages = discover_image_pattern(reader_html, doc_id)
        dimensions = dimensions or d_dims
        image_name = image_name or d_name
        pages = pages or (d_pages or 0)
        if d_dims or d_name or d_pages:
            print(f"Detected: dimensions={d_dims} image={d_name} pages={d_pages}")

    dimensions = dimensions or DEFAULT_DIMENSIONS
    image_name = image_name or DEFAULT_IMAGE_NAME

    files = download_pages(opener, doc_id, dimensions, image_name, password, pages, outdir)
    if not files:
        raise SystemExit(
            "Error: no pages downloaded. Likely an auth failure or a wrong "
            "image pattern. Try passing --dimensions / --image explicitly, and "
            "verify the password."
        )

    print(f"\nDownloaded {len(files)} page(s) to: {outdir}")
    print("You can now open the images in that folder to read/analyse the document.")

    if args.pdf:
        output = args.pdf if isinstance(args.pdf, str) else f"{slug or doc_id}.pdf"
        output = os.path.abspath(output)
        print(f"Building PDF: {output} ...")
        merge_to_pdf(files, output)
        print(f"Done: {output}")


if __name__ == "__main__":
    main()
