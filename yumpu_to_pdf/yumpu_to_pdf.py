#!/usr/bin/env python3
"""Fetch a Yumpu document so its pages can be read and analysed.

Primary goal: download the page images of a Yumpu document (including
password-protected ones) into a folder so a tool — or a human, or Claude —
can open each page and analyse the content. Building a single PDF is an
optional, secondary step (``--pdf``).

This is a "bundle" of the techniques used across the open-source Yumpu
downloaders (see CREDITS.md):

* json2 metadata endpoint to learn the real image base path, per-page image
  names and page count (from ianmuscat/yumpu-scraper) — no guessing.
* img.yumpu.com page-image scheme + ImageMagick PDF build (from the C++
  YumpuToPDFConverter lineage).
* Password handling, content validation and fail-loud auth (added here).

Usage::

    python3 yumpu_to_pdf/yumpu_to_pdf.py \\
        "https://www.yumpu.com/de/document/read/71073502/expose-17614/29?password=baurimmo"

Download flow
-------------
1. Authenticate (handles the /document/protected/password/ gate, POSTs the
   password, fails loudly if rejected).
2. Query ``https://www.yumpu.com/document/json2/<id>`` for ``base_path`` +
   ``pages[].images.large`` + ``pages[].qss.large`` and build exact image
   URLs. (Primary path — works for any document without guessing.)
3. Fall back to scraping the reader page / the hardcoded img.yumpu.com scheme
   if the metadata endpoint is unavailable.
4. Download each page, validating it is a real image (magic bytes), into the
   output folder.
5. Optionally merge into a PDF (``--pdf``).

Only the Python standard library is needed to download. Building a PDF uses
ImageMagick's ``convert`` if present, otherwise Pillow if installed.

NOTE: The exact protection flow and the json2 response shape could not be
verified against the live site from the development sandbox (Yumpu hosts are
blocked by egress policy there). The code is defensive, with manual overrides
(``--dimensions`` / ``--image`` / ``--pages``) as a fallback. Run it where
``www.yumpu.com`` / ``img.yumpu.com`` are reachable.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
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
IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG
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


def _request(opener, url, data=None, binary=False):
    """GET/POST. Returns (final_url, status, body) where body is bytes if
    binary else decoded text."""
    req = Request(url, data=data)
    with opener.open(req, timeout=30) as resp:
        raw = resp.read()
        if binary:
            return resp.geturl(), resp.status, raw
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), resp.status, raw.decode(charset, errors="replace")


# --------------------------------------------------------------------------
# Authentication (password-protected documents)
# --------------------------------------------------------------------------

def _find_password_form(body_html, base_url):
    for form in re.finditer(r"<form\b[^>]*>(.*?)</form>", body_html,
                            re.IGNORECASE | re.DOTALL):
        block, inner = form.group(0), form.group(1)
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
        final_url, status, body = _request(opener, url)
    except HTTPError as exc:
        final_url, status, body = exc.geturl(), exc.code, ""
    except URLError as exc:
        raise SystemExit(f"Error: could not reach Yumpu ({exc.reason}).")

    if not _looks_like_password_page(final_url, body):
        return body  # public doc, or query param already sufficed

    if not password:
        raise SystemExit(
            "Error: document is password-protected but no password was given "
            "(add ?password=... to the URL or use --password)."
        )

    action_url, fields = _find_password_form(body, final_url)
    if not action_url:
        doc_id, _, _ = parse_yumpu_url(url)
        parsed = urlparse(url)
        lang = parsed.path.split("/")[1] if parsed.path.count("/") > 1 else "en"
        action_url = (f"{parsed.scheme}://{parsed.netloc}"
                      f"/{lang}/document/protected/password/{doc_id}")
        fields = {"redirect": parsed.path}

    pw_field = next((k for k in fields if k.lower() == "password"), "password")
    fields[pw_field] = password

    redirect.chain.clear()
    try:
        final_url, status, body = _request(opener, action_url,
                                           data=urlencode(fields).encode("utf-8"))
    except HTTPError as exc:
        final_url, status, body = exc.geturl(), exc.code, ""
    except URLError as exc:
        raise SystemExit(f"Error: password POST failed ({exc.reason}).")

    if _looks_like_password_page(final_url, body):
        raise SystemExit("Error: password was rejected (still on the protection "
                         "page). Check the password.")
    return body


# --------------------------------------------------------------------------
# Page discovery
# --------------------------------------------------------------------------

def fetch_metadata_urls(opener, doc_id):
    """PRIMARY: use the json2 metadata endpoint to build exact page-image URLs.

    Returns a list of full image URLs, or None if the endpoint is unavailable
    or the response doesn't have the expected shape.
    Technique adapted from ianmuscat/yumpu-scraper.
    """
    url = f"https://www.yumpu.com/document/json2/{doc_id}"
    try:
        _, _, body = _request(opener, url)
    except (HTTPError, URLError):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None

    base = data.get("base_path") or data.get("basePath")
    pages = data.get("pages")
    if not base or not isinstance(pages, list) or not pages:
        return None
    if base.startswith("//"):
        base = "https:" + base

    urls = []
    for pg in pages:
        images = pg.get("images") or {}
        img = images.get("large") or images.get("medium") or images.get("small")
        if not img:
            return None
        qss = (pg.get("qss") or {})
        token = qss.get("large") or qss.get("medium") or qss.get("small") or ""
        full = urljoin(base if base.endswith("/") else base + "/", img.lstrip("/"))
        if token:
            full += ("&" if "?" in full else "?") + token
        urls.append(full)
    return urls or None


def discover_image_pattern(reader_html, doc_id):
    """FALLBACK: scrape the reader HTML for (dimensions, image_name, pages)."""
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


def pattern_url(doc_id, page, dimensions, image_name, password):
    base = f"https://img.yumpu.com/{doc_id}/{page}/{dimensions}/{image_name}"
    if password:
        return base + "?" + urlencode({"password": password})
    return base


# --------------------------------------------------------------------------
# Download + PDF
# --------------------------------------------------------------------------

def is_image(data):
    return data.startswith(IMAGE_SIGNATURES) or (
        len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )


def _save_page(opener, url, filename):
    _, _, data = _request(opener, url, binary=True)
    if not is_image(data):
        raise ValueError("response was not an image (auth/placeholder?)")
    with open(filename, "wb") as fh:
        fh.write(data)


def download_from_urls(opener, urls, outdir):
    files = []
    for idx, url in enumerate(urls, start=1):
        filename = os.path.join(outdir, f"page{idx:04d}.jpg")
        print(f"=== Downloading page {idx}/{len(urls)} ===")
        try:
            _save_page(opener, url, filename)
            files.append(filename)
        except (HTTPError, URLError, ValueError) as exc:
            reason = getattr(exc, "code", None) or getattr(exc, "reason", exc)
            print(f"Warning: page {idx} failed ({reason}).", file=sys.stderr)
    return files


def download_by_pattern(opener, doc_id, dimensions, image_name, password, pages, outdir):
    files = []
    consecutive_failures = 0
    page = 1
    limit = pages if pages else MAX_PAGES
    ext = os.path.splitext(image_name)[1] or ".jpg"
    while page <= limit:
        url = pattern_url(doc_id, page, dimensions, image_name, password)
        filename = os.path.join(outdir, f"page{page:04d}{ext}")
        print(f"=== Downloading page {page} ===")
        try:
            _save_page(opener, url, filename)
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
        raise SystemExit("Error: need ImageMagick's 'convert' on PATH or Pillow "
                         "installed (pip install pillow) to build the PDF.")
    images = [Image.open(f).convert("RGB") for f in files]
    images[0].save(output, save_all=True, append_images=images[1:])


# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download a Yumpu document's pages (for reading/analysis); "
        "optionally build a PDF.")
    parser.add_argument("url", nargs="?",
                        help="Full Yumpu reader URL, may contain ?password=<pw>")
    parser.add_argument("-d", "--doc-id", help="Yumpu document id (instead of a URL)")
    parser.add_argument("--password", help="Document password (overrides the URL's)")
    parser.add_argument("-p", "--pages", type=int, default=0,
                        help="Exact page count for the fallback path (default: auto)")
    parser.add_argument("-s", "--dimensions", help="Fallback image dimensions override")
    parser.add_argument("-i", "--image", help="Fallback image file-name override")
    parser.add_argument("--no-metadata", action="store_true",
                        help="Skip the json2 metadata endpoint, force the fallback")
    parser.add_argument("--outdir", help="Folder for the page images "
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
    reader_html = ""
    if reader_url:
        reader_html = authenticate(opener, redirect, reader_url, password)

    files = []
    # PRIMARY path: json2 metadata endpoint.
    if not args.no_metadata:
        meta_urls = fetch_metadata_urls(opener, doc_id)
        if meta_urls:
            print(f"Metadata: {len(meta_urls)} page(s) from json2 endpoint.")
            files = download_from_urls(opener, meta_urls, outdir)

    # FALLBACK path: scrape pattern / hardcoded scheme.
    if not files:
        d_dims, d_name, d_pages = discover_image_pattern(reader_html, doc_id)
        dimensions = args.dimensions or d_dims or DEFAULT_DIMENSIONS
        image_name = args.image or d_name or DEFAULT_IMAGE_NAME
        pages = args.pages or (d_pages or 0)
        print(f"Fallback: dimensions={dimensions} image={image_name} "
              f"pages={pages or 'auto'}")
        files = download_by_pattern(opener, doc_id, dimensions, image_name,
                                    password, pages, outdir)

    if not files:
        raise SystemExit(
            "Error: no pages downloaded. Likely an auth failure or wrong image "
            "pattern. Verify the password, or pass --dimensions / --image.")

    print(f"\nDownloaded {len(files)} page(s) to: {outdir}")
    print("Open the images in that folder to read/analyse the document.")

    if args.pdf:
        output = os.path.abspath(args.pdf if isinstance(args.pdf, str)
                                 else f"{slug or doc_id}.pdf")
        print(f"Building PDF: {output} ...")
        merge_to_pdf(files, output)
        print(f"Done: {output}")


if __name__ == "__main__":
    main()
