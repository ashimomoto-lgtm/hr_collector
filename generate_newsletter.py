#!/usr/bin/env python3
"""
1on1総研メルマガ草稿を自動生成するスクリプト。

ワークフロー:
  1. kakeai.co.jp/media/ から記事一覧をスクレイピング
  2. 今週のダッシュボードデータ（企画案JSON）を読み込み
  3. Gemini APIで「今週らしいテーマ」を3案生成
  4. 各テーマに合う1on1総研記事を1〜3本選定
  5. 過去メルマガのフォーマット・トーンを完全再現した草稿を3案生成
  6. Google Driveに保存

使い方:
  python generate_newsletter.py                # 最新の週次データを使用
  python generate_newsletter.py 2026-03-21     # 日付指定
"""

import os
import sys
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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
DIR = Path(__file__).resolve().parent
PLANS_DIR = DIR / "plans"
OUTPUT_DIR = DIR / "newsletter"
OUTPUT_DIR.mkdir(exist_ok=True)

# Google Drive 設定
DRIVE_FOLDER_ID = "1GTNI6pcdtjlcWh0-qNQMly-wWB8hhK0j"
TOKEN_FILE = DIR / "token.json"

MEDIA_BASE = "https://kakeai.co.jp"
MEDIA_URL = f"{MEDIA_BASE}/media/"
ARTICLE_LIST_URL = f"{MEDIA_BASE}/media/article"

# 過去メルマガのGoogleドキュメントID（フォーマット学習用）
PAST_NEWSLETTER_DOC_ID = "1sUFHWfxnbfXGc4TjNNCdJECLZEHclVqOWUSOS5BRFv4"


# ── 過去メルマガで紹介済みのURLを抽出 ──────────────────────
def extract_featured_urls(past_text):
    """過去メルマガ全文からkakeai.co.jp/media/article/のURLを抽出"""
    if not past_text:
        return set()
    # URLパターン: kakeai.co.jp/media/article/XXXX 部分を正規化して抽出
    raw_urls = re.findall(r"https?://(?:l\.)?kakeai\.co\.jp/media/(?:article/|human-capital/|1on1/)(\d+)", past_text)
    # 正規化: /media/article/XXXX 形式に統一
    normalized = set()
    for article_id in raw_urls:
        normalized.add(f"https://kakeai.co.jp/media/article/{article_id}")
        # 旧URL形式も追加
        normalized.add(f"https://kakeai.co.jp/media/article/0{article_id}" if len(article_id) < 4 else f"https://kakeai.co.jp/media/article/{article_id}")
    # フルURLパターンでも直接抽出
    full_urls = re.findall(r"https://kakeai\.co\.jp/media/article/\d+", past_text)
    normalized.update(full_urls)
    return normalized


# ── Step 1: 記事一覧を取得 ─────────────────────────────────
def fetch_articles():
    """kakeai.co.jp/media/ から記事一覧をスクレイピング"""
    print("  記事一覧を取得中...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) 1on1-newsletter-bot"
    }
    articles = []

    for url in [MEDIA_URL, ARTICLE_LIST_URL]:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # 記事カードを探す（複数パターン対応）
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if "/media/article/" not in href:
                    continue

                # タイトルを取得
                title_el = a_tag.find(class_=re.compile(r"ttl|title"))
                if not title_el:
                    title_el = a_tag.find(["h2", "h3", "p"])
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                full_url = href if href.startswith("http") else f"{MEDIA_BASE}{href}"

                # 重複除去
                if not any(a["url"] == full_url for a in articles):
                    articles.append({"title": title, "url": full_url})

            time.sleep(0.5)
        except Exception as e:
            print(f"  警告: {url} の取得に失敗: {e}")

    print(f"  → {len(articles)} 件の記事を取得")
    return articles


