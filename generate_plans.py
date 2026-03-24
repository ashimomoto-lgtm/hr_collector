#!/usr/bin/env python3
"""
HR トピックから1on1総研向けコンテンツ企画案を自動生成するスクリプト

使い方:
  export GEMINI_API_KEY="your-api-key"
  pip3 install google-genai
  python3 generate_plans.py                    # 当日の hr_topics を使用
  python3 generate_plans.py 2026-03-17         # 日付を指定
  python3 generate_plans.py path/to/file.md    # ファイルを直接指定
"""

import os
import sys
import re
import json
import time
from datetime import datetime
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("google-genai がインストールされていません。")
    print("  pip3 install google-genai")
    sys.exit(1)

# ── 設定 ─────────────────────────────────────────────────
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("環境変数 GEMINI_API_KEY が設定されていません。")
    sys.exit(1)

MODEL = "gemini-2.5-flash"
TOPICS_DIR = Path(__file__).parent / "output"
PLANS_DIR = Path(__file__).parent / "plans"
PLANS_DIR.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")

# ── KAKEAIの資料ラインナップ（接続先）─────────────────────
KAKEAI_RESOURCES = """
## KAKEAIが保有するダウンロード資料

1. **メンバーのための1on1完全ガイド** — メンバー側が1on1を使いこなすためのノウハウ
2. **マネジャーのための1on1完全ガイド** — マネジャーが1on1を設計・実践するためのノウハウ
3. **マネジャー向け1on1質問集** — 場面別の具体的な問いかけ例
4. **0から始める！1on1導入ガイドライン** — HRが組織全体で1on1を導入・推進するためのステップ
5. **上司・部下の信頼関係16段階シート** — 信頼関係の現在地を把握し、段階に応じた対話を設計する
6. **1on1総研 調査レポート（各種）** — 1on1やマネジメントに関する独自調査データ
7. **KAKEAIサービス資料** — 1on1支援ツールKAKEAIの機能・導入事例
"""

# ── システムプロンプト ────────────────────────────────────
SYSTEM_PROMPT = """あなたは「1on1総研」のコンテンツストラテジストです。

## 1on1総研について
- 株式会社KAKEAIが運営するオウンドメディア
- テーマ: 1on1、マネジメント、上司部下関係、組織開発、人事制度
- 読者: 人事担当者（HRBP含む）、マネジャー・管理職、経営層
- 目的: KAKEAIの「1on1・マネジメント領域の第一想起」を獲得し、リード（資料DL）を創出する

## あなたの役割
渡されるHRトピック一覧（当日のニュース・記事）を分析し、1on1総研で発信すべきコンテンツ企画案を生成してください。

## 企画の2分類

### A. ブランディングコンテンツ（第一想起獲得・専門性訴求）
- 目的: 「1on1・マネジメントといえばKAKEAI」のポジションを築く
- 特徴: 独自の視点や深い分析、データに基づく考察
- 例: 調査レポート解説、トレンド分析、専門家コラム、概念整理
- KPIs: PV、SNSシェア、指名検索

### B. リード化コンテンツ（資料ダウンロードにつなげる）
- 目的: 読者の課題を顕在化させ、資料DLへ誘導する
- 特徴: 読者が「今すぐ使えるもの」を求める文脈をつくる
- 例: ハウツー、チェックリスト、事例紹介、課題診断
- KPIs: 資料DL数、CTA クリック率

## 出力フォーマット（厳守）

以下のJSON配列として出力してください。他の文章は一切不要です。

重要なルール:
- source_topics には元記事のタイトルをそのまま入れず、自分の言葉で短く要約して入れてください（例: "新入社員の定着率に関する調査報道"）。記事タイトルの引用符やカッコが JSON を壊すためです。
- JSON文字列値の中にダブルクォートを含めないでください。カギカッコ（「」）を使ってください。
- 全角記号（""''）は使わないでください。

```json
[
  {
    "type": "branding または lead",
    "title": "記事タイトル案",
    "target_reader": "想定読者（具体的に）",
    "angle": "切り口・論点（2-3文で）",
    "source_topics": ["元ネタの要約（自分の言葉で短く）"],
    "connected_resource": "接続するKAKEAI資料名",
    "why_now": "なぜ今このテーマか（1文）"
  }
]
```

## 生成ルール
- 合計12本以上（ブランディング5本以上、リード化5本以上）
- トピック一覧の中から旬のネタを拾い、1on1・マネジメント文脈に接続する
- 直接1on1の話題でなくても、マネジメントに引きつけられるなら企画化する
  （例: 「若手の離職増加」→「離職を防ぐ1on1の設計」）
- タイトルは具体的かつクリック誘引力のあるものにする
- 各企画にはKAKEAI資料のいずれかを必ず接続する
- 同じ資料ばかりに偏らないようバランスを取る
"""


