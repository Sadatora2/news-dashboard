import json
import os
import re
import html as _html
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import feedparser

PER_GENRE = 20
_UA = "Mozilla/5.0 (news-dashboard)"


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
    return datetime(*t[:6])


def parse_entries(content) -> list:
    d = feedparser.parse(content)
    out = []
    for e in d.entries:
        out.append({
            "title": _clean(e.get("title", ""), 300),
            "link": e.get("link", ""),
            "summary": _clean(e.get("summary", ""), 200),
            "published": _to_dt(e),
        })
    return out


def _download(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_feed(url: str, timeout: int = 10):
    try:
        content = _download(url, timeout)
        entries = parse_entries(content)
        return (entries, bool(entries))
    except Exception:
        return ([], False)


def _extract_meta_description(content) -> str:
    """記事ページのHTMLから og:description / meta description を抜き出す。"""
    if isinstance(content, bytes):
        content = content.decode("utf-8", "ignore")
    patterns = (
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
    )
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return _clean(m.group(1), 200)
    return ""


def fetch_summary(url: str, timeout: int = 5) -> str:
    """記事ページを取得して概要を返す。失敗時は空文字。"""
    try:
        content = _download(url, timeout)
        return _extract_meta_description(content)
    except Exception:
        return ""


def collect(feeds: dict, fetcher=fetch_feed, summary_fetcher=fetch_summary):
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
        items.sort(key=lambda e: e["published"] or datetime.min, reverse=True)
        by_genre[genre] = items[:PER_GENRE]
    # 概要が空の記事だけ、リンク先ページから並列で補完する
    need = [e for items in by_genre.values() for e in items
            if not e["summary"].strip() and e.get("link")]
    if need:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda e: summary_fetcher(e["link"]), need))
        for e, s in zip(need, results):
            if s:
                e["summary"] = s
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
            cards.append(
                '<a class="card" href="{link}" target="_blank" rel="noopener">'
                '<div class="ctitle">{title}</div>'
                '<div class="meta"><span class="src">{src}</span>'
                '<span class="time">{time}</span></div>'
                '<div class="sum">{sum}</div></a>'.format(
                    link=esc(e["link"]), title=esc(e["title"]),
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
.panel{{padding:12px 20px;display:grid;gap:10px;max-width:820px;margin:0 auto}}
.card{{display:block;background:#fff;border:1px solid #e2e2e6;border-radius:12px;padding:14px 16px;text-decoration:none;color:inherit}}
.card:hover{{border-color:#0a84ff}}
.ctitle{{font-size:16px;font-weight:600;line-height:1.4}}
.meta{{display:flex;gap:10px;font-size:12px;color:#888;margin:6px 0}}
.src{{color:#0a84ff}}
.sum{{font-size:13px;color:#555;line-height:1.5}}
.fail{{max-width:820px;margin:8px auto;padding:8px 20px;font-size:12px;color:#b00}}
@media(prefers-color-scheme:dark){{
body{{background:#000;color:#eee}}header,.tabs{{background:#1c1c1e;border-color:#333}}
.tab{{background:#1c1c1e;color:#eee;border-color:#444}}.card{{background:#1c1c1e;border-color:#333}}
.sum{{color:#aaa}}}}
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


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    feeds = load_feeds(os.path.join(here, "feeds.json"))
    by_genre, failures = collect(feeds)
    hml = render_html(by_genre, failures, datetime.now())
    out = os.path.join(here, "news.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(hml)
    print(f"生成: {out}")
    if failures:
        print("取得失敗:", ", ".join(failures))
    webbrowser.open("file://" + out.replace(os.sep, "/"))


if __name__ == "__main__":
    main()
