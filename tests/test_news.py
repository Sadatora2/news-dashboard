# tests/test_news.py
import json
from pathlib import Path
from datetime import datetime
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import news


def _fixture_text():
    p = Path(__file__).resolve().parent / "fixtures" / "sample_rss.xml"
    return p.read_text(encoding="utf-8")


# --- Task 1: load_feeds ---

def test_load_feeds_returns_genres(tmp_path):
    p = tmp_path / "feeds.json"
    p.write_text(json.dumps({
        "国内一般": [{"name": "NHK主要", "url": "http://x/rss"}]
    }, ensure_ascii=False), encoding="utf-8")
    result = news.load_feeds(str(p))
    assert "国内一般" in result
    assert result["国内一般"][0]["name"] == "NHK主要"
    assert result["国内一般"][0]["url"] == "http://x/rss"


# --- Task 2: parse_entries ---

def test_parse_entries_extracts_fields():
    entries = news.parse_entries(_fixture_text())
    assert len(entries) == 2
    titles = {e["title"] for e in entries}
    assert titles == {"記事A", "記事B"}
    a = next(e for e in entries if e["title"] == "記事A")
    assert a["link"] == "https://example.com/a"
    assert "記事Aの概要" in a["summary"]
    assert isinstance(a["published"], datetime)


def test_parse_entries_handles_missing_date():
    xml = ('<?xml version="1.0"?><rss version="2.0"><channel>'
           '<item><title>日付なし</title><link>https://example.com/x</link>'
           '<description>本文</description></item></channel></rss>')
    entries = news.parse_entries(xml)
    assert entries[0]["published"] is None


# --- Task 3: fetch_feed ---

