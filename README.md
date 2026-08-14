# 毎日ニュース ダッシュボード

4ジャンル+αの最新ニュースを、RSSから取得して1枚のHTMLにまとめて表示するツール。

## 使い方(ローカル)

`ニュース.bat` をダブルクリック → 最新ニュースを取得して `news.html` を生成し、ブラウザで開く。

## カテゴリー・参照サイト

`feeds.json` で管理(国内一般 / 経済・ビジネス / IT・AI / スポーツ / エンタメ・芸能 / ゲーム・アニメ / 海外・国際)。
各記事はリンク先ページから概要(og:description)とサムネイル画像(og:image)を補完する。
一度取得した内容は `cache.json` に保存し、再実行を高速化する。

## クラウド自動更新(GitHub Pages)

`.github/workflows/deploy.yml` で日中(JST 7:00〜23:00)に毎時自動生成し、GitHub Pages に公開する。
PCが起動していなくても更新される。公開URL:

- https://sadatora2.github.io/news-dashboard/

手動更新はGitHubの Actions タブから「Run workflow」で実行できる。

## 構成

| ファイル | 役割 |
|---|---|
| `news.py` | RSS取得→概要/画像補完→HTML生成(`--no-browser` でブラウザを開かない) |
| `feeds.json` | ジャンルごとの参照RSS一覧 |
| `ニュース.bat` | ローカル起動用ランチャー |
| `.github/workflows/deploy.yml` | 定期実行してPagesへ公開 |
| `tests/` | 単体テスト(`python -m pytest`) |

## 開発

```
pip install -r requirements.txt
python -m pytest
```
