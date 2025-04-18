import os
import time
import json
import threading
import requests
import pandas as pd
from flask import Flask, request
from pytrends.request import TrendReq
from datetime import datetime

# === Config ===
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or 'YOUR_TELEGRAM_TOKEN'
TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID') or 0)
app = Flask(__name__)

# State
KEYWORDS = []
CURRENT_TIMEFRAME = 'now 1-d'  # 'now 1-d', 'now 7-d', 'now 30-d'
ENABLED = True
CHECK_INTERVAL = 900  # seconds
checked_queries = set()
recent_trends = []
pytrends = TrendReq(hl='en-US', tz=0)

# Helpers
def send_telegram(text, reply_markup=None):
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=payload)

# Export to Excel
def export_to_xlsx() -> str:
    if not recent_trends:
        return None
    df = pd.DataFrame(recent_trends)
    filename = 'trends_export.xlsx'
    df.to_excel(filename, index=False)
    return filename

# Trend check
def check_trends():
    if not ENABLED or not KEYWORDS:
        return
    for kw in KEYWORDS:
        try:
            pytrends.build_payload([kw], timeframe=CURRENT_TIMEFRAME)
            related = pytrends.related_queries().get(kw, {}).get('rising')
            if related is None or related.empty:
                continue
            top = related.head(5)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            msg = f"<b>Тренды по '{kw}' ({CURRENT_TIMEFRAME}):</b>"
            for _, row in top.iterrows():
                msg += f"\n– {row['query']} ({row['value']})"
                recent_trends.append({
                    'keyword': kw,
                    'query': row['query'],
                    'value': row['value'],
                    'time': timestamp
                })
            send_telegram(msg)
        except Exception as e:
            send_telegram(f"Ошибка при запросе трендов '{kw}': {e}")

# Background loop
def trends_loop():
    while True:
        check_trends()
        time.sleep(CHECK_INTERVAL)

# Webhook
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global CURRENT_TIMEFRAME, ENABLED
    data = request.json
    # Inline callback
    if 'callback_query' in data:
        cmd = data['callback_query']['data']
        answer = None
        if cmd.startswith('tf_'):
            tf_map = {'1d': 'now 1-d', '7d': 'now 7-d', '30d': 'now 30-d'}
            key = cmd.split('_')[1]
            CURRENT_TIMEFRAME = tf_map.get(key, CURRENT_TIMEFRAME)
            answer = f"⏱ Период установлен: {key}"
        elif cmd == 'enable':
            ENABLED = True
            answer = "🤖 Бот включен"
        elif cmd == 'disable':
            ENABLED = False
            answer = "🤖 Бот отключён"
        if answer:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery',
                data={'callback_query_id': data['callback_query']['id'], 'text': answer}
            )
            send_telegram(answer)
        return {'ok': True}

    text = data.get('message', {}).get('text', '')
    # Menu
    if text == '/start':
        kb = [
            [{'text': '📆 Период'}],
            [{'text': '➕ Добавить слово'}, {'text': '🔍 Тренды'}],
            [{'text': '📥 Excel'}, {'text': '📊 Статус бота'}],
            [{'text': '⏸️ Отключить'}, {'text': '▶️ Включить'}]
        ]
        send_telegram("Привет! Выбери действие:", {'keyboard': kb, 'resize_keyboard': True})
    elif text == '📆 Период':
        inline = [[
            {'text': '1 день', 'callback_data': 'tf_1d'},
            {'text': '7 дней', 'callback_data': 'tf_7d'},
            {'text': '30 дней', 'callback_data': 'tf_30d'}
        ]]
        send_telegram("Выберите период:", {'inline_keyboard': inline})
    elif text == '➕ Добавить слово':
        send_telegram("✍️ Отправь слово для отслеживания трендов:")
    elif text.startswith('/add '):
        kw = text.split('/add ',1)[1].strip()
        if kw and kw not in KEYWORDS:
            KEYWORDS.append(kw)
            send_telegram(f"✅ Добавлено слово: {kw}")
    elif text == '🔍 Тренды':
        check_trends()
        send_telegram('🔍 Принудительный поиск трендов выполнен')
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
    elif text == '📊 Статус бота':
        status = 'включён' if ENABLED else 'отключён'
        send_telegram(
            f"🤖 Статус: {status}\n"
            f"🕒 Период: {CURRENT_TIMEFRAME}\n"
            f"🔤 Слова: {', '.join(KEYWORDS) if KEYWORDS else '—'}"
        )
    elif text == '⏸️ Отключить':
        ENABLED = False
        send_telegram("🤖 Бот отключён")
    elif text == '▶️ Включить':
        ENABLED = True
        send_telegram("🤖 Бот включён")
    return {'ok': True}

if __name__ == '__main__':
    threading.Thread(target=trends_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
