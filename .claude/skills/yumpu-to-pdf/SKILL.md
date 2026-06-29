---
name: yumpu-to-pdf
description: Fetch the pages of a Yumpu document (img.yumpu.com), including password-protected ones, into a folder so Claude can read and analyse the content. Building a PDF is optional. Use when the user wants to read, analyse, summarise, extract from, convert, download, or archive a Yumpu publication / magazine / document, or gives a Yumpu document id or yumpu.com link (with or without a ?password= parameter).
---

# Yumpu document → readable pages (PDF optional)

The primary purpose of this skill is to pull down the page images of a Yumpu
document — **including password-protected documents** — into a local folder so
the **content can be read and analysed** (by Claude reading the page images, by
OCR, etc.). Producing a single PDF is an optional, secondary step.

## When to use

Use this skill when the user wants to read, analyse, summarise, or extract
information from a Yumpu publication, mentions a Yumpu document id, or pastes a
`yumpu.com` / `img.yumpu.com` link. This includes **password-protected**
documents — the user's link contains a `?password=…` query parameter, or a
`/document/protected/password/<id>?redirect=…` link.

## Primary engine: Python

`yumpu_to_pdf/yumpu_to_pdf.py` (at the repo root) takes a full Yumpu reader
URL, handles the password flow, auto-detects the page image pattern and page
count, downloads every page into a folder, and only builds a PDF if you ask.

```sh
# Password-protected document → download pages into ./expose-17614_pages/
python3 yumpu_to_pdf/yumpu_to_pdf.py \
    "https://www.yumpu.com/de/document/read/71073502/expose-17614/29?password=baurimmo"

# Public document
python3 yumpu_to_pdf/yumpu_to_pdf.py "https://www.yumpu.com/en/document/view/62283426/slug"

# Choose the output folder and also build a PDF
python3 yumpu_to_pdf/yumpu_to_pdf.py "<url>?password=<pw>" --outdir ./doc --pdf expose.pdf
```

### Typical analysis workflow for Claude

1. Run the script with the user's URL (and password if present).
2. It writes `page0001.jpg`, `page0002.jpg`, … into the output folder.
3. **Read those image files** to understand and analyse the document's content
   (answer the user's question, summarise, extract data, etc.).
4. Only build a PDF (`--pdf`) if the user actually wants a PDF artefact.

### How page discovery works

The engine bundles the approaches of the open-source Yumpu downloaders (see
`CREDITS.md`). Its **primary** path queries the metadata endpoint
`https://www.yumpu.com/document/json2/<id>` to get the real image `base_path`,
per-page image names and page count, then builds exact image URLs — no
guessing. If that endpoint is unavailable it **falls back** to scraping the
reader page / the `img.yumpu.com/<id>/<page>/<dims>/<name>` scheme (use
`--no-metadata` to force the fallback, and `--dimensions` / `--image` /
`--pages` to override it).

### How the password flow works

Protected Yumpu documents are gated by a form page at
`/<lang>/document/protected/password/<id>?redirect=<reader-path>`. The script:

1. Visits the reader URL with a cookie-aware client + browser User-Agent.
2. If it lands on the protection page, parses the password form (including
   hidden `_token` / `redirect` fields) and **POSTs the password**, so Yumpu
   sets the access cookie.
3. **Fails loudly** if the password is rejected (it does not silently produce a
   PDF of error pages).
4. Scrapes the reader page for the real image URL pattern and page count
   instead of guessing.
5. Validates each downloaded page is a real image (magic bytes), so HTML error
   pages or placeholders are never saved as pages.

### Options

| Flag | Meaning | Default |
| --- | --- | --- |
| `url` (positional) | Full Yumpu reader URL (may contain `?password=`) | — |
| `-d`, `--doc-id ID` | Document id (instead of a URL) | — |
| `--password PW` | Document password (overrides the URL's) | from URL |
| `-p`, `--pages N` | Exact page count (fallback path) | auto-detect |
| `-s`, `--dimensions WxH` | Image dimensions segment (fallback) | auto → `1215x1600` |
| `-i`, `--image NAME` | Image file-name segment (fallback) | auto → `composicion-escrita.jpg` |
| `--no-metadata` | Skip the json2 endpoint, force the fallback | off |
| `--outdir DIR` | Folder for the page images | `./<slug-or-id>_pages` |
| `--pdf [FILE]` | Also build a PDF (optional file name) | off |

Requirements: `python3` (standard library only for downloading). A PDF
additionally needs ImageMagick's `convert` on `PATH`, or Pillow
(`pip install pillow`).

If auto-detection of the image pattern fails (no pages downloaded), pass
`--dimensions` and `--image` explicitly — read them off a page-image URL in the
reader's network requests: `https://img.yumpu.com/<id>/<page>/<dimensions>/<image-name>`.

## Simple Bash engine (public documents, no password support)

For public documents you can also use the dependency-light Bash script. It has
no password handling and always builds a PDF — use the Python engine for
protected documents or for content analysis.

Requirements: `curl` and ImageMagick's `convert` on `PATH`.

```sh
bash scripts/yumpu_to_pdf.sh [options]
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `-d`, `--doc-id ID` | Yumpu document id | `62283426` |
| `-p`, `--pages N` | Number of pages to fetch | `200` |
| `-s`, `--dimensions WxH` | Image dimensions segment | `1215x1600` |
| `-i`, `--image NAME` | Image file-name segment | `composicion-escrita.jpg` |
| `-o`, `--output FILE` | Output PDF file name | `composicion-escrita.pdf` |
| `-w`, `--workdir DIR` | Where to put temporary JPGs | fresh temp dir |
| `-k`, `--keep` | Keep the downloaded JPGs | off (cleaned up) |
| `-h`, `--help` | Show usage | — |

## Notes & caveats

- The original C++ implementation lives in `main.cpp` at the repo root and uses
  the same URL scheme; the engines here are dependency-light equivalents.
- **Verification status:** the exact Yumpu password flow could not be tested
  against the live site from the development sandbox, because that environment
  blocks `www.yumpu.com` / `img.yumpu.com` by egress policy. The form-POST
  handling and page-pattern scraping are written defensively with manual
  overrides (`--dimensions` / `--image` / `--pages`) as a fallback. Validate in
  an environment where Yumpu is reachable, and adjust the flow if Yumpu's real
  responses differ.
- Only download documents the user is allowed to access.
