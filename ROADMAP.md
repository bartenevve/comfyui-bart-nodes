# Roadmap

## Booru sources

Source list: [lxfly2000's image-board gist](https://gist.github.com/lxfly2000/c183fcd23cfb447b2b9cb353e103c8fe).
Each candidate was probed anonymously on 2026-10-11 with a plain HTTP client (no cookies, no login), to see
whether a backend is feasible at all. A source that sits behind a bot challenge is **not** worked around:
it stays blocked until the site offers a supported way in (an API key, say).

Interface to implement: `booru/sources/base.py` (`count`, `page`, `resolve_file_url`, `download`); every
file URL read from a third-party response must pass `base.url_on_domain` for the site's own domain.

### Done

| Site | Engine | Notes |
| --- | --- | --- |
| Gelbooru | HTML scraper | `booru/sources/gelbooru.py` |
| yande.re | Moebooru JSON API | `booru/sources/moebooru.py` |

### Next, in order

1. **Konachan** (`konachan.com`, `konachan.net`) — Moebooru, `post.json` answered 200 on both. Subclass
   `MoebooruSource` with a different `name` / `origin` / `domain` (~5 lines + a registry entry + a test that
   the file host is accepted). Check where each site's file host lives (`konachan.com` vs a CDN domain) —
   `url_on_domain` is per-domain, so a CDN on another domain needs the check widened per source.
2. **Safebooru** (`safebooru.org`) and **Xbooru** (`xbooru.com`) — Gelbooru 0.2 `dapi` engine:
   `index.php?page=dapi&s=post&q=index&limit=100&pid=<page>&tags=…`, answers 200 anonymously
   (`json=1` for JSON on Safebooru, XML on both), count in the `<posts count="…">` header. One engine base
   class (like `MoebooruSource`), two subclasses. Pagination is by page number (`pid`), file URL built from
   the `directory`/`image` fields or `file_url` when present. Xbooru is R18 and served over plain http in the
   gist; use https if it answers (the probe did, over https).
3. **e621** (`e621.net`) — JSON API (`posts.json`) answered 200. From its public API docs (not verified
   here): a descriptive `User-Agent` is required, the tag limit is 40 and `page=` is capped (cursors
   `page=b<id>` / `a<id>` go deeper), so it needs its own engine class and a `fetch` option for a custom UA.
   The site is R18-heavy; tag-based filtering (`rating:s`) is the user's job, as with the other sources.

### Candidates needing more work

| Site | Probe result | What it would take |
| --- | --- | --- |
| Sankaku (`chan.sankakucomplex.com`) | the site redirects to a login page; `sankakuapi.com/posts` answered with JSON anonymously | a new engine; check whether file URLs are signed/expiring and whether anonymous access is meant to be used before building on it |
| e-shuushuu, Zerochan, Anime-Pictures | no JSON API; Zerochan and Anime-Pictures answered with a bot check / 503 | HTML scrapers at best, and the bot-checked ones are blocked as above |

### Blocked or unreachable

| Site | Why |
| --- | --- |
| Danbooru, Safebooru (donmai.us), Sonohara, donmai.moe | API requests get a Cloudflare challenge (403, "Just a moment...") — no anonymous access for non-browser clients |
| Lolibooru, 3dbooru (behoimi.org), One Yukkuri Place, tsundora | connection failed from the probing machine; retry later before deciding |
