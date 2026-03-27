#!/usr/bin/env python3
"""
人事・1on1・マネジメント関連ホットトピック収集スクリプト

毎日100件以上の記事を収集し、日付入りMarkdownファイルに保存する。

使い方:
  pip3 install feedparser requests
  python3 collect_hr_topics.py

出力: ./output/YYYY-MM-DD_hr_topics.md
"""

import feedparser
import requests
import hashlib
import re
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import mktime, sleep

# ── 設定 ─────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = OUTPUT_DIR / f"{TODAY}_hr_topics.md"

# リクエスト設定
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 15

# ── キーワード ────────────────────────────────────────────
KEYWORDS = [
    "人事", "1on1", "ワンオンワン", "マネジメント", "管理職",
    "組織開発", "組織", "エンゲージメント", "人的資本", "キャリア",
    "採用", "離職", "オンボーディング", "評価制度", "目標管理",
    "MBO", "OKR", "タレントマネジメント", "リーダーシップ",
    "心理的安全性", "ウェルビーイング", "リスキリング", "人材育成",
    "ピープルマネジメント", "CHRO", "HRテック", "HR Tech",
    "働き方改革", "ダイバーシティ", "D&I", "DE&I",
    "サーベイ", "パルスサーベイ", "従業員体験", "EX",
]

# ── RSSフィード定義 ───────────────────────────────────────
# カテゴリ: (名前, URL, キーワードフィルタ必要か)
RSS_FEEDS = {
    # ── HR専門メディア ──
    "HR専門メディア": [
        ("HRzine", "https://hrzine.jp/rss/new/index.xml", False),
        ("日本の人事部（記事）", "https://jinjibu.jp/rss/?mode=atcl", False),
        ("日本の人事部（ニュース）", "https://jinjibu.jp/rss/?mode=news", False),
        ("日本の人事部（企業人事）", "https://jinjibu.jp/rss/?mode=news&type=1", False),
        ("日本の人事部（サービス）", "https://jinjibu.jp/rss/?mode=news&type=2", False),
        ("@人事", "https://at-jinji.jp/feed", False),
    ],

    # ── ビジネスメディア（キーワードフィルタ必要）──
    "ビジネスメディア": [
        ("東洋経済オンライン", "https://toyokeizai.net/list/feed/rss", True),
        ("ダイヤモンド・オンライン", "https://diamond.jp/list/feed/rss/dol", True),
        ("ITmedia ビジネス", "https://rss.itmedia.co.jp/rss/2.0/bizid.xml", True),
        ("プレジデントオンライン", "https://president.jp/list/rss", True),
        ("日経ビジネス", "https://business.nikkei.com/rss/sns/nb.rdf", True),
    ],

    # ── シンクタンク・研究所 ──
    "シンクタンク": [
        ("パーソル総合研究所（コラム）", "https://rc.persol-group.co.jp/wp-content/json/column.json", False),
        ("リクルートMC 調査データ", "https://www.recruit.co.jp/newsroom/pressrelease/feed/", True),
    ],

}


