#!/bin/bash
# 毎日の一括実行スクリプト: 収集 → 企画案生成 → ダッシュボード → Drive アップロード

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$DIR/.venv/bin/python3"
DATE=$(date +%Y-%m-%d)
ERRORS=0

echo "===== HR日次パイプライン ($DATE) ====="

echo ""
echo "[1/4] トピック収集..."
if timeout 300 "$PYTHON" "$DIR/collect_hr_topics.py"; then
    echo "  ✓ トピック収集完了"
else
    echo "  ✗ トピック収集に失敗（終了コード: $?）"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "[2/4] 企画案生成..."
if timeout 300 "$PYTHON" "$DIR/generate_plans.py"; then
    echo "  ✓ 企画案生成完了"
else
    echo "  ✗ 企画案生成に失敗（終了コード: $?）"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "[3/4] ダッシュボード生成..."
if timeout 300 "$PYTHON" "$DIR/generate_dashboard.py"; then
    echo "  ✓ ダッシュボード生成完了"
else
    echo "  ✗ ダッシュボード生成に失敗（終了コード: $?）"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "[4/4] Google Driveへアップロード..."
if [ -f "$DIR/token.json" ]; then
    if timeout 120 "$PYTHON" "$DIR/upload_to_drive.py"; then
        echo "  ✓ アップロード完了"
    else
        echo "  ✗ アップロードに失敗（終了コード: $?）"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  スキップ: token.json が未作成です（初回は手動で python upload_to_drive.py を実行してください）"
fi

echo ""
echo "===== 完了 (エラー: ${ERRORS}件) ====="
echo "  トピック:       $DIR/output/${DATE}_hr_topics.md"
echo "  企画案:         $DIR/plans/${DATE}_content_plans.md"
echo "  ダッシュボード: $DIR/dashboard/${DATE}_dashboard.html"

if [ $ERRORS -gt 0 ]; then
    echo "  ⚠ ${ERRORS}件のステップでエラーが発生しました。上記のログを確認してください。"
    exit 1
fi
