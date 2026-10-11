# Roadmap

## Booru sources

Source list: [lxfly2000's image-board gist](https://gist.github.com/lxfly2000/c183fcd23cfb447b2b9cb353e103c8fe).
Every candidate was probed anonymously on 2026-10-11 with a plain HTTP client (no cookies, no login) to see
whether a backend is feasible at all. A site behind a bot challenge is **not** worked around: it stays
blocked until the site offers a supported way in (an API key, say).

Interface to implement: `booru/sources/base.py` (`count`, `page`, `resolve_file_url`, `download`). Every file
URL read from a third-party response must pass `base.url_on_domain` for the site's own domain.

### Done

| Site (`source` value) | Engine | Code |
| --- | --- | --- |
| Gelbooru (`gelbooru`) | HTML scraper (its API wants a key) | `booru/sources/gelbooru.py` |
| yande.re (`yandere`) | Moebooru JSON | `booru/sources/moebooru.py` |
| Konachan (`konachan`, `konachan_net`) | Moebooru JSON | `booru/sources/moebooru.py` |
| Safebooru (`safebooru`), Xbooru (`xbooru`) | Gelbooru 0.2 `dapi` JSON | `booru/sources/dapi.py` |

### Not done, and why

| Site | Probe result | Why it is not an easy add |
| --- | --- | --- |
| **e621** | `posts.json` answers 200 anonymously | Medium, not hard. A distinct engine: tags are nested per category instead of one string, `file.url` can be null for posts hidden from anonymous users, results are capped by page number (~750 pages of up to 320), and its API rules ask for a descriptive, unique `User-Agent` — `booru/fetch.py` currently sends one browser-like UA for every site, so it needs a per-source UA first. Count comes from a separate `counts/posts.json`. (Details from the site's public API docs, not verified here.) Do this next. |
| **Sankaku** (`chan.sankakucomplex.com`) | The site redirects to a login page; `sankakuapi.com/posts` answered with JSON anonymously | Unknown rules: before building on it check that anonymous use is intended, whether file URLs are signed and expire (that would break the preview-then-execute cache), and how aggressively it rate-limits. A new engine either way (string ids, nested JSON). |
| **Danbooru**, **Safebooru (donmai.us)**, **Sonohara**, **donmai.moe** | Every API request gets a Cloudflare challenge (HTTP 403, "Just a moment...") | Blocked for non-browser clients. Bypassing a bot check is out of scope; revisit if the site documents API-key access that skips the challenge. The engine itself (JSON, `counts/posts.json`) would be easy. |
| **Zerochan** | HTTP 503 "Checking browser..." | Bot check, same as above; also has no stable public JSON listing. |
| **Anime-Pictures** | Sits behind Cloudflare (the 301 came from it) | Bot check; JSON API not probed past that. |
| **e-shuushuu** | HTML only, answers 200 | No API: would be an HTML scraper like Gelbooru's, with its own pagination and no count header. Low value for the effort. |
| **Lolibooru** | Connection timeout (curl exit 28) | Unreachable from the probing machine; retry later. If it is Moebooru-based it is a 5-line subclass like Konachan. |
| **3dbooru** (behoimi.org) | Connection timeout (curl exit 28) | Unreachable; also an old Danbooru 1.x engine, so it needs its own (small) JSON client. |
| **One Yukkuri Place** (yukkuri.shii.org) | DNS lookup failed (curl exit 6) | Host does not resolve; may be gone. |
| **tsundora** | Connection refused (curl exit 7) | Unreachable; unknown engine. |
