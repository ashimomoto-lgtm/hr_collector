#!/bin/bash
# HR トピック収集 + 企画案生成パイプラインのセットアップ
# 使い方: bash setup.sh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== HR パイプライン セットアップ ==="

# 1. 依存パッケージのインストール
echo ""
echo "📦 依存パッケージをインストール..."
pip3 install feedparser requests google-genai

# 2. GEMINI_API_KEY の確認
if [ -z "$GEMINI_API_KEY" ]; then
    echo ""
    echo "⚠ GEMINI_API_KEY が未設定です。企画案生成には必要です。"
    echo "  export GEMINI_API_KEY='your-api-key'"
    echo "  ~/.zshrc に追記しておくと launchd からも使えます。"
fi

# 3. launchd plist の生成（run_daily.sh を毎朝7:00に実行）
PLIST_NAME="com.user.hr-pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
SCRIPT_PATH="$DIR/run_daily.sh"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

chmod +x "$SCRIPT_PATH"

echo ""
echo "⏰ 毎朝7:00に自動実行するよう設定..."

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_PATH}</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/daily_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/daily_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
        <key>GEMINI_API_KEY</key>
        <string>${GEMINI_API_KEY}</string>
    </dict>
</dict>
</plist>
PLIST

# 旧plistがあれば削除
OLD_PLIST="$HOME/Library/LaunchAgents/com.user.hr-collector.plist"
if [ -f "$OLD_PLIST" ]; then
    launchctl unload "$OLD_PLIST" 2>/dev/null || true
    rm "$OLD_PLIST"
    echo "  (旧plist com.user.hr-collector を削除)"
fi

# 4. launchd に登録
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "  パイプライン:  $SCRIPT_PATH"
echo "  自動実行:      毎朝 7:00"
echo "  トピック出力:  $DIR/output/"
echo "  企画案出力:    $DIR/plans/"
echo "  ログ:          $LOG_DIR/"
echo "  plist:         $PLIST_PATH"
echo ""
echo "手動で今すぐ実行するには:"
echo "  bash $SCRIPT_PATH"
echo ""
echo "自動実行を停止するには:"
echo "  launchctl unload $PLIST_PATH"