def fetch_persol_json(name: str, url: str) -> list[dict]:
    """パーソル総合研究所のJSON APIからエントリを取得"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        entries = []
        for post in data.get("posts", [])[:30]:  # 最新30件
            # 日付を正規化（"2026年03月25日" → "2026-03-25"）
            date_str = post.get("date", "")
            date_norm = re.sub(r"(\d{4})年(\d{2})月(\d{2})日", r"\1-\2-\3", date_str)
            post_link = post.get("post_link", "")
            if post_link and not post_link.startswith("http"):
                post_link = "https://rc.persol-group.co.jp" + post_link
            entries.append({
                "title": post.get("post_title", "（タイトルなし）").strip(),
                "url": post_link,
                "date": date_norm,
                "source": name,
                "summary": post.get("abstract", "").strip()[:200],
            })
        return entries
    except Exception as e:
        print(f"  ⚠ {name}: {e}")
        return []


def fetch_feed(name: str, url: str) -> list[dict]:
    """RSSフィードを取得してエントリのリストを返す"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        entries = []
        for entry in feed.entries:
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime.fromtimestamp(mktime(entry.published_parsed)).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if not published and hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published = datetime.fromtimestamp(mktime(entry.updated_parsed)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            entries.append({
                "title": entry.get("title", "（タイトルなし）").strip(),
                "url": entry.get("link", ""),
                "date": published,
                "source": name,
                "summary": _clean_html(entry.get("summary", "")),
            })
        return entries
    except Exception as e:
        print(f"  ⚠ {name}: {e}")
        return []


def _clean_html(text: str) -> str:
    """HTMLタグを除去して要約を整形"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200] if text else ""


def matches_keyword(entry: dict) -> bool:
    """タイトルまたは要約にキーワードが含まれるか判定"""
    text = (entry["title"] + " " + entry["summary"]).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def dedup_entries(entries: list[dict]) -> list[dict]:
    """URL（正規化）ベースで重複除去"""
    seen = set()
    result = []
    for e in entries:
        # URLからクエリパラメータの一部を除去して正規化
        url_key = re.sub(r"[?&](utm_\w+|ref|source|from)=[^&]*", "", e["url"])
        key = hashlib.md5(url_key.encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def generate_markdown(entries: list[dict], stats: dict) -> str:
    """収集結果をMarkdownに変換"""
    lines = []
    lines.append(f"# HR・マネジメント ホットトピック ({TODAY})")
    lines.append("")
    lines.append(f"> 収集日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 総記事数: **{len(entries)}件**")
    lines.append("")

    # 統計
    lines.append("## 収集サマリー")
    lines.append("")
    lines.append("| カテゴリ | フィード数 | 取得件数 | エラー |")
    lines.append("|---------|-----------|---------|-------|")
    for cat, s in stats.items():
        lines.append(f"| {cat} | {s['feeds']} | {s['count']} | {s['errors']} |")
    lines.append("")

    # ソース別に記事をグルーピング
    by_source = {}
    for e in entries:
        by_source.setdefault(e["source"], []).append(e)

    # カテゴリ順で出力
    for category, feeds in RSS_FEEDS.items():
        feed_names = {f[0] for f in feeds}
        category_entries = []
        for name in feed_names:
            if name in by_source:
                category_entries.extend(by_source[name])

        if not category_entries:
            continue

        lines.append(f"## {category}")
        lines.append("")

        for entry in category_entries:
            date_str = f" ({entry['date']})" if entry["date"] else ""
            lines.append(f"### [{entry['title']}]({entry['url']})")
            lines.append(f"**{entry['source']}**{date_str}")
            if entry["summary"]:
                lines.append(f"> {entry['summary']}")
            lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print(f"HR・マネジメント ホットトピック収集")
    print(f"日付: {TODAY}")
    print(f"出力: {OUTPUT_FILE}")
    print("=" * 60)

    all_entries = []
    stats = {}

    for category, feeds in RSS_FEEDS.items():
        print(f"\n📂 {category} ({len(feeds)}フィード)")
        cat_entries = []
        errors = 0

        for name, url, needs_filter in feeds:
            if url.endswith(".json"):
                entries = fetch_persol_json(name, url)
            else:
                entries = fetch_feed(name, url)
            if not entries:
                errors += 1
                continue

            # キーワードフィルタが必要なフィード（ビジネスメディア等）
            if needs_filter:
                before = len(entries)
                entries = [e for e in entries if matches_keyword(e)]
                print(f"  ✓ {name}: {len(entries)}件 (フィルタ前: {before})")
            else:
                print(f"  ✓ {name}: {len(entries)}件")

            cat_entries.extend(entries)
            sleep(0.5)  # サーバー負荷軽減

        stats[category] = {
            "feeds": len(feeds),
            "count": len(cat_entries),
            "errors": errors,
        }
        all_entries.extend(cat_entries)

    # 重複除去
    before_dedup = len(all_entries)
    all_entries = dedup_entries(all_entries)
    print(f"\n重複除去: {before_dedup} → {len(all_entries)}件")

    # 日付でソート（新しい順）
    all_entries.sort(key=lambda e: e["date"] or "0000-00-00", reverse=True)

    # Markdown生成・保存
    md = generate_markdown(all_entries, stats)
    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"✓ 完了: {len(all_entries)}件を収集")
    print(f"  保存先: {OUTPUT_FILE}")
    if len(all_entries) < 100:
        print(f"  ⚠ 100件未満です。フィードの応答状況を確認してください。")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
