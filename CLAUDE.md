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

## 編集判断時の参照軸
編集判断（記事企画 / SEO / メルマガ / CTA / KPI設計）が絡む依頼では `editor-playbook-kajiken` Skill を参照する（`~/.claude/skills/user/editor-playbook-kajiken/`）。
