import os
import time
import requests
import threading
import pandas as pd
from pytrends.request import TrendReq
from flask import Flask, request
from datetime import datetime
import json
import re

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "CHAT_ID")
MIN_TREND_VALUE = 30
KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']
FILTER_MODE = True
CURRENT_GEO = "IN"
checked_queries = set()
recent_trends = []
SLEEP_TIME = 900
pytrends = TrendReq(hl='en-US', tz=330)
app = Flask(__name__)

def log(msg, file="log.txt"):
    print(msg)
    with open(file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

def send_telegram(msg, reply_markup=None):
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': msg,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=payload)
    except Exception as e:
        log(f"Ошибка Telegram: {e}")

def is_probable_new_brand(query):
    patterns = ['login', 'app', 'official', 'register', 'bet', 'win']
    return any(p in query.lower() for p in patterns) or re.match(r'^[a-zA-Z0-9]{4,12}( win| bet| app)?$', query.lower())

def check_trends():
    try:
        pytrends.build_payload(['online casino'], geo=CURRENT_GEO, timeframe='now 1-d')
        related = pytrends.related_queries()
        rising = None
        if isinstance(related, dict):
            topic_data = related.get('online casino')
            if isinstance(topic_data, dict):
                rising = topic_data.get('rising')
        if isinstance(rising, pd.DataFrame) and not rising.empty:
            for _, row in rising.iterrows():
                query, val = row['query'], row['value']
                if val >= MIN_TREND_VALUE and query not in checked_queries:
                    if any(k in query.lower() for k in KEYWORDS):
                        if not FILTER_MODE or is_probable_new_brand(query):
                            checked_queries.add(query)
                            msg = f"🆕 Новый возможный запуск онлайн-казино в {CURRENT_GEO}:
<b>{query}</b> (value: {val})"
                            send_telegram(msg)
                            log(msg, "log_new_casinos.txt")
    except Exception as e:
        log(f"⚠️ Ошибка цикла: {e}")

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    data = request.json
    msg = data.get('message', {}).get('text', "")
    if msg == "/start":
        send_telegram("✅ Бот запущен и отслеживает тренды.")
    return {"ok": True}

def trends_loop():
    while True:
        check_trends()
        time.sleep(SLEEP_TIME)

def set_webhook(url):
    requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={url}/{TELEGRAM_TOKEN}")

if __name__ == "__main__":
    set_webhook("https://telegram-trends-bot.onrender.com/7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8")
    threading.Thread(target=trends_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)