#!/usr/bin/env python3
"""Download a Yumpu document and merge its pages into a single PDF.

Accepts a full Yumpu reader URL, including the optional ``?password=`` query
parameter used by password-protected documents, e.g.::

    python3 yumpu_to_pdf/yumpu_to_pdf.py \\
        "https://www.yumpu.com/de/document/read/71073502/expose-17614?password=baurimmo"

The page images are served from ``img.yumpu.com``. For password-protected
documents Yumpu validates the password on the reader URL and hands back an
access cookie; this script replays that flow with a cookie-aware opener and
also forwards the password to the image requests, so protected documents can
be fetched.

Only the Python standard library is required for downloading. Merging the
images into a PDF uses ImageMagick's ``convert`` if available, otherwise
Pillow (``pip install pillow``) if installed.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.cookiejar import CookieJar
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError, URLError

DEFAULT_DIMENSIONS = "1215x1600"
DEFAULT_IMAGE_NAME = "composicion-escrita.jpg"
MAX_PAGES = 1000
STOP_AFTER_CONSECUTIVE_FAILURES = 3
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def parse_yumpu_url(url):
    """Extract (doc_id, password, slug) from a Yumpu reader/view URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    password = query.get("password", [None])[0]

    # Path looks like /de/document/read/71073502/expose-17614
    match = re.search(r"/document/(?:read|view)/(\d+)(?:/([^/?#]+))?", parsed.path)
    if not match:
        # Fall back to the first long run of digits in the path.
        digits = re.search(r"/(\d{4,})", parsed.path)
        if not digits:
            raise ValueError(
                "Could not find a document id in the URL. Expected something "
                "like https://www.yumpu.com/de/document/read/<id>/<slug>"
            )
        return digits.group(1), password, None

    return match.group(1), password, match.group(2)


def make_opener():
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def establish_session(opener, url):
    """Visit the reader URL so the password is validated and cookies are set."""
    try:
        with opener.open(Request(url), timeout=30) as resp:
            resp.read()
    except HTTPError as exc:
        # 403 here often just means the reader page gates differently; the
        # image requests may still succeed with the cookie + password param.
        print(f"Note: reader URL returned HTTP {exc.code}; continuing.", file=sys.stderr)
    except URLError as exc:
        print(f"Note: could not open reader URL ({exc.reason}); continuing.", file=sys.stderr)


def image_url(doc_id, page, dimensions, image_name, password):
    base = f"https://img.yumpu.com/{doc_id}/{page}/{dimensions}/{image_name}"
    if password:
        return base + "?" + urlencode({"password": password})
    return base


def download_pages(opener, doc_id, dimensions, image_name, password, pages, workdir):
    files = []
    consecutive_failures = 0
    page = 1
    limit = pages if pages else MAX_PAGES

    while page <= limit:
        url = image_url(doc_id, page, dimensions, image_name, password)
        filename = os.path.join(workdir, f"page{page}.jpg")
        print(f"=== Downloading page {page} ===")
        try:
            with opener.open(Request(url), timeout=30) as resp:
                data = resp.read()
            if not data:
                raise ValueError("empty response")
            with open(filename, "wb") as fh:
                fh.write(data)
            files.append(filename)
            consecutive_failures = 0
        except (HTTPError, URLError, ValueError) as exc:
            reason = getattr(exc, "code", None) or getattr(exc, "reason", exc)
            print(f"Warning: page {page} failed ({reason}).", file=sys.stderr)
            consecutive_failures += 1
            # When no explicit page count was requested, stop once the
            # document clearly ended (several pages in a row missing).
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
        description="Download a Yumpu document and merge its pages into a PDF."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Full Yumpu reader URL, e.g. "
        "https://www.yumpu.com/de/document/read/<id>/<slug>?password=<pw>",
    )
    parser.add_argument("-d", "--doc-id", help="Yumpu document id (instead of a URL)")
    parser.add_argument("--password", help="Document password (overrides the URL's ?password=)")
    parser.add_argument(
        "-p", "--pages", type=int, default=0,
        help="Exact number of pages to fetch (default: auto-detect)",
    )
    parser.add_argument("-s", "--dimensions", default=DEFAULT_DIMENSIONS,
                        help=f"Image dimensions segment (default: {DEFAULT_DIMENSIONS})")
    parser.add_argument("-i", "--image", default=DEFAULT_IMAGE_NAME,
                        help=f"Image file-name segment (default: {DEFAULT_IMAGE_NAME})")
    parser.add_argument("-o", "--output", help="Output PDF file name")
    parser.add_argument("-w", "--workdir", help="Directory for temporary JPGs")
    parser.add_argument("-k", "--keep", action="store_true",
                        help="Keep the downloaded JPGs")
    args = parser.parse_args(argv)

    password = args.password
    slug = None
    if args.url:
        doc_id, url_password, slug = parse_yumpu_url(args.url)
        password = password or url_password
    elif args.doc_id:
        doc_id = args.doc_id
    else:
        parser.error("provide a Yumpu URL or --doc-id")

    output = args.output or (f"{slug}.pdf" if slug else f"{doc_id}.pdf")
    output = os.path.abspath(output)

    created_workdir = args.workdir is None
    workdir = args.workdir or tempfile.mkdtemp(prefix="yumpu_")
    os.makedirs(workdir, exist_ok=True)

    opener = make_opener()
    if args.url and password:
        establish_session(opener, args.url)

    try:
        files = download_pages(
            opener, doc_id, args.dimensions, args.image, password, args.pages, workdir
        )
        if not files:
            raise SystemExit(
                "Error: no pages downloaded. Check the document id, password, "
                "dimensions or image name."
            )
        print(f"\nConverting {len(files)} page(s) into {output} ...")
        merge_to_pdf(files, output)
        print(f"Done: {output}")
    finally:
        if created_workdir and not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
