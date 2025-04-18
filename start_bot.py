import os
import time
import json
import threading
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, request
from pytrends.request import TrendReq

# === Config ===
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', 'YOUR_TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID', '0'))
app = Flask(__name__)

# State
timeframes = {'1d': 'now 1-d', '7d': 'now 7-d', '30d': 'now 30-d'}
CURRENT_TIMEFRAME_KEY = '1d'
ENABLED = True
CHECK_INTERVAL = 900  # seconds
checked = set()
recent = []
pytrends = TrendReq(hl='en-US', tz=0)

# Helpers
def send_telegram(text, reply_markup=None):
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=payload)

def export_excel():
    if not recent:
        return None
    df = pd.DataFrame(recent)
    fname = 'new_casinos.xlsx'
    df.to_excel(fname, index=False)
    return fname

# Brand filter
def is_new_brand(q):
    q = q.lower()
    if any(kw in q for kw in ['casino', 'bet', 'play', 'win']):
        return True
    return False

# Fetch new casinos
 def fetch_new_casinos():
    tf = timeframes[CURRENT_TIMEFRAME_KEY]
    try:
        pytrends.build_payload(['online casino'], timeframe=tf)
        related = pytrends.related_queries().get('online casino', {}).get('rising')
    except:
        return
    if related is None or related.empty:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for _, row in related.iterrows():
        q, val = row['query'], row['value']
        if q not in checked and is_new_brand(q):
            checked.add(q)
            recent.append({'query': q, 'value': val, 'time': now, 'period': CURRENT_TIMEFRAME_KEY})
            send_telegram(f"🆕 Новый казино: <b>{q}</b> (value: {val}, период: {CURRENT_TIMEFRAME_KEY})")

# Background loop
def loop():
    while True:
        if ENABLED:
            fetch_new_casinos()
        time.sleep(CHECK_INTERVAL)

# Webhook
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global CURRENT_TIMEFRAME_KEY, ENABLED
    data = request.json
    if 'callback_query' in data:
        cmd = data['callback_query']['data']
        if cmd in timeframes:
            CURRENT_TIMEFRAME_KEY = cmd
            msg = f"⏱ Период: {cmd}"
        elif cmd == 'toggle':
            ENABLED = not ENABLED
            msg = f"🔄 Бот {'включён' if ENABLED else 'отключён'}"
        elif cmd == 'fetch':
            fetch_new_casinos()
            msg = "🔍 Поиск выполнен"
        elif cmd == 'excel':
            path = export_excel()
            if path:
                with open(path, 'rb') as f:
                    requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument', files={'document': f}, data={'chat_id': TELEGRAM_CHAT_ID})
                msg = "📥 Файл с трендами отправлен"
            else:
                msg = "Нет данных для экспорта"
        else:
            return {'ok': True}
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery', data={'callback_query_id': data['callback_query']['id'], 'text': msg})
        send_telegram(msg)
        return {'ok': True}

    text = data.get('message', {}).get('text', '')
    if text == '/start':
        kb = [[{'text':'🔍 Найти казино', 'callback_data':'fetch'}],
             [{'text':'⌛️ Интервал', 'callback_data':'1d'},{'text':'7d','callback_data':'7d'},{'text':'30d','callback_data':'30d'}],
             [{'text':'💾 Excel', 'callback_data':'excel'},{'text':'🔄 Вкл/Выкл','callback_data':'toggle'}]]
        send_telegram('Выберите действие:', {'inline_keyboard': kb})
    return {'ok': True}

if __name__ == '__main__':
    threading.Thread(target=loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
