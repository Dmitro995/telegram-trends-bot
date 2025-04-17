import os
import subprocess
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
NGROK_PATH = 'ngrok.exe'
MIN_TREND_VALUE = 30
FILTER_MODE = True
NGROK_URL = None
ACTION_STATE = None

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
    # Стоп-слова
    NOISE_KEYWORDS = [
        "how to", "trick", "strategy", "tips", "near me", "is legal", "rules", "best", "online gambling"
    ]
    if any(phrase in q for phrase in NOISE_KEYWORDS):
        return False
    # Длина запроса
    if len(q.split()) > 5:
        return False
    # Ключевые слова брендов
    BRAND_KEYWORDS = [
        "login", "register", "official", "app", "apk", "casino", "slots", "bet", "rummy", "teenpatti", "bonus", "play", "earn", "win"
    ]
    if any(word in q for word in BRAND_KEYWORDS):
        return True
    # Регулярные паттерны
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

# === Webhook ===
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global MIN_TREND_VALUE, FILTER_MODE, KEYWORDS, CURRENT_GEO, ACTION_STATE
    data = request.json
    # Обработка inline-кнопок
    if 'callback_query' in data:
        cd = data['callback_query']['data']
        answer = ""
        if cd.startswith("set_value_"):
            v = int(cd.replace("set_value_", ""))
            if 10 <= v <= 100:
                MIN_TREND_VALUE = v
                answer = f"✅ Фильтр обновлён: value ≥ {v}"
            else:
                answer = "❌ Значение должно быть от 10 до 100"
        elif cd.startswith("geo_"):
            CURRENT_GEO = cd.replace("geo_", "")
            answer = f"🌍 Страна установлена: {CURRENT_GEO}"
        if answer:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", data={
                'callback_query_id': data['callback_query']['id'], 'text': answer
            })
            send_telegram(answer)
        return {"ok": True}

    msg = data.get('message', {}).get('text')
    # Меню
    if msg == "/start":
        kb = [[{'text':'📊 Статус бота'},{'text':'🕵️ Последние 10'}],
              [{'text':'📥 Excel'},{'text':'⚙️ Порог'}],
              [{'text':'🎚 Фильтр'},{'text':'🌍 Страна'}],
              [{'text':'➕ Добавить слова'},{'text':'🔍 Показать слова'}],
              [{'text':'🗑 Удалить слова'},{'text':'🔄 Сброс слов'}]]
        send_telegram("👋 Выбери действие:", reply_markup={'keyboard':kb,'resize_keyboard':True})
    elif msg == '📊 Статус бота':
        status = "✅ Подключен" if NGROK_URL else "❌ Выключен"
        send_telegram(f"📡 Статус: {status}\n🌍 Страна: {CURRENT_GEO}\nvalue ≥ {MIN_TREND_VALUE}\n🔤 Слова: {', '.join(KEYWORDS)}\n🎚 Фильтр: {'ВКЛ' if FILTER_MODE else 'ВЫКЛ'}")
    elif msg == '🕵️ Последние 10':
        if recent_trends:
            txt = "\n".join([f"{t['time']} – {t['query']} ({t['value']})" for t in recent_trends[-10:]])
            send_telegram(f"🧾 Последние 10:\n{txt}")
        else:
            send_telegram("Нет данных.")
    elif msg == '📥 Excel':
        path = export_to_xlsx()
        if path:
            with open(path,'rb') as f:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument", files={'document':f}, data={'chat_id':TELEGRAM_CHAT_ID})
        else:
            send_telegram("Нет данных для экспорта.")
    elif msg == '⚙️ Порог':
        inline = [[{'text':str(v),'callback_data':f'set_value_{v}'} for v in range(10,101,10)]]
        send_telegram("🔧 Выбери порог:", reply_markup={'inline_keyboard':inline})
    elif msg == '🎚 Фильтр':
        FILTER_MODE = not FILTER_MODE
        send_telegram(f"🎚 Фильтр {'включён' if FILTER_MODE else 'выключен'}")
    elif msg == '🌍 Страна':
        inline = [[{'text':'🇮🇳 IN','callback_data':'geo_IN'},{'text':'🇪🇬 EG','callback_data':'geo_EG'},{'text':'🇺🇸 US','callback_data':'geo_US'}]]
        send_telegram("🌍 Выбери страну:", reply_markup={'inline_keyboard':inline})
    elif msg == '➕ Добавить слова':
        ACTION_STATE = 'add'
        send_telegram("✍️ Введи слова через запятую:")
    elif msg == '🔍 Показать слова':
        send_telegram(f"🔤 Текущие слова: {', '.join(KEYWORDS)}")
    elif msg == '🗑 Удалить слова':
        ACTION_STATE = 'delete'
        send_telegram("✂️ Введи слова для удаления:")
    elif msg == '🔄 Сброс слов':
        KEYWORDS = DEFAULT_KEYWORDS.copy()
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"🔁 Сброс слов: {', '.join(KEYWORDS)}")
    elif ACTION_STATE == 'add' and msg:
        new = [k.strip().lower() for k in msg.split(',') if k.strip()]
        for w in new:
            if w not in KEYWORDS:
                KEYWORDS.append(w)
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"✅ Добавлено: {', '.join(new)}")
        ACTION_STATE = None
    elif ACTION_STATE == 'delete' and msg:
        rem = [k.strip().lower() for k in msg.split(',') if k.strip()]
        KEYWORDS = [w for w in KEYWORDS if w not in rem]
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"🗑 Удалено: {', '.join(rem)}")
        ACTION_STATE = None
    return {"ok": True}

def trends_loop():
    while True:
        check_trends()
        time.sleep(SLEEP_TIME)

def start_ngrok():
    subprocess.Popen([NGROK_PATH,'http','5000'])
    time.sleep(3)
    r = requests.get('http://localhost:4040/api/tunnels')
    return r.json()['tunnels'][0]['public_url']

def set_webhook(ngrok_url):
    requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={ngrok_url}/{TELEGRAM_TOKEN}")

if __name__ == '__main__':
    NGROK_URL = start_ngrok()
    set_webhook(NGROK_URL)
    threading.Thread(target=trends_loop, daemon=True).start()
    app.run(port=5000)
