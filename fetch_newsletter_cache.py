#!/usr/bin/env python3
"""
過去メルマガテキストをGoogle Driveから取得してキャッシュに保存。

OAuthスコープに drive.readonly が必要なため、
専用のトークン(token_readonly.json)を使用する。
初回はブラウザ認証が開きます。

使い方:
    python fetch_newsletter_cache.py
"""

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = DIR / "credentials.json"
TOKEN_FILE = DIR / "token_readonly.json"
CACHE_PATH = DIR / "newsletter" / "_past_newsletters_cache.txt"

DOC_ID = "1sUFHWfxnbfXGc4TjNNCdJECLZEHclVqOWUSOS5BRFv4"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main():
    CACHE_PATH.parent.mkdir(exist_ok=True)

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"エラー: {CREDENTIALS_FILE} が見つかりません")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    service = build("drive", "v3", credentials=creds)
    result = service.files().export(fileId=DOC_ID, mimeType="text/plain").execute()
    text = result.decode("utf-8") if isinstance(result, bytes) else result

    CACHE_PATH.write_text(text, encoding="utf-8")
    print(f"キャッシュ保存: {CACHE_PATH} ({len(text):,} 文字)")


if __name__ == "__main__":
    main()
