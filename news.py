import json
import os
import re
import html as _html
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import feedparser

PER_GENRE = 30
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
}


def load_feeds(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _clean(text: str, limit: int = 200) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = _html.unescape(text).strip()
    return text[:limit]


def _to_dt(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    # feedparser の published_parsed は UTC。表示・並び替えを JST に統一する
    return datetime(*t[:6]) + timedelta(hours=9)


def parse_entries(content) -> list:
    d = feedparser.parse(content)
    out = []
    for e in d.entries:
        out.append({
            "title": _clean(e.get("title", ""), 300),
            "link": e.get("link", ""),
            "summary": _clean(e.get("summary", ""), 200),
            "published": _to_dt(e),
            "image": "",
        })
    return out


def _download(url: str, timeout: int):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_feed(url: str, timeout: int = 10):
    try:
        content = _download(url, timeout)
        entries = parse_entries(content)
        return (entries, bool(entries))
    except Exception:
        return ([], False)


def _meta_content(content, key_attr, key_val) -> str:
    """<meta {key_attr}="{key_val}" content="..."> の content を返す(属性順は両対応)。"""
    if isinstance(content, bytes):
        content = content.decode("utf-8", "ignore")
    patterns = (
        rf'<meta[^>]+{key_attr}=["\']{key_val}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+{key_attr}=["\']{key_val}["\']',
    )
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _extract_meta_description(content) -> str:
    """og:description → meta description の順で概要を抜き出す。"""
    for attr, val in (("property", "og:description"), ("name", "description")):
        s = _meta_content(content, attr, val)
        if s:
            return _clean(s, 200)
    return ""


def _extract_og_image(content) -> str:
    """og:image → twitter:image の順でサムネイル画像URLを抜き出す。"""
    for attr, val in (("property", "og:image"), ("name", "twitter:image")):
        s = _meta_content(content, attr, val)
        if s:
            return _html.unescape(s)
    return ""


def fetch_page_meta(url: str, timeout: int = 5):
    """記事ページを取得して (概要, 画像URL) を返す。失敗時は ("", "")。"""
    try:
        content = _download(url, timeout)
        return (_extract_meta_description(content), _extract_og_image(content))
    except Exception:
        return ("", "")


def _diversify(items, limit):
    """新しい順を基本にしつつ、1ソースの独占を避けて上位 limit 件を選ぶ。"""
    ordered = sorted(items, key=lambda e: e["published"] or datetime.min, reverse=True)
    n_src = len({e["source"] for e in ordered}) or 1
    cap = max(3, -(-limit // n_src))   # ソースごとの上限(limit/ソース数の切り上げ)
    counts, chosen, chosen_ids = {}, [], set()
    for e in ordered:                  # 1巡目: ソース上限まで新しい順に採用
        if len(chosen) >= limit:
            break
        if counts.get(e["source"], 0) < cap:
            counts[e["source"]] = counts.get(e["source"], 0) + 1
            chosen.append(e)
            chosen_ids.add(id(e))
    for e in ordered:                  # 2巡目: 埋め足りなければ残りを新しい順で補充
        if len(chosen) >= limit:
            break
        if id(e) not in chosen_ids:
            chosen.append(e)
    chosen.sort(key=lambda e: e["published"] or datetime.min, reverse=True)
    return chosen


def collect(feeds: dict, fetcher=fetch_feed, page_fetcher=fetch_page_meta, cache=None):
    by_genre = {}
    failures = []
    for genre, sources in feeds.items():
        items = []
        for src in sources:
            entries, ok = fetcher(src["url"])
            if not ok:
                failures.append(f"{genre}/{src['name']}")
                continue
            for e in entries:
                e = dict(e)
                e["source"] = src["name"]
                items.append(e)
        by_genre[genre] = _diversify(items, PER_GENRE)
    # 表示する記事ごとにページから概要・画像を補完する(既知URLはキャッシュ利用)
    if cache is None:
        cache = {}
    targets = [e for items in by_genre.values() for e in items if e.get("link")]
    todo = [e for e in targets if e["link"] not in cache]
    if todo:
        with ThreadPoolExecutor(max_workers=24) as ex:
            results = list(ex.map(lambda e: page_fetcher(e["link"]), todo))
        for e, res in zip(todo, results):
            if res != ("", ""):          # 失敗は保存せず次回再取得
                cache[e["link"]] = res
    for e in targets:
        summary, image = cache.get(e["link"], ("", ""))
        if image and not e.get("image"):
            e["image"] = image
        if summary and not e["summary"].strip():
            e["summary"] = summary
    return by_genre, failures


def _fmt_time(dt):
    return dt.strftime("%m/%d %H:%M") if dt else ""


def render_html(by_genre: dict, failures: list, updated_at) -> str:
    esc = _html.escape
    genres = list(by_genre.keys())
    tabs = "".join(
        f'<button class="tab" data-g="{i}" onclick="show({i})">{esc(g)}</button>'
        for i, g in enumerate(genres)
    )
    panels = []
    for i, g in enumerate(genres):
        cards = []
        for e in by_genre[g]:
            img = e.get("image", "")
            thumb = (f'<img class="thumb" src="{esc(img)}" loading="lazy" alt="">'
                     if img else '<div class="thumb ph"></div>')
            cards.append(
                '<a class="card" href="{link}" target="_blank" rel="noopener">'
                '{thumb}'
                '<div class="body"><div class="ctitle">{title}</div>'
                '<div class="meta"><span class="src">{src}</span>'
                '<span class="time">{time}</span></div>'
                '<div class="sum">{sum}</div></div></a>'.format(
                    link=esc(e["link"]), thumb=thumb, title=esc(e["title"]),
                    src=esc(e["source"]), time=esc(_fmt_time(e["published"])),
                    sum=esc(e["summary"]),
                )
            )
        style = "" if i == 0 else ' style="display:none"'
        panels.append(f'<div class="panel" data-g="{i}"{style}>' + "".join(cards) + "</div>")
    fail_html = ""
    if failures:
        fail_html = '<div class="fail">取得失敗: ' + esc(", ".join(failures)) + "</div>"
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>毎日ニュース</title>
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;background:#f5f5f7;color:#1a1a1a}}
header{{padding:16px 20px;background:#fff;border-bottom:1px solid #e2e2e6;position:sticky;top:0;z-index:10}}
h1{{margin:0;font-size:20px}}
.updated{{font-size:12px;color:#888;margin-top:4px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 20px;background:#fff;border-bottom:1px solid #e2e2e6;position:sticky;top:64px;z-index:9}}
.tab{{border:1px solid #d0d0d5;background:#fff;border-radius:20px;padding:6px 16px;font-size:14px;cursor:pointer}}
.tab.active{{background:#0a84ff;color:#fff;border-color:#0a84ff}}
.panel{{padding:12px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr));gap:12px;max-width:1280px;margin:0 auto}}
.card{{display:flex;gap:12px;background:#fff;border:1px solid #e2e2e6;border-radius:12px;padding:12px;text-decoration:none;color:inherit}}
.card:hover{{border-color:#0a84ff}}
.thumb{{flex:0 0 104px;width:104px;height:78px;border-radius:8px;object-fit:cover;background:#ececf0}}
.thumb.ph{{display:flex}}
.body{{min-width:0;flex:1}}
.ctitle{{font-size:16px;font-weight:600;line-height:1.4}}
.meta{{display:flex;gap:10px;font-size:12px;color:#888;margin:6px 0}}
.src{{color:#0a84ff}}
.sum{{font-size:13px;color:#555;line-height:1.5}}
.fail{{max-width:820px;margin:8px auto;padding:8px 20px;font-size:12px;color:#b00}}
@media(prefers-color-scheme:dark){{
body{{background:#000;color:#eee}}header,.tabs{{background:#1c1c1e;border-color:#333}}
.tab{{background:#1c1c1e;color:#eee;border-color:#444}}.card{{background:#1c1c1e;border-color:#333}}
.thumb{{background:#2c2c2e}}.sum{{color:#aaa}}}}
</style></head><body>
<header><h1>毎日ニュース</h1><div class="updated">最終更新: {updated_at.strftime('%Y-%m-%d %H:%M')}</div></header>
<div class="tabs">{tabs}</div>
{''.join(panels)}
{fail_html}
<script>
function show(i){{
  document.querySelectorAll('.panel').forEach(p=>p.style.display=(p.dataset.g==i)?'grid':'none');
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.g==i));
}}
show(0);
</script></body></html>"""


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {k: tuple(v) for k, v in json.load(f).items()}
    except Exception:
        return {}


def _save_cache(path, cache, keep_links):
    trimmed = {k: list(v) for k, v in cache.items() if k in keep_links}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False)
    except Exception:
        pass


def main(open_browser=True):
    here = os.path.dirname(os.path.abspath(__file__))
    feeds = load_feeds(os.path.join(here, "feeds.json"))
    cache_path = os.path.join(here, "cache.json")
    cache = _load_cache(cache_path)
    by_genre, failures = collect(feeds, cache=cache)
    keep = {e["link"] for items in by_genre.values() for e in items if e.get("link")}
    _save_cache(cache_path, cache, keep)
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    hml = render_html(by_genre, failures, now_jst)
    out = os.path.join(here, "news.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(hml)
    print(f"生成: {out}")
    if failures:
        print("取得失敗:", ", ".join(failures))
    if open_browser:
        webbrowser.open("file://" + out.replace(os.sep, "/"))


if __name__ == "__main__":
    import sys
    main(open_browser="--no-browser" not in sys.argv)
