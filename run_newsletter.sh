#!/bin/bash
# 毎週火曜の一括実行: メルマガ草稿生成
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$DIR/.venv/bin/python3"
DATE=$(date +%Y-%m-%d)

echo "===== メルマガ草稿生成パイプライン ($DATE) ====="

echo ""
echo "[1/2] 最新トピック収集（当日分がなければ実行）..."
TOPICS_FILE="$DIR/output/${DATE}_hr_topics.md"
if [ ! -f "$TOPICS_FILE" ]; then
    "$PYTHON" "$DIR/collect_hr_topics.py"
    "$PYTHON" "$DIR/generate_plans.py"
else
    echo "  → 今日のデータは収集済み（スキップ）"
fi

echo ""
echo "[2/2] メルマガ草稿を生成..."
"$PYTHON" "$DIR/generate_newsletter.py"

echo ""
echo "===== 完了 ====="
echo "  草稿: $DIR/newsletter/${DATE}_newsletter_drafts.txt"
