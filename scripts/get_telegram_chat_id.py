"""
텔레그램 Chat ID 확인 스크립트
================================
이 스크립트를 실행하면 텔레그램 봇에 메시지를 보낸 사용자의 Chat ID를 확인할 수 있습니다.

사용법:
1. 먼저 텔레그램에서 봇에게 아무 메시지를 보내세요
2. 그 다음 이 스크립트를 실행하세요:
   python scripts/get_telegram_chat_id.py
3. 출력된 Chat ID를 .env 파일의 TELEGRAM_CHAT_ID에 입력하세요
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from app.config import settings


def main():
    if not settings.telegram_bot_token:
        print("❌ 오류: .env 파일에 TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        print("   먼저 텔레그램 @BotFather에서 봇을 만들고 토큰을 .env에 입력하세요.")
        return

    print(f"🔍 봇 토큰으로 업데이트 확인 중...")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"

    try:
        response = requests.get(url, timeout=10)
        data = response.json()

        if not data.get("ok"):
            print(f"❌ 텔레그램 API 오류: {data}")
            return

        results = data.get("result", [])
        if not results:
            print("📭 아직 메시지가 없습니다.")
            print("   텔레그램에서 봇에게 아무 메시지를 보낸 후 다시 실행하세요.")
            return

        print(f"\n📨 {len(results)}개의 업데이트 발견:\n")

        seen_chats = set()
        for update in results:
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            chat_id = chat.get("id")

            if chat_id and chat_id not in seen_chats:
                seen_chats.add(chat_id)
                chat_type = chat.get("type", "unknown")
                name = chat.get("first_name", "") + " " + chat.get("last_name", "")
                username = chat.get("username", "")

                print(f"  Chat ID: {chat_id}")
                print(f"  이름: {name.strip()}")
                print(f"  유저네임: @{username}" if username else "  유저네임: (없음)")
                print(f"  타입: {chat_type}")
                print()

        print("=" * 40)
        print("위의 Chat ID를 .env 파일의 TELEGRAM_CHAT_ID에 입력하세요.")
        print(f"예: TELEGRAM_CHAT_ID={list(seen_chats)[0]}" if seen_chats else "")

    except requests.RequestException as e:
        print(f"❌ 네트워크 오류: {e}")


if __name__ == "__main__":
    main()
