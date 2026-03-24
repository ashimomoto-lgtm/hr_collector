#!/usr/bin/env python3
"""
HR日次ダッシュボード（HTML）を生成するスクリプト

入力:
  - output/YYYY-MM-DD_hr_topics.md   (収集済みトピック)
  - plans/YYYY-MM-DD_content_plans.json (企画案)

出力:
  - dashboard/YYYY-MM-DD_dashboard.html

使い方:
  export GEMINI_API_KEY="..."
  python3 generate_dashboard.py              # 当日分
  python3 generate_dashboard.py 2026-03-17   # 日付指定
"""

import os
import sys
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from html import escape

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("google-genai が必要です: pip3 install google-genai")
    sys.exit(1)

# ── 設定 ─────────────────────────────────────────────────
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("環境変数 GEMINI_API_KEY が未設定です。")
    sys.exit(1)

MODEL = "gemini-2.5-flash"
BASE_DIR = Path(__file__).parent
TOPICS_DIR = BASE_DIR / "output"
PLANS_DIR = BASE_DIR / "plans"
DASH_DIR = BASE_DIR / "dashboard"
DASH_DIR.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")


# ── ファイル探索 ──────────────────────────────────────────
def find_file(directory: Path, pattern: str, date: str) -> Path | None:
    f = directory / pattern.format(date=date)
    if f.exists():
        return f
    files = sorted(directory.glob(pattern.format(date="*")), reverse=True)
    return files[0] if files else None


# ── トピックMD → 構造化リスト ─────────────────────────────
def parse_topics_md(md_path: Path) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    entries = []
    current = None
    current_category = ""

    for line in text.split("\n"):
        if line.startswith("## ") and not line.startswith("## 収集サマリー"):
            current_category = line[3:].strip()
        elif line.startswith("### ["):
            m = re.match(r"### \[(.+?)\]\((.+?)\)", line)
            if m:
                current = {
                    "title": m.group(1),
                    "url": m.group(2),
                    "source": "",
                    "date": "",
                    "summary": "",
                    "category": current_category,
                }
                entries.append(current)
        elif current and line.startswith("**"):
            m = re.match(r"\*\*(.+?)\*\*\s*(?:\((.+?)\))?", line)
            if m:
                current["source"] = m.group(1)
                current["date"] = m.group(2) or ""
        elif current and line.startswith("> "):
            current["summary"] = line[2:].strip()

    return entries


# ── JSON修復ユーティリティ ─────────────────────────────────
def _fix_json(raw: str) -> str:
    """LLM出力のJSON文字列を修復する"""
    # ```json``` ブロックを剥がす
    m = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)

    # 文字列値内の全角引用符・制御文字を修復
    result = []
    i = 0
    in_string = False
    while i < len(raw):
        ch = raw[i]
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
        else:
            if ch == '\\':
                result.append(ch)
                if i + 1 < len(raw):
                    i += 1
                    result.append(raw[i])
            elif ch == '"':
                rest = raw[i+1:].lstrip()
                if not rest or rest[0] in ':,]}\n':
                    result.append(ch)
                    in_string = False
                else:
                    result.append('\\"')
            elif ch in '\u201c\u201d':
                result.append('\\"')
            elif ch in '\u2018\u2019':
                result.append("'")
            else:
                result.append(ch)
        i += 1

    text = ''.join(result)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)
    return text


