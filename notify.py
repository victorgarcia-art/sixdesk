"""Avisos: Telegram (bot) y/o webhook (Make.com). Ambos opcionales, por variables de entorno."""
import os, requests

def notify(text: str):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=10)
        except Exception as e:
            print("telegram error", e)
    hook = os.getenv("WEBHOOK_URL")
    if hook:
        try:
            requests.post(hook, json={"text": text}, timeout=10)
        except Exception as e:
            print("webhook error", e)
