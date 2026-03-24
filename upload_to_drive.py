#!/usr/bin/env python3
"""
ダッシュボードHTMLをGoogle Driveにアップロードするスクリプト。

初回実行時にブラウザでOAuth認証が必要。
認証後はトークンが token.json に保存され、以降は自動実行可能。

使い方:
    python upload_to_drive.py                  # 今日のダッシュボードをアップロード
    python upload_to_drive.py 2026-03-21       # 日付指定
"""

import os
import sys
from datetime import date
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- 設定 ---
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_ID = "1GTNI6pcdtjlcWh0-qNQMly-wWB8hhK0j"

DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = DIR / "credentials.json"
TOKEN_FILE = DIR / "token.json"
DASHBOARD_DIR = DIR / "dashboard"


def get_credentials():
    """認証情報を取得。OAuthトークン（環境変数 or ファイル）→ブラウザ認証の順で試行。"""
    import json

    # 1. 環境変数からOAuthトークン（CI / GitHub Actions向け）
    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN")
    if oauth_token_json:
        print("  環境変数からOAuthトークンを使用（CI モード）")
        token_data = json.loads(oauth_token_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            print("  トークンを更新中...")
            creds.refresh(Request())
        return creds

    # 2. 既存OAuthトークンファイル（ローカル開発向け）
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  トークンを更新中...")
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"エラー: {CREDENTIALS_FILE} が見つかりません。")
                print("GCPコンソールからOAuthクライアントIDのJSONをダウンロードして配置してください。")
                sys.exit(1)
            print("  ブラウザでGoogleアカウント認証を行ってください...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # トークンを保存
        TOKEN_FILE.write_text(creds.to_json())
        print(f"  トークンを保存: {TOKEN_FILE}")

    return creds


def upload_file(service, local_path, folder_id):
    """ファイルをGoogle Driveにアップロード。同名ファイルがあれば上書き。"""
    filename = local_path.name

    # 同名ファイルが既にあるか検索
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get("files", [])

    media = MediaFileUpload(str(local_path), mimetype="text/html", resumable=True)

    if existing:
        # 上書き更新
        file_id = existing[0]["id"]
        updated = (
            service.files()
            .update(fileId=file_id, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        print(f"  更新完了: {updated.get('name')} -> {updated.get('webViewLink')}")
        return updated
    else:
        # 新規作成
        file_metadata = {"name": filename, "parents": [folder_id]}
        created = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        print(f"  アップロード完了: {created.get('name')} -> {created.get('webViewLink')}")
        return created


def main():
    # 日付の決定
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = date.today().strftime("%Y-%m-%d")

    dashboard_path = DASHBOARD_DIR / f"{target_date}_dashboard.html"

    if not dashboard_path.exists():
        print(f"エラー: ダッシュボードが見つかりません: {dashboard_path}")
        sys.exit(1)

    print(f"Google Driveへアップロード: {dashboard_path.name}")
    print(f"  アップロード先フォルダ: {FOLDER_ID}")

    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)

    upload_file(service, dashboard_path, FOLDER_ID)
    print("完了!")


if __name__ == "__main__":
    main()
