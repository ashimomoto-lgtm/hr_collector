#!/usr/bin/env python3
"""
GitHub Pages用インデックスページを生成する。

ステージングディレクトリ内の dashboard/, plans/, cta_output/ をスキャンし、
日付別リンク一覧の index.html を出力する。

使い方:
  python3 generate_index.py --root ./staging
"""

import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# 日付パターン
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def scan_files(root: Path) -> dict[str, dict[str, list[Path]]]:
    """日付 → カテゴリ → ファイル一覧 を返す"""
    categories = {
        "dashboard": root / "dashboard",
        "plans": root / "plans",
        "cta_output": root / "cta_output",
    }
    result: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))

    for cat_name, cat_dir in categories.items():
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.iterdir()):
            if f.name.startswith("."):
                continue
            m = DATE_RE.search(f.name)
            if m:
                result[m.group(1)][cat_name].append(f)

    return result


def file_icon(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".html":
        return "📊"
    elif ext == ".json":
        return "📋"
    elif ext == ".md":
        return "📝"
    elif ext == ".txt":
        return "📄"
    return "📎"


def file_label(cat: str, path: Path) -> str:
    if cat == "dashboard":
        return "ダッシュボード"
    elif cat == "plans":
        if path.suffix == ".md":
            return "企画案 (Markdown)"
        elif path.suffix == ".json":
            return "企画案 (JSON)"
    elif cat == "cta_output":
        if path.suffix == ".json":
            return "CTA結果 (JSON)"
        elif path.suffix == ".txt":
            return "CTA結果 (テキスト)"
        elif path.suffix == ".html":
            return "CTA結果"
    return path.name


def generate_html(data: dict[str, dict[str, list[Path]]], root: Path) -> str:
    sorted_dates = sorted(data.keys(), reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")

    rows = []
    for date in sorted_dates:
        cats = data[date]
        links = []
        # dashboard first, then plans, then cta
        for cat in ["dashboard", "plans", "cta_output"]:
            for f in cats.get(cat, []):
                rel = f.relative_to(root)
                icon = file_icon(f)
                label = file_label(cat, f)
                links.append(
                    f'<a href="{rel}" class="file-link">{icon} {label}</a>'
                )

        if not links:
            continue

        badge = ' <span class="badge-new">NEW</span>' if date == today else ""
        rows.append(f"""
      <div class="date-card">
        <div class="date-header">
          <span class="date-label">{date}{badge}</span>
        </div>
        <div class="file-list">
          {"".join(links)}
        </div>
      </div>""")

    count = len(sorted_dates)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Daily Pipeline — Archive</title>
  <style>
    :root {{
      --bg: #F8FAFC;
      --surface: #FFFFFF;
      --border: #E2E8F0;
      --text: #1E293B;
      --text-sub: #64748B;
      --blue: #3B82F6;
      --blue-bg: #EFF6FF;
      --green: #10B981;
      --green-bg: #ECFDF5;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Noto Sans JP', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
    }}
    .container {{ max-width: 800px; margin: 0 auto; padding: 24px 20px; }}

    header {{
      background: linear-gradient(135deg, #1E3A5F 0%, #2563EB 100%);
      color: white;
      padding: 32px 0;
      margin-bottom: 32px;
    }}
    header .container {{
      display: flex; justify-content: space-between;
      align-items: center; flex-wrap: wrap; gap: 16px;
    }}
    header h1 {{ font-size: 24px; font-weight: 700; }}
    header .meta {{ font-size: 14px; opacity: 0.85; }}

    .date-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 16px;
      transition: box-shadow 0.2s;
    }}
    .date-card:hover {{
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }}
    .date-header {{
      margin-bottom: 12px;
    }}
    .date-label {{
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
    }}
    .badge-new {{
      display: inline-block;
      background: var(--green);
      color: white;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 9999px;
      margin-left: 8px;
      vertical-align: middle;
    }}
    .file-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .file-link {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 6px 14px;
      background: var(--blue-bg);
      color: var(--blue);
      border-radius: 8px;
      text-decoration: none;
      font-size: 14px;
      font-weight: 500;
      transition: background 0.15s;
    }}
    .file-link:hover {{
      background: #DBEAFE;
    }}

    .empty {{
      text-align: center;
      padding: 60px 20px;
      color: var(--text-sub);
    }}

    footer {{
      text-align: center;
      padding: 32px 20px;
      color: var(--text-sub);
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>HR Daily Pipeline</h1>
      <div class="meta">{count} 日分のアーカイブ</div>
    </div>
  </header>
  <main class="container">
    {"".join(rows) if rows else '<div class="empty">まだデータがありません。パイプライン実行後に更新されます。</div>'}
  </main>
  <footer>
    1on1総研 HR Daily Pipeline &mdash; 自動生成
  </footer>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate index.html for GitHub Pages")
    parser.add_argument("--root", required=True, help="Staging directory to scan")
    args = parser.parse_args()

    root = Path(args.root)
    data = scan_files(root)
    html = generate_html(data, root)

    out = root / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"✅ index.html を生成しました: {out}  ({len(data)} 日分)")


if __name__ == "__main__":
    main()