def find_topics_file(arg: str = None) -> Path:
    """トピックファイルを特定する"""
    if arg:
        # 直接ファイルパス指定
        p = Path(arg)
        if p.exists():
            return p
        # 日付指定
        p = TOPICS_DIR / f"{arg}_hr_topics.md"
        if p.exists():
            return p
        print(f"ファイルが見つかりません: {arg}")
        sys.exit(1)

    # デフォルト: 当日 → 最新
    today_file = TOPICS_DIR / f"{TODAY}_hr_topics.md"
    if today_file.exists():
        return today_file

    # 最新のファイルを探す
    files = sorted(TOPICS_DIR.glob("*_hr_topics.md"), reverse=True)
    if files:
        print(f"当日のファイルがないため最新を使用: {files[0].name}")
        return files[0]

    print(f"トピックファイルが見つかりません。先に collect_hr_topics.py を実行してください。")
    sys.exit(1)


def extract_topics_summary(md_content: str, max_chars: int = 30000) -> str:
    """Markdownからトピック一覧を抽出（トークン節約のため要約）"""
    lines = md_content.split("\n")
    output = []
    current_section = ""

    for line in lines:
        # セクション見出し
        if line.startswith("## ") and not line.startswith("## 収集サマリー"):
            current_section = line
            output.append(line)
        # 記事タイトル
        elif line.startswith("### "):
            output.append(line)
        # ソース情報
        elif line.startswith("**") and current_section:
            output.append(line)
        # 要約（> で始まる行）
        elif line.startswith("> ") and current_section:
            output.append(line)

    result = "\n".join(output)

    # トークン上限を超えそうなら末尾をカット
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n（以下省略）"

    return result


def generate_plans(topics_summary: str, resources: str) -> list[dict]:
    """Gemini APIで企画案を生成"""
    client = genai.Client(api_key=API_KEY)

    user_prompt = f"""以下は本日収集したHR・マネジメント関連トピック一覧です。
これを元に、1on1総研のコンテンツ企画案をJSON配列で生成してください。

{resources}

---

## 本日のトピック一覧

{topics_summary}
"""

    max_retries = 3
    response = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Gemini API に送信中... (試行 {attempt}/{max_retries})")
            response = client.models.generate_content(
                model=MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=8000,
                    response_mime_type="application/json",
                ),
            )
            break
        except Exception as e:
            print(f"  ⚠ API呼び出しエラー (試行 {attempt}): {e}")
            if attempt < max_retries:
                wait = 10 * attempt
                print(f"  {wait}秒後にリトライします...")
                time.sleep(wait)
            else:
                print("  ⚠ 全リトライ失敗。")
                return []

    if not response or not response.text:
        print("  ⚠ APIから空のレスポンスが返されました。")
        return []

    text = response.text

    # 保険: ```json``` ブロックが付いていたら剥がす
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # JSON文字列値の中にある全角引用符をエスケープ付き半角に置換すると壊れるので、
    # 代わにJSON構造を壊さないよう文字列値の内部だけを修復する
    def _fix_json_string_values(raw: str) -> str:
        """JSON文字列値の中にある非エスケープのダブルクォートを修復"""
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
                    # エスケープシーケンス: そのまま通す
                    result.append(ch)
                    if i + 1 < len(raw):
                        i += 1
                        result.append(raw[i])
                elif ch == '"':
                    # 文字列の終了かどうかを判定
                    # 次の非空白文字が : , ] } のいずれかなら文字列終了
                    rest = raw[i+1:].lstrip()
                    if not rest or rest[0] in ':,]}\n':
                        result.append(ch)
                        in_string = False
                    else:
                        # 文字列内のクォート → エスケープ
                        result.append('\\"')
                else:
                    # \u201c \u201d (全角ダブルクォート) を通常文字に
                    if ch in '\u201c\u201d':
                        result.append('\\"')
                    else:
                        result.append(ch)
            i += 1
        return ''.join(result)

    text = _fix_json_string_values(text)

    # 制御文字を除去
    text = re.sub(r'[\x00-\x1f]', lambda m: m.group() if m.group() in '\n\r\t' else ' ', text)

    try:
        plans = json.loads(text)
        return plans
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON解析エラー: {e}")

        # フォールバック: 生レスポンスを保存
        fallback_path = PLANS_DIR / f"{TODAY}_raw_response.txt"
        fallback_path.write_text(response.text, encoding="utf-8")
        print(f"  生のレスポンスを保存: {fallback_path}")

        # 最終手段: 各オブジェクトを個別にパース
        print(f"  個別オブジェクト抽出を試みます...")
        plans = []
        for m in re.finditer(r'\{[^{}]*\}', response.text, re.DOTALL):
            try:
                obj_text = m.group()
                obj_text = obj_text.replace('\u201c', '"').replace('\u201d', '"')
                obj = json.loads(obj_text)
                if "title" in obj:
                    plans.append(obj)
            except json.JSONDecodeError:
                continue
        if plans:
            print(f"  ✓ {len(plans)}件を救出")
        else:
            print(f"  ⚠ 救出失敗")
        return plans


