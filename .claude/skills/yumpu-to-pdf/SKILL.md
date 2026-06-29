---
name: yumpu-to-pdf
description: Download the pages of a Yumpu document (img.yumpu.com) and merge them into a single PDF, including password-protected documents. Use when the user wants to convert, download, or archive a Yumpu publication / magazine / document as a PDF, or gives a Yumpu document id or yumpu.com link (with or without a ?password= parameter).
---

# Yumpu to PDF

Convert a Yumpu document into a single PDF by downloading each page image
from `img.yumpu.com` and merging them.

## When to use

Use this skill when the user wants to turn a Yumpu publication into a PDF,
mentions a Yumpu document id, or pastes a `yumpu.com` / `img.yumpu.com` link.
This includes **password-protected** documents — the user's link will contain
a `?password=…` query parameter.

## Recommended engine: Python (supports passwords + full URLs)

`yumpu_to_pdf/yumpu_to_pdf.py` (at the repo root) accepts a full Yumpu reader
URL, including the `?password=` parameter used by protected documents, and
auto-detects the page count.

```sh
# Password-protected document — pass the full reader URL
python3 yumpu_to_pdf/yumpu_to_pdf.py \
    "https://www.yumpu.com/de/document/read/71073502/expose-17614?password=baurimmo"

# Public document
python3 yumpu_to_pdf/yumpu_to_pdf.py "https://www.yumpu.com/en/document/view/62283426/slug"

# By id, with an explicit password and page count
python3 yumpu_to_pdf/yumpu_to_pdf.py -d 71073502 --password baurimmo -p 24 -o expose.pdf
```

How the password support works: the script uses a cookie-aware opener, visits
the reader URL first so Yumpu validates the password and sets the access
cookie, then forwards the password to each `img.yumpu.com` page request.

Python engine options:

| Flag | Meaning | Default |
| --- | --- | --- |
| `url` (positional) | Full Yumpu reader URL (may contain `?password=`) | — |
| `-d`, `--doc-id ID` | Document id (instead of a URL) | — |
| `--password PW` | Document password (overrides the URL's) | from URL |
| `-p`, `--pages N` | Exact page count | auto-detect |
| `-s`, `--dimensions WxH` | Image dimensions segment | `1215x1600` |
| `-i`, `--image NAME` | Image file-name segment | `composicion-escrita.jpg` |
| `-o`, `--output FILE` | Output PDF file name | `<slug>.pdf` / `<id>.pdf` |
| `-w`, `--workdir DIR` | Temp directory for JPGs | fresh temp dir |
| `-k`, `--keep` | Keep the downloaded JPGs | off |

Requirements for the Python engine: `python3` (standard library only for the
download) plus either ImageMagick's `convert` on `PATH` or Pillow
(`pip install pillow`) to build the PDF.

## Simple Bash engine (no password support)

For public documents you can also use the dependency-light Bash script. It has
no password handling — use the Python engine for protected documents.

### Requirements

The Bash script shells out to two tools that must be on `PATH`:

- `curl` — downloads the page images.
- `convert` — ImageMagick, merges the images into a PDF.

If `convert` is missing, install ImageMagick first.

### How to run

The engine is `scripts/yumpu_to_pdf.sh`. All parameters have defaults and can
be overridden with flags:

```sh
bash scripts/yumpu_to_pdf.sh [options]
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `-d`, `--doc-id ID` | Yumpu document id | `62283426` |
| `-p`, `--pages N` | Number of pages to fetch | `200` |
| `-s`, `--dimensions WxH` | Image dimensions segment of the URL | `1215x1600` |
| `-i`, `--image NAME` | Image file-name segment of the URL | `composicion-escrita.jpg` |
| `-o`, `--output FILE` | Output PDF file name | `composicion-escrita.pdf` |
| `-w`, `--workdir DIR` | Where to put temporary JPGs | fresh temp dir |
| `-k`, `--keep` | Keep the downloaded JPGs | off (cleaned up) |
| `-h`, `--help` | Show usage | — |

### Examples

```sh
# All defaults
bash scripts/yumpu_to_pdf.sh

# A different document, only 50 pages
bash scripts/yumpu_to_pdf.sh -d 12345678 -p 50

# Fully custom
bash scripts/yumpu_to_pdf.sh -d 12345678 -p 50 -s 800x1000 -i cover.jpg -o out.pdf
```

## Figuring out the parameters

A page image URL on Yumpu looks like:

```
https://img.yumpu.com/<doc-id>/<page>/<dimensions>/<image-name>
```

So to convert a specific document:

1. Open one page image of the document in the browser (or inspect the
   network requests on the Yumpu reader page) to read off the `doc-id`,
   `dimensions`, and `image-name` segments.
2. Determine how many pages the document has and pass it via `--pages`.
3. Run the script with those values.

If a page fails to download the script logs a warning and continues, then
merges whatever pages were retrieved. If nothing downloads it exits with an
error — that usually means the `doc-id`, `dimensions`, or `image-name` is
wrong.

## Notes

- The original C++ implementation lives in `main.cpp` at the repo root and
  uses the same URL scheme and defaults; this skill is a dependency-light
  Bash equivalent so it runs without a compiler.
- Only convert documents the user is allowed to download.
