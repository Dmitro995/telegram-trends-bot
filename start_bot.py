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
CURRENT_GEO = 'IN'                # Код страны для trending_searches
CURRENT_TIMEFRAME = 'now 1-d'     # Не используется в trending_searches
DEFAULT_KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']

# Состояние
ACTION_STATE = None
CHECK_INTERVAL = 900              # Интервал проверки трендов (сек)

TELEGRAM_TOKEN = '7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
TELEGRAM_CHAT_ID = 784190963

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

# === Отправка сообщений ===
def send_telegram(msg: str, reply_markup: dict = None):
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=payload)
    except Exception as e:
        log(f"Ошибка Telegram: {e}")

# === Экспорт в Excel ===
def export_to_xlsx() -> str:
    if not recent_trends:
        return None
    df = pd.DataFrame(recent_trends)
    filename = "trends_export.xlsx"
    df.to_excel(filename, index=False)
    return filename

# === Проверка трендов с помощью trending_searches ===
def check_trends():
    log(f"DEBUG: Запускаю check_trends() using trending_searches for geo={CURRENT_GEO}")
    # Шаг 1: получить топ-20 трендов за последние 24ч
    try:
        df = pytrends.trending_searches(pn=CURRENT_GEO)
    except Exception as e:
        log(f"⚠️ Ошибка trending_searches: {e}")
        return
    # Шаг 2: обработать каждый тренд
    for q in df[0].tolist():
        if q in checked_queries:
            continue
        checked_queries.add(q)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info = {"query": q, "time": timestamp}
        recent_trends.append(info)
        msg = f"🔥 Тренд сейчас в {CURRENT_GEO} (24ч):\n<b>{q}</b>"
        send_telegram(msg)
        log(f"Sent trending: {q}", "log_new_trends.txt")

# === Фоновой цикл ===
def trends_loop():
    while True:
        check_trends()
        time.sleep(CHECK_INTERVAL)

# === Webhook и обработка обновлений ===
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    log(f"⚙️ Incoming update {json.dumps(data, ensure_ascii=False)}")
    # inline callbacks
    cq = data.get('callback_query')
    if cq:
        cmd = cq.get('data', '')
        answer = None
        if cmd == 'run_trends':
            check_trends()
            answer = "🔍 Тренды обновлены"
        if answer:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery',
                data={'callback_query_id': cq['id'], 'text': answer}
            )
            send_telegram(answer)
        return {"ok": True}
    text = data.get('message', {}).get('text', '')
    log(f"DEBUG: message text {text}")

    # --- Меню команд ---
    if text == '/start':
        kb = [
            [{'text':'📊 Статус бота'},{'text':'🕵️ Последние 10'}],
            [{'text':'📥 Excel'},{'text':'🔍 Тест трендов'}]
        ]
        send_telegram('👋 Выбери действие:', reply_markup={'keyboard': kb, 'resize_keyboard': True})
    elif text == '🔍 Тест трендов':
        check_trends()
        send_telegram('🔍 Тренды обновлены — проверь логи.')
    elif text == '📊 Статус бота':
        send_telegram(
            f"📡 ✅ Подключен\n"
            f"🌍 {CURRENT_GEO}\n"
            f"⏲ Интервал: {CHECK_INTERVAL//60} мин\n"
            f"🔤 Отслежено запросов: {len(checked_queries)}"
        )
    elif text == '🕵️ Последние 10':
        if recent_trends:
            last = recent_trends[-10:]
            msg = "\n".join([f"{i['time']} – {i['query']}" for i in last])
            send_telegram(f"🧾 Последние 10 трендов:\n{msg}")
        else:
            send_telegram('Нет данных.')
    elif text == '📥 Excel':
        path = export_to_xlsx()
        if path:
            with open(path, 'rb') as f:
                requests.post(
                    f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
                    files={'document': f},
                    data={'chat_id': TELEGRAM_CHAT_ID}
                )
        else:
            send_telegram('Нет данных для экспорта.')
    return {"ok": True}

if __name__ == '__main__':
    webhook_url = f'https://telegram-trends-bot.onrender.com/{TELEGRAM_TOKEN}'
    try:
        requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}')
        log(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        log(f"Ошибка webhook: {e}")
    threading.Thread(target=trends_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