def test_fetch_feed_failure_returns_empty_and_false(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(news, "_download", boom)
    entries, ok = news.fetch_feed("http://unreachable.invalid/rss", timeout=1)
    assert entries == []
    assert ok is False


def test_fetch_feed_success(monkeypatch):
    monkeypatch.setattr(news, "_download", lambda url, timeout: _fixture_text())
    entries, ok = news.fetch_feed("http://x/rss")
    assert ok is True
    assert len(entries) == 2


# --- Task 4: collect ---

def test_collect_aggregates_sorts_and_tags_source():
    feeds = {"国内一般": [
        {"name": "S1", "url": "u1"},
        {"name": "S2", "url": "u2"},
    ]}
    def fake_fetcher(url, timeout=10):
        if url == "u1":
            return ([{"title": "古い", "link": "l1", "summary": "",
                      "published": datetime(2026, 8, 1)}], True)
        return ([{"title": "新しい", "link": "l2", "summary": "",
                  "published": datetime(2026, 8, 10)}], True)
    by_genre, failures = news.collect(feeds, fetcher=fake_fetcher,
                                      page_fetcher=lambda *a, **k: ("", ""))
    titles = [e["title"] for e in by_genre["国内一般"]]
    assert titles == ["新しい", "古い"]
    assert by_genre["国内一般"][0]["source"] == "S2"
    assert failures == []


def test_collect_records_failures_and_caps_per_genre():
    n = news.PER_GENRE
    many = [{"title": f"t{i}", "link": f"l{i}", "summary": "",
             "published": datetime(2026, 8, i % 28 + 1)} for i in range(n + 10)]
    feeds = {"IT・AI": [
        {"name": "多い", "url": "big"},
        {"name": "死んでる", "url": "dead"},
    ]}
    def fake_fetcher(url, timeout=10):
        return (many, True) if url == "big" else ([], False)
    by_genre, failures = news.collect(feeds, fetcher=fake_fetcher,
                                      page_fetcher=lambda *a, **k: ("", ""))
    assert len(by_genre["IT・AI"]) == news.PER_GENRE
    assert "IT・AI/死んでる" in failures


# --- 改良: 概要+サムネイル補完(fetch_page_meta / collect enrichment) ---

def test_extract_meta_description_og():
    html = ('<html><head>'
            '<meta property="og:description" content="OGの概要テキスト">'
            '</head><body></body></html>')
    assert news._extract_meta_description(html) == "OGの概要テキスト"


def test_extract_meta_description_fallback_name():
    html = ('<html><head>'
            '<meta name="description" content="name属性の概要">'
            '</head></html>')
    assert news._extract_meta_description(html) == "name属性の概要"


def test_extract_meta_description_none():
    html = "<html><head><title>概要なし</title></head></html>"
    assert news._extract_meta_description(html) == ""


def test_extract_og_image():
    html = '<meta property="og:image" content="https://ex.com/pic.jpg">'
    assert news._extract_og_image(html) == "https://ex.com/pic.jpg"


def test_extract_og_image_none():
    html = "<html><head><title>画像なし</title></head></html>"
    assert news._extract_og_image(html) == ""


def test_fetch_page_meta_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(news, "_download", boom)
    assert news.fetch_page_meta("http://x.invalid/a") == ("", "")


def test_fetch_page_meta_success(monkeypatch):
    html = ('<meta property="og:description" content="取得した概要">'
            '<meta property="og:image" content="https://ex.com/a.jpg">')
    monkeypatch.setattr(news, "_download", lambda url, timeout: html)
    assert news.fetch_page_meta("http://x/a") == ("取得した概要", "https://ex.com/a.jpg")


def test_collect_fills_image_and_empty_summary():
    feeds = {"国内一般": [{"name": "S", "url": "u"}]}
    def fake_fetcher(url, timeout=10):
        return ([
            {"title": "空概要", "link": "https://ex.com/empty", "summary": "",
             "published": datetime(2026, 8, 2), "image": ""},
            {"title": "既概要", "link": "https://ex.com/full", "summary": "元の概要",
             "published": datetime(2026, 8, 1), "image": ""},
        ], True)
    def fake_page(url, timeout=5):
        return ("補完概要", "https://ex.com/pic.jpg")
    by_genre, _ = news.collect(feeds, fetcher=fake_fetcher, page_fetcher=fake_page)
    items = {e["title"]: e for e in by_genre["国内一般"]}
    assert items["空概要"]["summary"] == "補完概要"   # 空は補完
    assert items["既概要"]["summary"] == "元の概要"   # 既存は保持
    assert items["空概要"]["image"] == "https://ex.com/pic.jpg"  # 画像は付与
    assert items["既概要"]["image"] == "https://ex.com/pic.jpg"


def test_dedupe_merges_similar_but_keeps_dated_series():
    items = [
        {"title": "速報 地震 震度3 津波の心配なし", "link": "l1", "summary": "",
         "published": datetime(2026, 8, 10), "image": ""},
        # 言い回し違いだが数字(3)一致 → 似た記事としてまとめる
        {"title": "速報 地震 震度3 津波被害の心配なし", "link": "l2", "summary": "",
         "published": datetime(2026, 8, 10), "image": ""},
        {"title": "ロシア侵攻 8月8日の動き", "link": "l3", "summary": "",
         "published": datetime(2026, 8, 8), "image": ""},
        # 見出しは酷似だが数字(日付)が違う → 別記事として残す
        {"title": "ロシア侵攻 8月7日の動き", "link": "l4", "summary": "",
         "published": datetime(2026, 8, 7), "image": ""},
    ]
    out = news._dedupe(items)
    titles = [e["title"] for e in out]
    assert sum("地震" in t for t in titles) == 1     # 似た速報は1件に
    assert sum("ロシア侵攻" in t for t in titles) == 2  # 日付違いは両方残る


def test_collect_dedupes_same_article():
    # 2ソースが同じ記事(同一URL・同一タイトル)を配信 → 1件にまとまる
    feeds = {"国内一般": [{"name": "A", "url": "ua"}, {"name": "B", "url": "ub"}]}
    art = {"title": "同じ記事", "link": "https://x/1", "summary": "",
           "published": datetime(2026, 8, 10), "image": ""}
    other = {"title": "別記事", "link": "https://x/2", "summary": "",
             "published": datetime(2026, 8, 9), "image": ""}
    def fake_fetcher(url, timeout=10):
        return ([dict(art), dict(other)], True) if url == "ua" else ([dict(art)], True)
    by_genre, _ = news.collect(feeds, fetcher=fake_fetcher,
                               page_fetcher=lambda *a, **k: ("", ""))
    titles = [e["title"] for e in by_genre["国内一般"]]
    assert titles.count("同じ記事") == 1   # 重複は1件に集約
    assert titles.count("別記事") == 1


def test_collect_dedupes_across_genres_general_yields():
    # 同じ記事が「国内一般」と専門カテゴリの両方に来たら、専門側に残し国内一般から消す
    art = {"title": "共通ニュース", "link": "https://x/1", "summary": "",
           "published": datetime(2026, 8, 10), "image": ""}
    feeds = {"国内一般": [{"name": "G", "url": "ug"}],
             "経済・ビジネス": [{"name": "E", "url": "ue"}]}
    def fake_fetcher(url, timeout=10):
        return ([dict(art)], True)
    by_genre, _ = news.collect(feeds, fetcher=fake_fetcher,
                               page_fetcher=lambda *a, **k: ("", ""))
    assert [e["title"] for e in by_genre["経済・ビジネス"]] == ["共通ニュース"]
    assert by_genre["国内一般"] == []          # 総合側は専門側に譲る


def test_collect_diversifies_sources():
    # A が新着大量、B は少数。多様化で少数ソースBも埋もれず全部入る
    n = news.PER_GENRE
    a = [{"title": f"a{i}", "link": f"la{i}", "summary": "x",
          "published": datetime(2026, 8, 20, 12, i % 60), "image": ""}
         for i in range(n + 20)]
    b = [{"title": f"b{i}", "link": f"lb{i}", "summary": "x",
          "published": datetime(2026, 8, 19, 12, i), "image": ""} for i in range(5)]
    feeds = {"スポーツ": [{"name": "A", "url": "ua"}, {"name": "B", "url": "ub"}]}
    def fake_fetcher(url, timeout=10):
        return (a, True) if url == "ua" else (b, True)
    by_genre, _ = news.collect(feeds, fetcher=fake_fetcher,
                               page_fetcher=lambda *x, **k: ("", ""))
    srcs = [e["source"] for e in by_genre["スポーツ"]]
    assert len(by_genre["スポーツ"]) == n
    assert srcs.count("B") == 5          # 少数ソースも全件採用される
    assert srcs.count("A") == n - 5


def test_collect_uses_cache_and_skips_fetch():
    feeds = {"国内一般": [{"name": "S", "url": "u"}]}
    def fake_fetcher(url, timeout=10):
        return ([{"title": "記事", "link": "https://ex.com/a", "summary": "",
                  "published": datetime(2026, 8, 1), "image": ""}], True)
    calls = []
    def counting_page(url, timeout=5):
        calls.append(url)
        return ("新規", "https://ex.com/new.jpg")
    cache = {"https://ex.com/a": ("キャッシュ概要", "https://ex.com/cached.jpg")}
    by_genre, _ = news.collect(feeds, fetcher=fake_fetcher,
                               page_fetcher=counting_page, cache=cache)
    e = by_genre["国内一般"][0]
    assert calls == []                                  # 取得は呼ばれない
    assert e["summary"] == "キャッシュ概要"              # キャッシュから補完
    assert e["image"] == "https://ex.com/cached.jpg"


# --- Task 5: render_html ---

def test_render_html_contains_core_elements():
    by_genre = {"国内一般": [{
        "title": "見出しテスト", "link": "https://example.com/a",
        "summary": "概要テスト", "published": datetime(2026, 8, 13, 9, 0),
        "source": "NHK主要",
    }]}
    hml = news.render_html(by_genre, ["国内一般/死んでる"], datetime(2026, 8, 13, 9, 30))
    assert "見出しテスト" in hml
    assert 'href="https://example.com/a"' in hml
    assert "NHK主要" in hml
    assert "国内一般" in hml
    assert "最終更新" in hml
    assert hml.strip().lower().startswith("<!doctype html>")


def test_render_html_omits_failure_footer():
    by_genre = {"国内一般": [{
        "title": "見出し", "link": "https://example.com/a",
        "summary": "概要", "published": datetime(2026, 8, 13, 9, 0),
        "source": "NHK主要",
    }]}
    hml = news.render_html(by_genre, ["国内一般/落ちたソース"], datetime(2026, 8, 13, 9, 30))
    assert "取得失敗" not in hml            # 失敗表示はページに出さない
    assert "落ちたソース" not in hml


def test_render_html_escapes_titles():
    by_genre = {"国内一般": [{
        "title": "危険<script>", "link": "https://example.com/a",
        "summary": "", "published": None, "source": "S",
    }]}
    hml = news.render_html(by_genre, [], datetime(2026, 8, 13, 9, 30))
    assert "<script>" not in hml.split("危険")[1][:20]
