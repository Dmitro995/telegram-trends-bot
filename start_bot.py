import os
import time
import requests
from pytrends.request import TrendReq
from flask import Flask, request
import pandas as pd
from datetime import datetime
import threading
import re
import json

# === Настройки ===
CURRENT_GEO = 'IN'
DEFAULT_KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']
# Загружаем ключевые слова из файла (если существует)
try:
    with open('keywords_base.txt', 'r', encoding='utf-8') as f:
        KEYWORDS = [k.strip() for k in f.read().split(',') if k.strip()]
except FileNotFoundError:
    KEYWORDS = DEFAULT_KEYWORDS.copy()

TELEGRAM_TOKEN = '7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
TELEGRAM_CHAT_ID = 784190963
MIN_TREND_VALUE = 30
FILTER_MODE = True

app = Flask(__name__)
checked_queries = set()
recent_trends = []
SLEEP_TIME = 900  # 15 минут
pytrends = TrendReq(hl='en-US', tz=330)

# === Логирование ===
def log(msg, file="log.txt"):
    print(msg)
    with open(file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

# === Отправка сообщений в Telegram ===
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

# === Фильтрация брендов ===
def is_probable_new_brand(query):
    q = query.lower()
    NOISE_KEYWORDS = [
        "how to", "trick", "strategy", "tips", "near me", "is legal", "rules", "best", "online gambling"
    ]
    if any(phrase in q for phrase in NOISE_KEYWORDS):
        return False
    if len(q.split()) > 5:
        return False
    BRAND_KEYWORDS = [
        "login", "register", "official", "app", "apk", "casino", "slots", "bet", "rummy", "teenpatti", "bonus", "play", "earn", "win"
    ]
    if any(word in q for word in BRAND_KEYWORDS):
        return True
    BRAND_PATTERNS = [
        r"\b(win|fox|cash|luck|mega|star|super)[a-z]{2,}",
        r"[a-z]+(bet|play|win|club|cash|app)\b",
        r"\b[a-z]{3,10}(casino|game|jackpot)\b",
        r"(teenpatti|rummy)\s+(cash|plus|king|master)"
    ]
    for pattern in BRAND_PATTERNS:
        if re.search(pattern, q):
            return True
    return False

# === Экспорт в Excel ===
def export_to_xlsx():
    if not recent_trends:
        return None
    df = pd.DataFrame(recent_trends)
    filename = "trends_export.xlsx"
    df.to_excel(filename, index=False)
    return filename

# === Проверка трендов ===
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
                    if not FILTER_MODE or is_probable_new_brand(query):
                        checked_queries.add(query)
                        info = {"query": query, "value": val, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        recent_trends.append(info)
                        msg = f"🆕 Новый запуск казино в {CURRENT_GEO}:\n<b>{query}</b> (value: {val})"
                        send_telegram(msg)
                        log(msg, "log_new_casinos.txt")
    except Exception as e:
        log(f"⚠️ Ошибка цикла: {e}")

# === Webhook и обработка сообщений ===
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global MIN_TREND_VALUE, FILTER_MODE, KEYWORDS, CURRENT_GEO, ACTION_STATE
    data = request.json
    # ... остальной код обработки callback_query и сообщений без изменений ...
    return {"ok": True}

# === Цикл трендов в отдельном потоке ===
def trends_loop():
    while True:
        check_trends()
        time.sleep(SLEEP_TIME)

if __name__ == '__main__':
    # Установка webhook вручную
    manual_webhook_url = 'https://telegram-trends-bot.onrender.com/7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
    try:
        requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={manual_webhook_url}')
        log(f"Webhook установлен на {manual_webhook_url}")
    except Exception as e:
        log(f"Ошибка при установке webhook: {e}")

    # Запуск цикла проверки трендов в фоне
    trend_thread = threading.Thread(target=trends_loop, daemon=True)
    trend_thread.start()

    # Запуск Flask-приложения на порту из переменной окружения
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