def format_plans_markdown(plans: list[dict], topics_file: str) -> str:
    """企画案をMarkdownに整形"""
    branding = [p for p in plans if p.get("type") == "branding"]
    lead = [p for p in plans if p.get("type") == "lead"]

    lines = []
    lines.append(f"# 1on1総研 コンテンツ企画案 ({TODAY})")
    lines.append("")
    lines.append(f"> 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> ソース: `{topics_file}`")
    lines.append(f"> 企画総数: **{len(plans)}本**（ブランディング {len(branding)}本 / リード化 {len(lead)}本）")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── ブランディング ──
    lines.append("## A. ブランディングコンテンツ（第一想起獲得・専門性訴求）")
    lines.append("")
    if not branding:
        lines.append("（該当なし）")
    for i, p in enumerate(branding, 1):
        lines.append(f"### A-{i}. {p.get('title', '（タイトルなし）')}")
        lines.append("")
        lines.append(f"| 項目 | 内容 |")
        lines.append(f"|------|------|")
        lines.append(f"| **想定読者** | {p.get('target_reader', '-')} |")
        lines.append(f"| **切り口** | {p.get('angle', '-')} |")
        lines.append(f"| **使用するネタ** | {_format_sources(p.get('source_topics', []))} |")
        lines.append(f"| **接続する資料** | {p.get('connected_resource', '-')} |")
        lines.append(f"| **Why Now** | {p.get('why_now', '-')} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── リード化 ──
    lines.append("## B. リード化コンテンツ（資料DLにつなげる）")
    lines.append("")
    if not lead:
        lines.append("（該当なし）")
    for i, p in enumerate(lead, 1):
        lines.append(f"### B-{i}. {p.get('title', '（タイトルなし）')}")
        lines.append("")
        lines.append(f"| 項目 | 内容 |")
        lines.append(f"|------|------|")
        lines.append(f"| **想定読者** | {p.get('target_reader', '-')} |")
        lines.append(f"| **切り口** | {p.get('angle', '-')} |")
        lines.append(f"| **使用するネタ** | {_format_sources(p.get('source_topics', []))} |")
        lines.append(f"| **接続する資料** | {p.get('connected_resource', '-')} |")
        lines.append(f"| **Why Now** | {p.get('why_now', '-')} |")
        lines.append("")

    # ── 資料接続の分布 ──
    lines.append("---")
    lines.append("")
    lines.append("## 資料接続の分布")
    lines.append("")
    resource_count = {}
    for p in plans:
        r = p.get("connected_resource", "不明")
        resource_count[r] = resource_count.get(r, 0) + 1
    lines.append("| 資料名 | 接続数 |")
    lines.append("|-------|-------|")
    for r, c in sorted(resource_count.items(), key=lambda x: -x[1]):
        lines.append(f"| {r} | {c} |")
    lines.append("")

    return "\n".join(lines)


def _format_sources(sources: list) -> str:
    if not sources:
        return "-"
    if len(sources) == 1:
        return sources[0]
    return " / ".join(sources)


def main():
    print("=" * 60)
    print("1on1総研 コンテンツ企画案 自動生成")
    print(f"日付: {TODAY}")
    print("=" * 60)

    # 1. トピックファイルを読み込む
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    topics_file = find_topics_file(arg)
    print(f"\n📄 トピックファイル: {topics_file.name}")

    md_content = topics_file.read_text(encoding="utf-8")
    topics_summary = extract_topics_summary(md_content)
    topic_count = topics_summary.count("### ")
    print(f"   トピック数: {topic_count}件")

    if topic_count == 0:
        print("⚠ トピックが0件です。先に collect_hr_topics.py を実行してください。")
        sys.exit(1)

    # 2. Gemini APIで企画案を生成
    print(f"\n🤖 企画案を生成中 (モデル: {MODEL})...")
    plans = generate_plans(topics_summary, KAKEAI_RESOURCES)

    if not plans:
        print("⚠ 企画案の生成に失敗しました。")
        sys.exit(1)

    print(f"   生成数: {len(plans)}本")

    # 3. Markdown出力
    output_path = PLANS_DIR / f"{TODAY}_content_plans.md"
    md_output = format_plans_markdown(plans, topics_file.name)
    output_path.write_text(md_output, encoding="utf-8")

    # 4. JSON（生データ）も保存
    json_path = PLANS_DIR / f"{TODAY}_content_plans.json"
    json_path.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")

    branding = sum(1 for p in plans if p.get("type") == "branding")
    lead = sum(1 for p in plans if p.get("type") == "lead")

    print(f"\n{'=' * 60}")
    print(f"✓ 完了")
    print(f"  ブランディング: {branding}本")
    print(f"  リード化:       {lead}本")
    print(f"  合計:           {len(plans)}本")
    print(f"")
    print(f"  Markdown: {output_path}")
    print(f"  JSON:     {json_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