# ── 日付でトピックを分類 ──────────────────────────────────
def split_topics_by_recency(topics: list[dict], ref_date: str) -> tuple[list, list]:
    """トピックを primary(当日・前日) と secondary(直近1週間) に分類。
    各エントリに元のインデックスを付与する。"""
    try:
        ref = datetime.strptime(ref_date, "%Y-%m-%d")
    except ValueError:
        ref = datetime.now()

    yesterday = (ref - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (ref - timedelta(days=7)).strftime("%Y-%m-%d")

    primary = []    # 当日・前日
    secondary = []  # 直近1週間（当日・前日を除く）

    for i, t in enumerate(topics):
        d = t.get("date", "")
        t_with_idx = {**t, "_idx": i}
        if d >= ref_date or d == yesterday:
            primary.append(t_with_idx)
        elif d >= week_ago:
            secondary.append(t_with_idx)

    # 日付が空のものは primary に入れる（当日収集のものが多い）
    for i, t in enumerate(topics):
        if not t.get("date", ""):
            t_with_idx = {**t, "_idx": i}
            if t_with_idx not in primary:
                primary.append(t_with_idx)

    return primary, secondary


# ── Gemini API 呼び出し共通関数 ───────────────────────────
def _call_gemini_json(client, prompt: str, max_tokens: int = 16000, retries: int = 3) -> dict | list | None:
    """Gemini API を呼んで JSON をパースして返す（レートリミット対応）"""
    from google.genai.errors import ClientError

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
        except ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 60 * (attempt + 1)
                print(f"    ⚠ レートリミット。{wait}秒待機後リトライ ({attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            raise

        text = _fix_json(response.text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON解析エラー: {e}")
            # 個別オブジェクト救出
            results = []
            for m in re.finditer(r'\{[^{}]+\}', text):
                try:
                    obj = json.loads(m.group())
                    results.append(obj)
                except json.JSONDecodeError:
                    continue
            return results if results else None

    return None


def _build_topic_list_text(topic_group: list[dict], limit: int = 100) -> str:
    """トピックリストをLLMに渡すテキストに変換"""
    lines = []
    for t in topic_group[:limit]:
        idx = t["_idx"] + 1  # 1-based
        date_tag = f" ({t['date']})" if t.get("date") else ""
        lines.append(f"{idx}. [{t['source']}]{date_tag} {t['title']}")
    return "\n".join(lines)


# ── Gemini: 注目記事 + トレンド分析を生成 ─────────────────
THEME_CATEGORIES = [
    ("1on1_dialogue", "1on1・対話関連", "最新事例・研究・実践tips"),
    ("management_issues", "マネジメント課題", "管理職の悩み・負担・スキル不足"),
    ("hr_topics", "人事担当者の注目トピック", "制度・法改正・HRトレンド"),
    ("case_studies", "企業事例", "1on1・対話・組織開発の導入事例"),
    ("other", "その他人事界隈の注目トピック", ""),
]



# ── キーワードベースのテーマ分類（API不要）──────────────
_THEME_KEYWORDS = {
    "1on1_dialogue": [
        "1on1", "ワンオンワン", "1対1", "対話", "面談", "傾聴", "コーチング",
        "フィードバック", "メンタリング", "コミュニケーション",
    ],
    "management_issues": [
        "マネジメント", "管理職", "マネジャー", "マネージャー", "上司", "部下",
        "リーダーシップ", "リーダー", "プレイングマネジャー", "負担", "悩み",
        "ピープルマネジメント", "中間管理職",
    ],
    "hr_topics": [
        "人事", "HR", "制度", "法改正", "評価", "報酬", "賃金", "給与",
        "エンゲージメント", "人的資本", "サーベイ", "ウェルビーイング",
        "ダイバーシティ", "D&I", "DE&I", "働き方", "テレワーク",
        "HRテック", "タレントマネジメント", "CHRO", "採用", "離職",
        "リスキリング", "人材育成", "研修", "オンボーディング", "OKR", "MBO",
        "キャリア", "異動", "配置",
    ],
    "case_studies": [
        "導入", "事例", "取り組み", "施策", "プロジェクト", "改革", "刷新",
        "トヨタ", "ソニー", "楽天", "メルカリ", "サイバーエージェント",
        "パナソニック", "日立", "NTT", "リクルート", "三菱", "スズキ", "IHI",
    ],
}

def _classify_topic(title: str, summary: str) -> str:
    """タイトルと要約からテーマを判定。最もマッチしたカテゴリを返す。"""
    text = (title + " " + summary).lower()

    scores = {}
    for cat, keywords in _THEME_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        # 1on1 は特にブースト
        if cat == "1on1_dialogue" and score > 0:
            score += 1
        # case_studies は「企業名 + 導入/事例」の組み合わせでブースト
        if cat == "case_studies" and score >= 2:
            score += 1
        scores[cat] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "other"
    return best


def _select_highlights(topics: list[dict], ref_date: str, target_per_theme: int = 20) -> list[dict]:
    """キーワードベースで全トピックをテーマ分類し、上位を選定。APIを使わない。"""
    try:
        ref = datetime.strptime(ref_date, "%Y-%m-%d")
    except ValueError:
        ref = datetime.now()

    yesterday = (ref - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (ref - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (ref - timedelta(days=30)).strftime("%Y-%m-%d")

    # 全トピックにカテゴリとスコアを付与
    scored = []
    for i, t in enumerate(topics):
        cat = _classify_topic(t["title"], t.get("summary", ""))
        d = t.get("date", "")

        # 日付による優先度スコア
        if d >= ref_date or d == yesterday:
            date_score = 3
            group = "primary"
        elif d >= week_ago:
            date_score = 2
            group = "secondary"
        elif d >= month_ago:
            date_score = 1
            group = "secondary"
        else:
            date_score = 0
            group = "secondary"

        scored.append({
            "index": i + 1,
            "category": cat,
            "summary": t.get("summary", "")[:120] or t["title"],
            "reason": "",  # 後でGeminiで付与
            "_group": group,
            "_date": d,
            "_date_score": date_score,
            "_title": t["title"],
        })

    # テーマ別に日付スコア降順→日付降順でソートし、上位を選定
    from collections import defaultdict
    by_theme = defaultdict(list)
    for s in scored:
        by_theme[s["category"]].append(s)

    selected = []
    for cat_key, _, _ in THEME_CATEGORIES:
        items = by_theme.get(cat_key, [])
        items.sort(key=lambda x: (x["_date_score"], x["_date"]), reverse=True)
        selected.extend(items[:target_per_theme])

    # other に未選択の高スコアを追加
    selected_indices = {s["index"] for s in selected}
    others = [s for s in by_theme.get("other", []) if s["index"] not in selected_indices]
    others.sort(key=lambda x: (x["_date_score"], x["_date"]), reverse=True)
    selected.extend(others[:target_per_theme])

    return selected


# ── Gemini: トレンド分析 + 注目記事の注目理由を付与 ───────
_TRENDS_PROMPT = """以下はHR・マネジメント関連トピック一覧です。
全体を俯瞰し、以下の3軸で動向をまとめてください。

- 1on1・マネジメント領域の動向
- 人事制度・採用・育成領域の動向
- HRテック・AI活用の動向

各軸3〜5文で簡潔に。具体的な記事名・企業名を引用すること。
カギカッコ（「」）を使い、文字列中にダブルクォートを含めないでください。

```json
{{
  "management": "...",
  "hr_system": "...",
  "hr_tech": "..."
}}
```

## トピック一覧
{topics_text}
"""


def generate_highlights_and_trends(
    topics: list[dict], ref_date: str
) -> dict:
    # ── Step 1: キーワードベースで100本以上を選定（API不要）──
    print("  キーワードベースで記事を分類・選定中...")
    highlights = _select_highlights(topics, ref_date, target_per_theme=20)

    from collections import Counter
    cat_counts = Counter(h["category"] for h in highlights)
    print(f"  注目記事: {len(highlights)}件（キーワード分類）")
    for cat_key, cat_label, _ in THEME_CATEGORIES:
        print(f"    {cat_label}: {cat_counts.get(cat_key, 0)}件")

    primary_count = sum(1 for h in highlights if h["_group"] == "primary")
    secondary_count = sum(1 for h in highlights if h["_group"] == "secondary")
    print(f"    → 当日・前日: {primary_count}件 / 直近1週間+: {secondary_count}件")

    # ── Step 2: Gemini でトレンド分析のみ（API 1回だけ）──
    trends = {"management": "", "hr_system": "", "hr_tech": ""}
    try:
        client = genai.Client(api_key=API_KEY)
        topics_text = _build_topic_list_text(
            [{"_idx": h["index"]-1, **topics[h["index"]-1]} for h in highlights[:80] if h["index"]-1 < len(topics)],
            limit=80,
        )
        print("  Gemini API: トレンド分析を生成中（1回のみ）...")
        raw = _call_gemini_json(
            client,
            _TRENDS_PROMPT.format(topics_text=topics_text),
            max_tokens=16000,
        )
        if isinstance(raw, dict):
            trends = raw
        elif isinstance(raw, list) and raw:
            trends = raw[0] if isinstance(raw[0], dict) else {}
    except Exception as e:
        print(f"  ⚠ トレンド分析失敗（ダッシュボードは生成続行）: {e}")

    for k in ("management", "hr_system", "hr_tech"):
        trends.setdefault(k, "")

    return {"highlights": highlights, "trends": trends}


# ── HTML生成 ──────────────────────────────────────────────
def generate_html(
    date: str,
    topics: list[dict],
    highlights_data: dict,
    plans: list[dict],
) -> str:
    highlights = highlights_data.get("highlights", [])
    trends = highlights_data.get("trends", {})

    # テーマカラーマッピング
    theme_colors = {
        "1on1_dialogue":     ("#3B82F6", "#EFF6FF"),   # blue
        "management_issues": ("#F59E0B", "#FFFBEB"),   # amber
        "hr_topics":         ("#10B981", "#ECFDF5"),   # green
        "case_studies":      ("#8B5CF6", "#F5F3FF"),   # purple
        "other":             ("#64748B", "#F1F5F9"),   # gray
    }

    def _highlight_card(h, topics_list):
        idx = h.get("index", 0) - 1
        if not (0 <= idx < len(topics_list)):
            return ""
        t = topics_list[idx]
        title_e = escape(t["title"])
        url_e = escape(t["url"])
        source_e = escape(t["source"])
        tdate_e = escape(t.get("date", ""))
        summary_e = escape(h.get("summary", ""))
        reason_e = escape(h.get("reason", ""))
        group = h.get("_group", "primary")
        date_badge_color = "var(--blue)" if group == "primary" else "var(--text-sub)"
        date_badge_bg = "var(--blue-bg)" if group == "primary" else "#F1F5F9"
        return f"""
            <div class="card highlight-card">
              <div class="card-header">
                <a href="{url_e}" target="_blank" rel="noopener">{title_e}</a>
                <span class="meta">
                  <span class="date-badge" style="background:{date_badge_bg};color:{date_badge_color}">{tdate_e}</span>
                  {source_e}
                </span>
              </div>
              <p class="summary">{summary_e}</p>
              {f'<p class="reason"><span class="reason-badge">注目理由</span> {reason_e}</p>' if reason_e else ''}
            </div>"""

    # テーマ別にグルーピングし、各テーマ内は日付降順ソート
    def _get_h_date(h):
        idx = h.get("index", 0) - 1
        if 0 <= idx < len(topics):
            return topics[idx].get("date", "0000-00-00")
        return "0000-00-00"

    highlights_html = ""
    h_total = 0
    theme_counts = {}

    for cat_key, cat_label, cat_desc in THEME_CATEGORIES:
        items = [h for h in highlights if h.get("category") == cat_key]
        items.sort(key=_get_h_date, reverse=True)
        theme_counts[cat_key] = len(items)
        h_total += len(items)

        if not items:
            continue

        color, bg = theme_colors.get(cat_key, ("#64748B", "#F1F5F9"))
        desc_html = f'<span style="color:var(--text-sub);font-size:13px;margin-left:8px;">{cat_desc}</span>' if cat_desc else ""
        highlights_html += f"""
        <div class="theme-section" style="border-left:4px solid {color}; padding-left:16px; margin-bottom:28px;">
          <h3 class="highlight-group-title" style="color:{color}">
            {cat_label}（{len(items)}本）{desc_html}
          </h3>"""
        for h in items:
            highlights_html += _highlight_card(h, topics)
        highlights_html += "</div>"

    # category未分類のものは other に入れる
    uncategorized = [h for h in highlights if h.get("category") not in dict([(c[0], True) for c in THEME_CATEGORIES])]
    if uncategorized:
        uncategorized.sort(key=_get_h_date, reverse=True)
        color, bg = theme_colors["other"]
        highlights_html += f"""
        <div class="theme-section" style="border-left:4px solid {color}; padding-left:16px; margin-bottom:28px;">
          <h3 class="highlight-group-title" style="color:{color}">
            未分類（{len(uncategorized)}本）
          </h3>"""
        for h in uncategorized:
            highlights_html += _highlight_card(h, topics)
        highlights_html += "</div>"
        h_total += len(uncategorized)

    h_primary_count = sum(1 for h in highlights if h.get("_group") == "primary")
    h_secondary_count = sum(1 for h in highlights if h.get("_group") == "secondary")

    # トレンド分析HTML
    trend_mgmt = escape(trends.get("management", "（データなし）"))
    trend_hr = escape(trends.get("hr_system", "（データなし）"))
    trend_tech = escape(trends.get("hr_tech", "（データなし）"))

    # 企画案HTML
    branding = [p for p in plans if p.get("type") == "branding"]
    lead = [p for p in plans if p.get("type") == "lead"]

    def plan_card(p: dict, label: str, color: str) -> str:
        title = escape(p.get("title", ""))
        reader = escape(p.get("target_reader", ""))
        angle = escape(p.get("angle", ""))
        sources = escape(" / ".join(p.get("source_topics", [])))
        resource = escape(p.get("connected_resource", ""))
        why = escape(p.get("why_now", ""))
        return f"""
            <div class="card plan-card" style="border-left: 4px solid {color}">
              <div class="plan-header">
                <span class="plan-badge" style="background:{color}">{label}</span>
                <h3>{title}</h3>
              </div>
              <table class="plan-table">
                <tr><th>想定読者</th><td>{reader}</td></tr>
                <tr><th>切り口</th><td>{angle}</td></tr>
                <tr><th>使用するネタ</th><td>{sources}</td></tr>
                <tr><th>接続する資料</th><td><span class="resource-tag">{resource}</span></td></tr>
                <tr><th>Why Now</th><td>{why}</td></tr>
              </table>
            </div>"""

    plans_html = ""
    for p in branding:
        plans_html += plan_card(p, "Branding", "#3B82F6")
    for p in lead:
        plans_html += plan_card(p, "Lead", "#F59E0B")

    total = len(plans)
    b_count = len(branding)
    l_count = len(lead)
    t_count = len(topics)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Daily Dashboard — {date}</title>
  <style>
    :root {{
      --bg: #F8FAFC;
      --surface: #FFFFFF;
      --border: #E2E8F0;
      --text: #1E293B;
      --text-sub: #64748B;
      --blue: #3B82F6;
      --blue-bg: #EFF6FF;
      --amber: #F59E0B;
      --amber-bg: #FFFBEB;
      --green: #10B981;
      --green-bg: #ECFDF5;
      --purple: #8B5CF6;
      --purple-bg: #F5F3FF;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Noto Sans JP', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 24px 20px; }}

    /* ── Header ── */
    header {{
      background: linear-gradient(135deg, #1E3A5F 0%, #2563EB 100%);
      color: white;
      padding: 32px 0;
      margin-bottom: 32px;
    }}
    header .container {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }}
    header h1 {{ font-size: 24px; font-weight: 700; }}
    header .date {{ font-size: 14px; opacity: 0.85; }}
    .stats {{ display: flex; gap: 16px; }}
    .stat-box {{
      background: rgba(255,255,255,0.15);
      border-radius: 8px;
      padding: 8px 16px;
      text-align: center;
      font-size: 13px;
    }}
    .stat-box .num {{ font-size: 22px; font-weight: 700; display: block; }}

    /* ── Section ── */
    .section {{ margin-bottom: 40px; }}
    .section-title {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 16px;
      padding-bottom: 8px;
      border-bottom: 2px solid var(--border);
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .section-num {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px; height: 28px;
      border-radius: 50%;
      font-size: 14px;
      font-weight: 700;
      color: white;
    }}

    /* ── Card ── */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
      margin-bottom: 12px;
      transition: box-shadow 0.15s;
    }}
    .card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}

    /* ── Highlights ── */
    .highlight-card .card-header a {{
      font-size: 15px;
      font-weight: 600;
      color: var(--blue);
      text-decoration: none;
    }}
    .highlight-card .card-header a:hover {{ text-decoration: underline; }}
    .highlight-card .meta {{
      display: block;
      font-size: 12px;
      color: var(--text-sub);
      margin-top: 4px;
    }}
    .highlight-card .summary {{
      font-size: 14px;
      color: var(--text);
      margin: 10px 0 8px;
    }}
    .highlight-card .reason {{
      font-size: 13px;
      color: var(--text-sub);
    }}
    .reason-badge {{
      display: inline-block;
      background: var(--green-bg);
      color: var(--green);
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 4px;
      margin-right: 4px;
    }}
    .date-badge {{
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 4px;
      margin-right: 6px;
    }}
    .highlight-group-title {{
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 12px;
      margin-top: 0;
      padding-left: 0;
    }}
    .theme-section {{
      margin-bottom: 28px;
    }}

    /* ── Trends ── */
    .trend-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
    .trend-box {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }}
    .trend-box h3 {{
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .trend-box h3 .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    .trend-box p {{ font-size: 14px; color: var(--text); }}

    /* ── Plans ── */
    .plan-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 14px; }}
    .plan-card {{ padding: 16px 20px; }}
    .plan-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }}
    .plan-header h3 {{ font-size: 15px; font-weight: 600; }}
    .plan-badge {{
      font-size: 11px;
      font-weight: 700;
      color: white;
      padding: 3px 10px;
      border-radius: 4px;
      white-space: nowrap;
    }}
    .plan-table {{ width: 100%; font-size: 13px; border-collapse: collapse; }}
    .plan-table th {{
      text-align: left;
      width: 110px;
      padding: 5px 8px;
      color: var(--text-sub);
      font-weight: 600;
      vertical-align: top;
      border-bottom: 1px solid var(--border);
    }}
    .plan-table td {{
      padding: 5px 8px;
      border-bottom: 1px solid var(--border);
    }}
    .resource-tag {{
      display: inline-block;
      background: var(--purple-bg);
      color: var(--purple);
      font-size: 12px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 4px;
    }}

    /* ── Footer ── */
    footer {{
      text-align: center;
      font-size: 12px;
      color: var(--text-sub);
      padding: 24px 0;
      border-top: 1px solid var(--border);
    }}

    @media (max-width: 600px) {{
      .plan-grid {{ grid-template-columns: 1fr; }}
      .trend-grid {{ grid-template-columns: 1fr; }}
      .stats {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>

<header>
  <div class="container">
    <div>
      <h1>HR Daily Dashboard</h1>
      <p class="date">{date}（1on1総研 企画会議用）</p>
    </div>
    <div class="stats">
      <div class="stat-box"><span class="num">{t_count}</span>収集記事</div>
      <div class="stat-box"><span class="num">{h_total}</span>注目記事</div>
      <div class="stat-box"><span class="num">{total}</span>企画案</div>
      <div class="stat-box"><span class="num">{b_count} / {l_count}</span>Brand / Lead</div>
    </div>
  </div>
</header>

<div class="container">

  <!-- Section 1: 注目記事 -->
  <div class="section">
    <h2 class="section-title">
      <span class="section-num" style="background:var(--blue)">1</span>
      本日の注目記事（{h_total}本: 当日・前日 {h_primary_count} + 直近1週間 {h_secondary_count}）
    </h2>
    {highlights_html if highlights_html else '<p style="color:var(--text-sub)">注目記事の抽出に失敗しました。</p>'}
  </div>

  <!-- Section 2: トレンド分析 -->
  <div class="section">
    <h2 class="section-title">
      <span class="section-num" style="background:var(--green)">2</span>
      HR界隈トレンド分析
    </h2>
    <div class="trend-grid">
      <div class="trend-box">
        <h3><span class="dot" style="background:var(--blue)"></span>1on1・マネジメント領域</h3>
        <p>{trend_mgmt}</p>
      </div>
      <div class="trend-box">
        <h3><span class="dot" style="background:var(--green)"></span>人事制度・採用・育成</h3>
        <p>{trend_hr}</p>
      </div>
      <div class="trend-box">
        <h3><span class="dot" style="background:var(--purple)"></span>HRテック・AI活用</h3>
        <p>{trend_tech}</p>
      </div>
    </div>
  </div>

  <!-- Section 3: 企画案 -->
  <div class="section">
    <h2 class="section-title">
      <span class="section-num" style="background:var(--amber)">3</span>
      1on1総研 コンテンツ企画案（{total}本）
    </h2>
    <p style="font-size:13px; color:var(--text-sub); margin-bottom:14px;">
      <span class="plan-badge" style="background:var(--blue)">Branding</span> 第一想起獲得・専門性訴求（{b_count}本）
      <span style="margin: 0 8px;">|</span>
      <span class="plan-badge" style="background:var(--amber)">Lead</span> 資料DL誘導（{l_count}本）
    </p>
    <div class="plan-grid">
      {plans_html}
    </div>
  </div>

</div>

<footer>
  Generated by hr_collector pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}
</footer>

</body>
</html>"""


# ── メイン ────────────────────────────────────────────────
def main():
    date = sys.argv[1] if len(sys.argv) > 1 else TODAY

    print("=" * 60)
    print(f"HR Daily Dashboard 生成")
    print(f"日付: {date}")
    print("=" * 60)

    # 1. トピックファイル読み込み
    topics_path = find_file(TOPICS_DIR, "{date}_hr_topics.md", date)
    if not topics_path:
        print("⚠ トピックファイルが見つかりません。collect_hr_topics.py を先に実行してください。")
        sys.exit(1)
    print(f"\n📄 トピック: {topics_path.name}")
    topics = parse_topics_md(topics_path)
    print(f"   {len(topics)}件をパース")

    # 2. 企画案読み込み
    plans_path = find_file(PLANS_DIR, "{date}_content_plans.json", date)
    plans = []
    if plans_path:
        print(f"📄 企画案: {plans_path.name}")
        plans = json.loads(plans_path.read_text(encoding="utf-8"))
        print(f"   {len(plans)}本")
    else:
        print("⚠ 企画案ファイルなし。企画セクションは空になります。")

    # 3. Gemini で注目記事 + トレンドを生成
    print(f"\n🤖 注目記事・トレンド分析を生成中...")
    highlights_data = generate_highlights_and_trends(topics, date)
    h_count = len(highlights_data.get("highlights", []))
    print(f"   注目記事: {h_count}件")

    # 4. HTML生成
    print(f"\n📊 ダッシュボードHTML生成中...")
    html = generate_html(date, topics, highlights_data, plans)
    output_path = DASH_DIR / f"{date}_dashboard.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"   保存: {output_path}")

    # 5. ブラウザで開く（CI環境ではスキップ）
    if not os.environ.get("CI"):
        print(f"\n🌐 ブラウザで開いています...")
        os.system(f"open '{output_path}'")

    print(f"\n{'=' * 60}")
    print(f"✓ 完了: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
