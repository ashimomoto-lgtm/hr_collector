# hr_collector プロジェクト

## 概要
毎朝HRニュースを収集・分析し、ダッシュボードとメルマガ下書きを自動生成するパイプライン。

## 主要スクリプト
- `run_daily.sh` — メインの日次実行スクリプト（これを起点に動く）
- `collect_hr_topics.py` — RSSから14+ソースを収集、Gemini APIで分析
- `generate_dashboard.py` — GitHub Pages用ダッシュボード生成
- `generate_newsletter.py` — メルマガ下書き生成
- `generate_plans.py` — コンテンツ企画案生成
- `generate_cta.py` — CTA挿入処理
- `upload_to_drive.py` — Google Driveへのアップロード

## 認証ファイル（Gitに含めない）
- `credentials.json` — Google API認証
- `service_account.json` — Google Service Account
- `token.json` / `token_readonly.json` — OAuthトークン

## 出力先
- `output/` — 収集・分析結果
- `dashboard/` — GitHub Pages配信ファイル
- `newsletter/` — メルマガ下書き
- `plans/` — コンテンツ企画
- `cta_output/` — CTA挿入結果
- `logs/` — 実行ログ

## よく使う操作
```bash
# 日次実行
./run_daily.sh

# メルマガ生成のみ
python generate_newsletter.py

# ダッシュボード再生成
python generate_dashboard.py
```

## 注意事項
- Gemini APIのレスポンスはJSON破損が起きることがある。エラー時は再試行する
- Google Drive uploadはtoken期限切れで失敗することがある。その場合はsetup.shを再実行

## 編集長プレイブック（kajiken digest）

このプロジェクトは**1on1総研の編集長業務**を支える。編集判断（記事企画／SEO／メルマガ／CTA／KPI設計／編集会議）に関わる依頼が来たら、必ず以下を参照軸として使うこと：

- `editor_playbook/principles.md` — 10の編集原則（kajiken0630マガジン全38記事から抽出）
- `editor_playbook/frameworks.md` — 方法論辞典（Goal Oriented／Profit Tree／ARRRA／12人ルール／UX5レイヤー／育成6領域 ほか）
- `editor_playbook/checklists.md` — 企画前／公開前／月次／四半期 チェックリスト
- `editor_playbook/prompts.md` — UVP抽出・因果関係チェック・最高/最悪フロー設計など 10種のプロンプト

**最重要10原則（即参照）**：
1. 「器の中の整理」vs「器を大きくする」を区別 / 2. 問いの質が答えの質を決める / 3. 足し算より引き算 / 4. 方法論よりチーム / 5. 暗黙知を体系化 / 6. データドリブン×仮説検証 / 7. Goal Oriented & Profit Tree（ARRRA優先順） / 8. UVPを20字で / 9. PMF 12人ルール / 10. カテゴリ啓蒙＞自社宣伝

既存スキル（`/hr-planning`, `/seo-article-structure`, `/cta-insertion`, `/melma-writer`, `/illustrate-article`）を呼ぶ際も本プレイブックの原則を適用する。
