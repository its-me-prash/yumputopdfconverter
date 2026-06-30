#!/usr/bin/env bash
#
# yumpu_to_pdf.sh — download the page images of a Yumpu document and merge
# them into a single PDF.
#
# Mirrors the logic of main.cpp: it downloads each page image from
# img.yumpu.com via curl and merges them with ImageMagick's `convert`.
# Every value has a sensible default and can be overridden by a flag.
#
# Usage:
#   yumpu_to_pdf.sh [options]
#
# Options:
#   -d, --doc-id ID        Yumpu document id          (default: 62283426)
#   -p, --pages N          Number of pages to fetch   (default: 200)
#   -s, --dimensions WxH   Image dimensions segment    (default: 1215x1600)
#   -i, --image NAME       Image file name segment     (default: composicion-escrita.jpg)
#   -o, --output FILE      Output PDF file name         (default: composicion-escrita.pdf)
#   -w, --workdir DIR      Directory for temp files     (default: a fresh mktemp dir)
#   -k, --keep             Keep the downloaded JPGs (do not delete them)
#   -h, --help             Show this help and exit
#
# Examples:
#   yumpu_to_pdf.sh
#   yumpu_to_pdf.sh -d 12345678 -p 50
#   yumpu_to_pdf.sh -d 12345678 -p 50 -s 800x1000 -i cover.jpg -o out.pdf

set -euo pipefail

doc_id="62283426"
pages=200
dimensions="1215x1600"
image="composicion-escrita.jpg"
output="composicion-escrita.pdf"
workdir=""
keep=0

usage() {
  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--doc-id)     doc_id="$2"; shift 2 ;;
    -p|--pages)      pages="$2"; shift 2 ;;
    -s|--dimensions) dimensions="$2"; shift 2 ;;
    -i|--image)      image="$2"; shift 2 ;;
    -o|--output)     output="$2"; shift 2 ;;
    -w|--workdir)    workdir="$2"; shift 2 ;;
    -k|--keep)       keep=1; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# Validate dependencies up front.
for cmd in curl convert; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command '$cmd' not found in PATH." >&2
    [[ "$cmd" == "convert" ]] && echo "Install ImageMagick to provide 'convert'." >&2
    exit 1
  fi
done

if ! [[ "$pages" =~ ^[0-9]+$ ]] || [[ "$pages" -lt 1 ]]; then
  echo "Error: --pages must be a positive integer (got '$pages')." >&2
  exit 1
fi

# Resolve absolute output path before we change directory.
case "$output" in
  /*) output_abs="$output" ;;
  *)  output_abs="$PWD/$output" ;;
esac

created_workdir=0
if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d)"
  created_workdir=1
else
  mkdir -p "$workdir"
fi

cleanup() {
  if [[ "$keep" -eq 0 && "$created_workdir" -eq 1 ]]; then
    rm -rf "$workdir"
  fi
}
trap cleanup EXIT

cd "$workdir"

files=()
for ((page = 1; page <= pages; page++)); do
  filename="page${page}.jpg"
  url="https://img.yumpu.com/${doc_id}/${page}/${dimensions}/${image}"
  echo "=== Downloading page ${page} as ${filename} ==="
  if ! curl -fsSL "$url" --output "$filename"; then
    echo "Warning: failed to download page ${page} (${url}); skipping." >&2
    rm -f "$filename"
    continue
  fi
  files+=("$filename")
done

if [[ "${#files[@]}" -eq 0 ]]; then
  echo "Error: no pages were downloaded; nothing to convert." >&2
  exit 1
fi

echo
echo "Converting ${#files[@]} page(s) into ${output_abs} ..."
convert "${files[@]}" "$output_abs"

echo "Done: $output_abs"
