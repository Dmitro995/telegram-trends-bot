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
# Параметр timeframe для Google Trends: 'now 1-d', 'now 7-d', 'now 30-d'
CURRENT_TIMEFRAME = 'now 1-d'
DEFAULT_KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']

# Загружаем ключевые слова из файла (если существует)
try:
    with open('keywords_base.txt', 'r', encoding='utf-8') as f:
        KEYWORDS = [k.strip() for k in f.read().split(',') if k.strip()]
except FileNotFoundError:
    KEYWORDS = DEFAULT_KEYWORDS.copy()

# Состояние ввода добавления/удаления слов
ACTION_STATE = None
# Флаг фильтрации по value
VAL_FILTER_ENABLED = True
# Интервал проверки трендов (сек)
CHECK_INTERVAL = 900  # по умолчанию 15 минут

TELEGRAM_TOKEN = '7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
TELEGRAM_CHAT_ID = 784190963
MIN_TREND_VALUE = 30
# Флаг фильтрации по вероятности бренда
FILTER_MODE = True

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
    with open(file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")

# === Отправка сообщений в Telegram ===
def send_telegram(msg: str, reply_markup: dict = None):
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
def is_probable_new_brand(query: str) -> bool:
    q = query.lower()
    NOISE_KEYWORDS = [
        "how to", "trick", "strategy", "tips", "near me", "is legal", "rules", "best", "online gambling"
    ]
    if any(phrase in q for phrase in NOISE_KEYWORDS) or len(q.split()) > 5:
        return False
    BRAND_KEYWORDS = [
        "login", "register", "official", "app", "apk", "casino", "slots",
        "bet", "rummy", "teenpatti", "bonus", "play", "earn", "win"
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
def export_to_xlsx() -> str:
    if not recent_trends:
        return None
    df = pd.DataFrame(recent_trends)
    filename = "trends_export.xlsx"
    df.to_excel(filename, index=False)
    return filename

# === Проверка трендов с логами отладки ===
def check_trends():
    log(f"DEBUG: Запускаю check_trends() с timeframe={CURRENT_TIMEFRAME}, geo={CURRENT_GEO}")
    try:
        pytrends.build_payload(['online casino'], geo=CURRENT_GEO, timeframe=CURRENT_TIMEFRAME)
        related = pytrends.related_queries()
        log(f"DEBUG: related_queries() вернуло: {type(related)} with keys: {list(related.keys())}")
        # Логируем сырые связанные запросы как JSON
        try:
            log(f"DEBUG: Raw related content: {json.dumps(related, default=str, ensure_ascii=False)}")
        except Exception as ex:
            log(f"DEBUG: Не удалось сериализовать related: {ex}, type: {type(related)}").get('rising')
        if rising is None:
            log("DEBUG: rising == None")
        elif hasattr(rising, 'empty') and rising.empty:
            log("DEBUG: rising пустой DataFrame")
        else:
            rows = len(rising)
            log(f"DEBUG: rising содержит {rows} строк")
            for _, row in rising.iterrows():
                query, val = row['query'], row['value']
                if (not VAL_FILTER_ENABLED or val >= MIN_TREND_VALUE) and query not in checked_queries:
                    if not FILTER_MODE or is_probable_new_brand(query):
                        checked_queries.add(query)
                        info = {"query": query, "value": val,
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        recent_trends.append(info)
                        msg = (f"🆕 Новый запуск казино в {CURRENT_GEO} "
                               f"(период {CURRENT_TIMEFRAME}):\n<b>{query}</b> (value: {val})")
                        send_telegram(msg)
                        log(msg, "log_new_casinos.txt")
    except Exception as e:
        log(f"⚠️ Ошибка цикла: {e}")

# === Фоновый цикл ===
def trends_loop():
    while True:
        try:
            check_trends()
        except Exception as e:
            log(f"⚠️ Ошибка в фоне: {e}")
        time.sleep(CHECK_INTERVAL)

# === Webhook и обработка обновлений ===
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    global MIN_TREND_VALUE, FILTER_MODE, VAL_FILTER_ENABLED, CURRENT_GEO, CURRENT_TIMEFRAME, ACTION_STATE, KEYWORDS, CHECK_INTERVAL
    data = request.get_json(force=True)
    log("DEBUG: Вебхук получил данные")
    log(f"⚙️ Incoming update: {json.dumps(data, ensure_ascii=False)}")

    # --- Inline‑кнопки ---
    cq = data.get('callback_query')
    log(f"DEBUG: callback_query: {cq}")
    if cq:
        cmd = cq.get('data', '')
        answer = None
        if cmd.startswith('set_value_'):
            v = int(cmd.split('_')[-1])
            if 0 <= v <= 100:
                MIN_TREND_VALUE = v
                answer = f"✅ Порог value обновлён: ≥ {v}"
        elif cmd.startswith('geo_'):
            CURRENT_GEO = cmd.split('_')[-1]
            answer = f"🌍 Страна установлена: {CURRENT_GEO}"
        elif cmd.startswith('tf_'):
            tf = cmd.split('_')[-1]
            mapping = {'1d': 'now 1-d', '7d': 'now 7-d', '30d': 'now 30-d'}
            labels = {'1d': '1 день', '7d': '7 дней', '30d': '30 дней'}
            if tf in mapping:
                CURRENT_TIMEFRAME = mapping[tf]
                answer = f"⏱ Период: {labels[tf]}"
        elif cmd.startswith('int_'):
            sec = int(cmd.split('_')[-1])
            if sec > 0:
                CHECK_INTERVAL = sec
                minutes = sec // 60
                answer = f"⏲ Интервал обновлён: {minutes} мин"
        if answer:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery',
                data={'callback_query_id': cq['id'], 'text': answer}
            )
            send_telegram(answer)
        return {"ok": True}

    # --- Reply‑кнопки и текстовые команды ---
    text = data.get('message', {}).get('text', '')
    log(f"DEBUG: message text: {text}")
    if text == '/start':
        kb = [
            [{'text': '📊 Статус бота'}, {'text': '🕵️ Последние 10'}],
            [{'text': '📥 Excel'}, {'text': '⚙️ Порог'}],
            [{'text': '🎚 Фильтр'}, {'text': '🔢 Фильтр value'}],
            [{'text': '🌍 Страна'}, {'text': '📆 Период'}],
            [{'text': '⏱ Интервал'}],
            [{'text': '➕ Добавить слова'}, {'text': '🔍 Показать слова'}],
            [{'text': '🗑 Удалить слова'}, {'text': '🔄 Сброс слов'}]
        ]
        send_telegram("👋 Выбери действие:", reply_markup={'keyboard': kb, 'resize_keyboard': True})
    elif text == '📊 Статус бота':
        status = "✅ Подключен"
        val_state = 'ON' if VAL_FILTER_ENABLED else 'OFF'
        period = {'now 1-d': '1 день', 'now 7-d': '7 дней', 'now 30-d': '30 дней'}.get(CURRENT_TIMEFRAME,CURRENT_TIMEFRAME)
        interval_min = CHECK_INTERVAL // 60
        send_telegram(
            f"📡 {status}\n"
            f"🌍 Страна: {CURRENT_GEO}\n"
            f"⏱ Период: {period}\n"
            f"⏲ Интервал: {interval_min} мин\n"
            f"💹 Порог value: ≥ {MIN_TREND_VALUE} (filter {'ON' if VAL_FILTER_ENABLED else 'OFF'})\n"
            f"🎚 Фильтр брендов: {'ВКЛ' if FILTER_MODE else 'ВЫКЛ'}\n"
            f"🔤 Слова: {', '.join(KEYWORDS)}"
        )
    elif text == '🕵️ Последние 10':
        if recent_trends:
            txt = "\n".join([f"{t['time']} – {t['query']} ({t['value']})" for t in recent_trends[-10:]])
            send_telegram(f"🧾 Последние 10:\n{txt}")
        else:
            send_telegram("Нет данных.")
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
            send_telegram("Нет данных для экспорта.")
    elif text == '⚙️ Порог':
        inline = [[{'text': str(v), 'callback_data': f'set_value_{v}'} for v in range(0,101,10)]]
        send_telegram("🔧 Выбери порог value:", reply_markup={'inline_keyboard': inline})
    elif text == '🎚 Фильтр':
        FILTER_MODE = not FILTER_MODE
        send_telegram(f"🎚 Фильтр брендов {'включён' if FILTER_MODE else 'выключен'}")
    elif text == '🔢 Фильтр value':
        VAL_FILTER_ENABLED = not VAL_FILTER_ENABLED
        send_telegram(f"🔢 Фильтр value: {'ON' if VAL_FILTER_ENABLED else 'OFF'}")
    elif text == '🌍 Страна':
        inline = [[{'text':'🇮🇳 IN','callback_data':'geo_IN'},{'text':'🇪🇬 EG','callback_data':'geo_EG'},{'text':'🇺🇸 US','callback_data':'geo_US'}]]
        send_telegram("🌍 Выбери страну:", reply_markup={'inline_keyboard': inline})
    elif text == '📆 Период':
        inline = [[{'text':'1 день','callback_data':'tf_1d'},{'text':'7 дней','callback_data':'tf_7d'},{'text':'30 дней','callback_data':'tf_30d'}]]
        send_telegram("⏱ Выберите период:", reply_markup={'inline_keyboard': inline})
    elif text == '⏱ Интервал':
        inline = [[{'text':'1 мин','callback_data':'int_60'},{'text':'5 мин','callback_data':'int_300'},{'text':'15 мин','callback_data':'int_900'}]]
        send_telegram("⏱ Выберите интервал:", reply_markup={'inline_keyboard': inline})
    elif text == '➕ Добавить слова':
        ACTION_STATE = 'add'
        send_telegram("✍️ Введи слова через запятую:")
    elif text == '🔍 Показать слова':
        send_telegram(f"🔤 Текущие слова: {', '.join(KEYWORDS)}")
    elif text == '🗑 Удалить слова':
        ACTION_STATE = 'delete'
        send_telegram("✂️ Введи слова для удаления:")
    elif text == '🔄 Сброс слов':
        KEYWORDS = DEFAULT_KEYWORDS.copy()
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"🔁 Сброс слов: {', '.join(KEYWORDS)}")
    elif ACTION_STATE == 'add' and text:
        new = [k.strip().lower() for k in text.split(',') if k.strip()]
        for w in new:
            if w not in KEYWORDS:
                KEYWORDS.append(w)
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"✅ Добавлено: {', '.join(new)}")
        ACTION_STATE = None
    elif ACTION_STATE == 'delete' and text:
        rem = [k.strip().lower() for k in text.split(',') if k.strip()]
        KEYWORDS = [w for w in KEYWORDS if w not in rem]
        with open('keywords_base.txt','w',encoding='utf-8') as f:
            f.write(','.join(KEYWORDS))
        send_telegram(f"🗑 Удалено: {', '.join(rem)}")
        ACTION_STATE = None
    return {"ok": True}

if __name__ == '__main__':
    manual_webhook_url = f'https://telegram-trends-bot.onrender.com/{TELEGRAM_TOKEN}'
    try:
        requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={manual_webhook_url}')
        log(f"Webhook установлен на {manual_webhook_url}")
    except Exception as e:
        log(f"Ошибка при установке webhook: {e}")
    threading.Thread(target=trends_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
