import os
import time
import json
import requests
import threading
import re
import pandas as pd
from datetime import datetime
from pytrends.request import TrendReq
from flask import Flask, request

# === Настройки ===
CURRENT_GEO = 'IN'
CURRENT_TIMEFRAME = 'now 1-d'    # 'now 1-d', 'now 7-d', 'now 30-d'
DEFAULT_KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']

# Загрузка ключевых слов из файла
try:
    with open('keywords_base.txt', 'r', encoding='utf-8') as f:
        KEYWORDS = [k.strip() for k in f.read().split(',') if k.strip()]
except FileNotFoundError:
    KEYWORDS = DEFAULT_KEYWORDS.copy()

# Состояние
ACTION_STATE = None
VAL_FILTER_ENABLED = True        # Флаг фильтрации по value
CHECK_INTERVAL = 900             # Интервал проверки трендов (сек)

TELEGRAM_TOKEN = '7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
TELEGRAM_CHAT_ID = 784190963
MIN_TREND_VALUE = 30             # Порог value
FILTER_MODE = True               # Флаг фильтра брендов

# Инициализация
app = Flask(__name__)
pytrends = TrendReq(hl='en-US', tz=330)
checked_queries = set()
recent_trends = []

# === Health check ===
@app.route('/', methods=['GET'])
def index():
    return 'Bot is running', 200

# === Логирование ===
def log(msg: str, file: str = "log.txt"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")
    with open(file, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {msg}\n")

# === Отправка Telegram ===
def send_telegram(msg: str, reply_markup: dict = None):
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=payload)
    except Exception as e:
        log(f"Ошибка Telegram: {e}")

# === Фильтрация брендов ===
def is_probable_new_brand(query: str) -> bool:
    q = query.lower()
    noise = ["how to","trick","strategy","tips","near me","is legal","rules","best","online gambling"]
    if any(phrase in q for phrase in noise) or len(q.split()) > 5:
        return False
    keywords = ["login","register","official","app","apk","casino","slots",
                "bet","rummy","teenpatti","bonus","play","earn","win"]
    if any(w in q for w in keywords):
        return True
    patterns = [
        r"\b(win|fox|cash|luck|mega|star|super)[a-z]{2,}",
        r"[a-z]+(bet|play|win|club|cash|app)\b",
        r"\b[a-z]{3,10}(casino|game|jackpot)\b",
        r"(teenpatti|rummy)\s+(cash|plus|king|master)"
    ]
    return any(re.search(p, q) for p in patterns)

# === Экспорт в Excel ===
def export_to_xlsx() -> str:
    if not recent_trends:
        return None
    df = pd.DataFrame(recent_trends)
    filename = "trends_export.xlsx"
    df.to_excel(filename, index=False)
    return filename

# === Проверка трендов (итерация по KEYWORDS) ===
def check_trends():
    log(f"DEBUG: Запускаю check_trends() timeframe={CURRENT_TIMEFRAME}, geo={CURRENT_GEO}")
    for kw in KEYWORDS:
        # Шаг 1: build_payload для каждого слова
        try:
            pytrends.build_payload([kw], geo=CURRENT_GEO, timeframe=CURRENT_TIMEFRAME)
        except Exception as e:
            log(f"⚠️ Ошибка build_payload для '{kw}': {e}")
            continue
        # Шаг 2: related_queries
        try:
            related = pytrends.related_queries()
        except Exception as e:
            log(f"⚠️ Ошибка related_queries для '{kw}': {e}")
            continue
        log(f"DEBUG: Для '{kw}' related type={type(related)}, keys={list(related.keys())}")
        # Шаг 3: извлечение rising
        rising = related.get(kw, {}).get('rising')
        if rising is None:
            log(f"DEBUG: rising is None для '{kw}'")
            continue
        if hasattr(rising, 'empty') and rising.empty:
            log(f"DEBUG: rising пуст для '{kw}'")
            continue
        log(f"DEBUG: Для '{kw}' найдено {len(rising)} трендов")
        # Шаг 4: обработка каждой строки
        for _, row in rising.iterrows():
            q_val, val = row['query'], row['value']
            if (VAL_FILTER_ENABLED and val < MIN_TREND_VALUE) or q_val in checked_queries:
                continue
            if FILTER_MODE and not is_probable_new_brand(q_val):
                continue
            checked_queries.add(q_val)
            info = {
                "keyword": kw,
                "query": q_val,
                "value": val,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            recent_trends.append(info)
            msg = (f"🆕 Новый запуск по '{kw}' в {CURRENT_GEO} "
                   f"(период {CURRENT_TIMEFRAME}):\n<b>{q_val}</b> (value: {val})")
            send_telegram(msg)
            log(msg, "log_new_trends.txt")

# === Фоновой цикл ===
def trends_loop():
    while True:
        check_trends()
        time.sleep(CHECK_INTERVAL)

# === Webhook и обработка обновлений ===
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global MIN_TREND_VALUE, FILTER_MODE, VAL_FILTER_ENABLED, CURRENT_GEO, CURRENT_TIMEFRAME, ACTION_STATE, KEYWORDS, CHECK_INTERVAL
    data = request.get_json(force=True)
    log(f"⚙️ Incoming update {json.dumps(data, ensure_ascii=False)}")
    log(f"DEBUG: callback_query {data.get('callback_query')}")
    cq = data.get('callback_query')
    if cq:
        cmd = cq.get('data', '')
        answer = None
        if cmd.startswith('set_value_'):
            v = int(cmd.split('_')[-1]); MIN_TREND_VALUE = v; answer = f"✅ Порог value: ≥ {v}"
        elif cmd.startswith('geo_'):
            CURRENT_GEO = cmd.split('_')[-1]; answer = f"🌍 Страна: {CURRENT_GEO}"
        elif cmd.startswith('tf_'):
            m = {'1d':'now 1-d','7d':'now 7-d','30d':'now 30-d'}; l = {'1d':'1 день','7d':'7 дней','30d':'30 дней'}
            tf = cmd.split('_')[-1]; CURRENT_TIMEFRAME = m[tf]; answer = f"⏱ Период: {l[tf]}"
        elif cmd.startswith('int_'):
            sec = int(cmd.split('_')[-1]); CHECK_INTERVAL = sec; answer = f"⏲ Интервал: {sec//60} мин"
        if answer:
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery', data={'callback_query_id': cq['id'], 'text': answer})
            send_telegram(answer)
        return {"ok": True}
    text = data.get('message', {}).get('text', '')
    log(f"DEBUG: message text {text}")
    # ... здесь остальной код меню и команд без изменений ...

if __name__ == '__main__':
    webhook_url = f'https://telegram-trends-bot.onrender.com/{TELEGRAM_TOKEN}'
    try:
        requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}')
        log(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        log(f"Ошибка webhook: {e}")
    threading.Thread(target=trends_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
