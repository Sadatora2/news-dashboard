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
    by_genre, failures = news.collect(feeds, fetcher=fake_fetcher)
    titles = [e["title"] for e in by_genre["国内一般"]]
    assert titles == ["新しい", "古い"]
    assert by_genre["国内一般"][0]["source"] == "S2"
    assert failures == []


def test_collect_records_failures_and_caps_20():
    many = [{"title": f"t{i}", "link": f"l{i}", "summary": "",
             "published": datetime(2026, 8, i % 28 + 1)} for i in range(25)]
    feeds = {"IT・AI": [
        {"name": "多い", "url": "big"},
        {"name": "死んでる", "url": "dead"},
    ]}
    def fake_fetcher(url, timeout=10):
        return (many, True) if url == "big" else ([], False)
    by_genre, failures = news.collect(feeds, fetcher=fake_fetcher)
    assert len(by_genre["IT・AI"]) == 20
    assert "IT・AI/死んでる" in failures


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
    assert "死んでる" in hml
    assert hml.strip().lower().startswith("<!doctype html>")


def test_render_html_escapes_titles():
    by_genre = {"国内一般": [{
        "title": "危険<script>", "link": "https://example.com/a",
        "summary": "", "published": None, "source": "S",
    }]}
    hml = news.render_html(by_genre, [], datetime(2026, 8, 13, 9, 30))
    assert "<script>" not in hml.split("危険")[1][:20]
