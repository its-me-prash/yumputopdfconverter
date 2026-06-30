# Credits & bundled techniques

The `yumpu_to_pdf/yumpu_to_pdf.py` engine bundles approaches from the existing
open-source Yumpu downloaders. Each is credited below with the technique it
contributed. Please respect the licenses of the upstream projects and only
download documents you are authorised to access.

| Project | Language | Technique bundled here |
| --- | --- | --- |
| [EddyBer16/YumpuToPDFConverter](https://github.com/EddyBer16/YumpuToPDFConverter) | C++ | The `img.yumpu.com/<id>/<page>/<dims>/<name>` page-image scheme + ImageMagick `convert` PDF build. This repo descends from it (see `main.cpp`). |
| [ianmuscat/yumpu-scraper](https://github.com/ianmuscat/yumpu-scraper) | Go | The **`https://www.yumpu.com/document/json2/<id>` metadata endpoint**: parse `base_path`, the `pages[]` array (page count), and each page's `images.large` + `qss.large` to build exact image URLs — no guessing of file name / dimensions. This is the primary download path. |
| [MaikeMota/yumpu-downloader](https://github.com/MaikeMota/yumpu-downloader) | JS/Angular | Browser-side downloader UX reference. |
| [gnunixon/python-yumpu-sdk](https://github.com/gnunixon/python-yumpu-sdk) | Python | The official [Yumpu API](https://developers.yumpu.com/) route (account API token) as the fully sanctioned alternative for documents you own. |

## Added in this repo (not from upstream)

- Password-protected document handling: detect the
  `/document/protected/password/<id>` gate, parse and POST the password form
  (carrying hidden `_token` / `redirect` fields), and **fail loudly** if the
  password is rejected.
- Download validation via image magic bytes (never save an HTML error or
  placeholder as a page).
- Analysis-first output: keep page images in a folder so the content can be
  read/analysed; PDF generation is optional (`--pdf`).

## Verification note

The live Yumpu flow (password POST, json2 response shape) could not be tested
from the development sandbox because it blocks `www.yumpu.com` / `img.yumpu.com`
by egress policy. The code is defensive and falls back to the pattern-based
scheme with manual overrides. Validate where Yumpu is reachable.