# ── Step 2: 今週のダッシュボードデータを読み込み ────────────
def load_weekly_plans(target_date):
    """直近の企画案JSONを読み込み"""
    # 指定日から過去7日分を探索
    for delta in range(7):
        d = target_date - timedelta(days=delta)
        json_path = PLANS_DIR / f"{d.strftime('%Y-%m-%d')}_content_plans.json"
        if json_path.exists():
            print(f"  企画案を読み込み: {json_path.name}")
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)

    print("  警告: 直近7日分の企画案が見つかりません")
    return []


# ── Step 3-5: Gemini APIでメルマガ草稿を生成 ───────────────
def generate_newsletter_drafts(articles, plans, past_newsletters_text, new_articles, all_articles):
    """Geminiでテーマ選定 → 記事マッチング → 草稿生成を一括実行"""
    print("  Gemini APIでメルマガ草稿を生成中...")

    client = genai.Client(api_key=API_KEY)

    # 新着記事テキスト（メルマガ未紹介）
    new_articles_text = "\n".join(
        f"- [NEW] 「{a['title']}」 {a['url']}" for a in new_articles
    )

    # 全記事一覧テキスト（関連記事選定用）
    all_articles_text = "\n".join(
        f"- 「{a['title']}」 {a['url']}" for a in all_articles
    )

    # 企画案テキスト
    plans_text = "\n".join(
        f"- [{p.get('type', '?')}] {p.get('title', '?')} — {p.get('angle', '')[:80]}..."
        for p in plans[:15]
    )

    today_str = date.today().strftime("%Y年%-m月%-d日")

    prompt = f"""あなたは「1on1総研」メルマガ編集チームのAIアシスタントです。
以下の情報を基に、**今週のメルマガ草稿を3案**生成してください。

## タスク

### Step 1: 新着記事の選定（最重要）
以下の「新着記事リスト」は、1on1総研に掲載済みだが**まだメルマガで紹介していない記事**です。
各案で、この新着記事リストから**1本をメイン記事**として選定してください。
- 3案それぞれで異なる新着記事を起点にすること（同じ新着記事を複数案で使わない）
- 新着記事が3本未満の場合は、一部の案で同じ新着記事を使ってもよいが、テーマの切り口は変えること

### Step 2: テーマ決定
選定した新着記事の内容を起点に、メルマガのテーマを決定してください。
- 新着記事が扱うテーマと、今週のHRトレンド（企画案データ参照）を接続する
- 読者（人事・マネジャー）にとって「今週読む理由」があるテーマにする
- 過去のメルマガと重複しないテーマにする

### Step 3: 関連記事の追加選定
メイン（新着）記事に合わせて、1on1総研の全記事一覧から**0〜2本の関連記事**を追加選定してください。
- 追加は任意。新着記事1本だけで十分テーマが成立する場合は追加不要
- 関連記事は新着でなくてもよい（過去にメルマガで紹介済みの記事でもOK）
- 合計で1〜3本になるようにする
- URLは記事一覧から正確に引用すること（絶対にURLを捏造しないこと）

### Step 3: 草稿生成
過去17回のメルマガを完全に学習してください。
特に**第10回〜第17回の文体・構成を最重要の参考モデル**とし、第15〜17回の質感に最も近づけてください。

## フォーマットルール

1. **タイトル**: キャッチーで、読者の好奇心を刺激する（——やemダッシュを効果的に使用）

2. **冒頭の挨拶**: 「こんにちは、「1on1総研」編集長の下元です。」+ 季節の挨拶（1〜2文）

3. **導入文（最重要パート — 以下を厳守）**:

   ■ 基本方針:
   第10回以降のメルマガでは、初期（第2〜9回）に多用していた「✅ or ❓ のチェックリスト3点」形式から脱却し、
   より自然な文章で読者の状況・感情・問題意識を描写してからテーマに入るスタイルに進化している。
   草稿生成時はこの進化後のスタイルを基本とすること。

   ■ 導入パターンの使い分け（3案で必ず異なるパターンを使うこと）:

   パターンA「状況描写型」（第10回、第13回を参考）:
   読者が置かれている具体的な場面を描写し、共感を起点にテーマへ接続する。
   例: 「業務が立て込み、スピードが求められるこの時期こそ増えるのが、部下の「ミス」です。」
   例: 「業務が立て込んでくると、つい部下に言ってしまいませんか。「ごめん、忙しいから今週の1on1はスキップしていい？」」

   パターンB「背景・経緯型」（第15回、第17回を参考）:
   直近の出来事や連載の経緯など「ストーリー」を語り、そこからテーマの必然性を立ち上げる。
   例: 「昨年9月から半年間にわたりお届けしてきた連載が、先日最終回を迎えました。」
   例: 「この記事に対し、人事インフルエンサーのこがねん氏がXで異議を唱えました。」

   パターンC「問題提起型」（第12回、第16回を参考）:
   大きな問い or 対比構造を提示し、知的好奇心を刺激してからテーマへ導く。
   例: 「経営からのオーダーを完璧にこなす人事か。それとも、時には経営に「NO」を突きつける人事か。」
   例: 「1本目では「なぜ日本企業から閉塞感が消えないのか」というマクロな組織論を、2本目では〜」

   パターンD「チェックリスト型」（第2〜4回のスタイル）:
   ✅ or ❓ を2〜3項目並べる形式。テーマが「複数の具体症状」を列挙すると効果的な場合にのみ使用。
   **3案のうち最大1案まで**。全案で使用するのは禁止。

   ■ 導入文の品質基準:
   - 読者が「自分のことだ」と感じる具体性があること
   - テーマの必然性（Why Now）が自然に伝わること
   - 「さて、今回のテーマは〜です」のような説明的な接続を避け、描写や問いかけからテーマに入ること
   - 長すぎないこと（5〜8文程度）

4. **区切り線**: ━━━━━━━━━ 📖 今週のおすすめ記事 ━━━━━━━━━━━━

5. **各記事紹介**（1〜3本）:
   - **1️⃣ 記事タイトル**（太字）
   - 記事の要約・紹介文（3〜5文、読者が読みたくなる書き方）
   - **📣編集長コメント**（2〜3文、下元の個人的視点・感想。「印象的だったのは〜」「ハッとさせられたのは〜」等の表現を自然に使う）
   - ▼詳細はこちら + URL

6. **区切り線**: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

7. **締めの言葉**: 今週の1on1に活かせる一言 + 体調への気遣い（第14〜17回の締め方を参考）

8. **フッター**: 👉「1on1総研」トップページへ https://kakeai.co.jp/media

## トーン・文体の特徴（第15〜17回を最重要参考モデルとする）

- 硬すぎず柔らかすぎない、知的で親しみやすい文体
- 読者を「皆さん」「皆様」「〜ではないでしょうか」と丁寧に呼びかけ
- 編集長コメントは個人の感想・気づきを率直に（「印象的だったのは」「ハッとさせられたのは」「記事の中にある〜という指摘」等）
- 記事紹介は「煽り」ではなく「価値の提示」——読者が「読む理由」を理解できる紹介文
- 季節感を自然に織り込む（今日は{today_str}。年度末→新年度の過渡期）
- 過去メルマガの文章をそのまま流用しないこと。あくまで構造・トーン・質感を学習して新しい文章を書く

## 入力データ

### 新着記事リスト（まだメルマガで紹介していない記事。ここから各案のメイン記事を選ぶこと）
{new_articles_text}

### 1on1総研 全記事一覧（関連記事の追加選定用。URLはここから正確に引用すること）
{all_articles_text}

### 今週の企画案（HRトレンドの要約。テーマ決定の参考にする）
{plans_text}

### 過去17回のメルマガ全文（構造・トーン・質感の学習用。特に第10〜17回を重点的に参照）
{past_newsletters_text[:30000]}

## 出力形式

以下のJSON形式で3案を出力してください:

```json
[
  {{
    "draft_number": 1,
    "intro_pattern": "使用した導入パターン（A/B/C/Dのいずれか）",
    "anchor_article": {{"title": "メイン新着記事のタイトル", "url": "メイン新着記事のURL"}},
    "theme": "テーマの要約（20字以内）",
    "title": "メルマガタイトル",
    "body": "メルマガ本文（フルテキスト）",
    "selected_articles": [
      {{"title": "記事タイトル", "url": "記事URL"}}
    ]
  }},
  ...
]
```

重要:
- bodyフィールドには、冒頭の挨拶からフッターまで、配信可能な完全なメルマガ本文を入れてください。
- 3案それぞれで異なる導入パターンを使うこと（intro_patternフィールドに明記）。
- チェックリスト型（パターンD）は3案のうち最大1案まで。
- anchor_articleは新着記事リストから選んだメイン記事。selected_articlesにはanchor_article＋追加の関連記事を含めること。
- selected_articlesの1本目は必ずanchor_article（新着記事）にすること。
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.85,
            max_output_tokens=24000,
            response_mime_type="application/json",
        ),
    )

    raw = response.text.strip()

    # JSONパース
    try:
        drafts = json.loads(raw)
    except json.JSONDecodeError:
        # コードブロック内のJSONを抽出
        match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            drafts = json.loads(match.group(1))
        else:
            print("  エラー: JSONパースに失敗しました")
            # フォールバック: テキストとして保存
            return [{"draft_number": 1, "theme": "パース失敗", "title": "要手動確認", "body": raw, "selected_articles": []}]

    print(f"  → {len(drafts)} 案の草稿を生成")
    return drafts


# ── Step 6: ファイル保存 & Google Driveアップロード ──────────
def save_drafts(drafts, target_date):
    """テキストファイルとして保存"""
    date_str = target_date.strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"{date_str}_newsletter_drafts.txt"

    lines = []
    lines.append(f"# 1on1総研 メルマガ草稿 ({date_str})")
    lines.append(f"# 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    for draft in drafts:
        n = draft.get("draft_number", "?")
        theme = draft.get("theme", "")
        title = draft.get("title", "")
        body = draft.get("body", "")
        articles = draft.get("selected_articles", [])

        lines.append("=" * 70)
        anchor = draft.get("anchor_article", {})
        intro_p = draft.get("intro_pattern", "?")

        lines.append(f"## 案{n}: {theme}")
        lines.append(f"## タイトル: {title}")
        lines.append(f"## 導入パターン: {intro_p}")
        lines.append(f"## メイン新着記事: {anchor.get('title', '?')} ({anchor.get('url', '')})")
        lines.append(f"## 選定記事:")
        for a in articles:
            lines.append(f"##   - {a.get('title', '')} ({a.get('url', '')})")
        lines.append("=" * 70)
        lines.append("")
        lines.append(body)
        lines.append("")
        lines.append("")

    content = "\n".join(lines)
    output_path.write_text(content, encoding="utf-8")
    print(f"  保存: {output_path}")

    # JSONも保存
    json_path = OUTPUT_DIR / f"{date_str}_newsletter_drafts.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=2)
    print(f"  保存: {json_path}")

    return output_path


def upload_to_drive(local_path):
    """Google Driveにアップロード"""
    if not TOKEN_FILE.exists():
        print("  スキップ: token.json が未作成です（Google Driveアップロードなし）")
        return

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json())
            else:
                print("  スキップ: OAuthトークンが無効です（手動で再認証してください）")
                return

        service = build("drive", "v3", credentials=creds)

        filename = local_path.name

        # 同名ファイルがあれば上書き
        query = f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id)").execute()
        existing = results.get("files", [])

        media = MediaFileUpload(str(local_path), mimetype="text/plain", resumable=True)

        if existing:
            updated = service.files().update(
                fileId=existing[0]["id"],
                media_body=media,
                fields="id, name, webViewLink"
            ).execute()
            print(f"  Drive更新: {updated.get('webViewLink')}")
        else:
            file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
            created = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink"
            ).execute()
            print(f"  Driveアップロード: {created.get('webViewLink')}")

    except Exception as e:
        print(f"  Drive アップロード失敗: {e}")
        print("  ローカルファイルは保存済みです。")


# ── 過去メルマガテキストの読み込み ─────────────────────────
def load_past_newsletters():
    """過去メルマガをGoogle Drive APIまたはローカルキャッシュから取得"""
    cache_path = DIR / "newsletter" / "_past_newsletters_cache.txt"

    # キャッシュがあれば使う（7日以内）
    if cache_path.exists():
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if (datetime.now() - mtime).days < 7:
            print("  過去メルマガ: キャッシュ使用")
            return cache_path.read_text(encoding="utf-8")

    # Google Drive APIで取得を試みる
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        READ_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
        TOKEN_READONLY = DIR / "token_readonly.json"

        if TOKEN_READONLY.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_READONLY), READ_SCOPES)
            if not creds.valid and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            service = build("drive", "v3", credentials=creds)
            result = service.files().export(
                fileId=PAST_NEWSLETTER_DOC_ID,
                mimeType="text/plain"
            ).execute()

            text = result.decode("utf-8") if isinstance(result, bytes) else result
            cache_path.write_text(text, encoding="utf-8")
            print("  過去メルマガ: Google Driveから取得・キャッシュ保存")
            return text
    except Exception as e:
        print(f"  過去メルマガ: Drive API取得失敗 ({e})")

    # フォールバック: キャッシュが古くてもあれば使う
    if cache_path.exists():
        print("  過去メルマガ: 古いキャッシュを使用")
        return cache_path.read_text(encoding="utf-8")

    print("  警告: 過去メルマガテキストが取得できませんでした")
    return ""


# ── メイン ──────────────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        target_date = date.today()

    print(f"===== メルマガ草稿生成 ({target_date}) =====")

    # Step 1: 記事一覧取得
    print("\n[1/6] 1on1総研の記事一覧を取得...")
    articles = fetch_articles()
    if not articles:
        print("エラー: 記事が取得できませんでした")
        sys.exit(1)

    # Step 2: 過去メルマガ読み込み
    print("\n[2/6] 過去メルマガのフォーマットを学習...")
    past_text = load_past_newsletters()

    # Step 3: 新着記事の特定（過去メルマガで未紹介の記事）
    print("\n[3/6] 新着記事を特定...")
    featured_urls = extract_featured_urls(past_text)
    print(f"  過去メルマガで紹介済み: {len(featured_urls)} 件")

    new_articles = []
    for a in articles:
        # URL末尾のスラッシュやパラメータを正規化して比較
        url_clean = re.sub(r"[?#].*$", "", a["url"].rstrip("/"))
        if url_clean not in featured_urls:
            new_articles.append(a)

    print(f"  → 未紹介の新着記事: {len(new_articles)} 件")
    for a in new_articles:
        print(f"    - 「{a['title'][:40]}」 {a['url']}")

    if not new_articles:
        print("  警告: 新着記事がありません。全記事からテーマを選定します。")
        new_articles = articles[:5]  # フォールバック

    # Step 4: 今週のデータ読み込み
    print("\n[4/6] 今週のダッシュボードデータを読み込み...")
    plans = load_weekly_plans(target_date)

    # Step 5: Gemini APIで草稿生成
    print("\n[5/6] 新着記事起点でテーマ決定 → 関連記事選定 → 草稿生成...")
    drafts = generate_newsletter_drafts(new_articles, plans, past_text, new_articles, articles)

    # Step 6: 保存 & アップロード
    print("\n[6/6] 保存 & Google Driveアップロード...")
    output_path = save_drafts(drafts, target_date)
    upload_to_drive(output_path)

    print("\n===== 完了 =====")
    for d in drafts:
        anchor = d.get("anchor_article", {})
        anchor_title = anchor.get("title", "?")[:30]
        print(f"  案{d.get('draft_number', '?')}: {d.get('title', '')[:50]}")
        print(f"    起点記事: {anchor_title}")


if __name__ == "__main__":
    main()
