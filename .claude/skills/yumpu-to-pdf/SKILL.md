---
name: yumpu-to-pdf
description: Download the pages of a Yumpu document (img.yumpu.com) and merge them into a single PDF. Use when the user wants to convert, download, or archive a Yumpu publication / magazine / document as a PDF, or gives a Yumpu document id or yumpu.com link.
---

# Yumpu to PDF

Convert a Yumpu document into a single PDF by downloading each page image
from `img.yumpu.com` and merging them with ImageMagick.

## When to use

Use this skill when the user wants to turn a Yumpu publication into a PDF,
mentions a Yumpu document id, or pastes a `yumpu.com` / `img.yumpu.com` link.

## Requirements

The script shells out to two tools that must be on `PATH`:

- `curl` — downloads the page images.
- `convert` — ImageMagick, merges the images into a PDF.

If `convert` is missing, install ImageMagick first.

## How to run

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
