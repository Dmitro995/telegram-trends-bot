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
CURRENT_TIMEFRAME = 'now 1-d'
DEFAULT_KEYWORDS = ['casino', 'bet', 'play', 'win', 'game']

# Загружаем ключевые слова из файла (если существует)
try:
    with open('keywords_base.txt', 'r', encoding='utf-8') as f:
        KEYWORDS = [k.strip() for k in f.read().split(',') if k.strip()]
except FileNotFoundError:
    KEYWORDS = DEFAULT_KEYWORDS.copy()

# Состояние для добавления/удаления
ACTION_STATE = None
VAL_FILTER_ENABLED = True
# Интервал проверки трендов (секунды)
CHECK_INTERVAL = 900  # 15 минут

TELEGRAM_TOKEN = '7543116655:AAHxgebuCQxGzY91o-sTxV2PSZjEe2nBWF8'
TELEGRAM_CHAT_ID = 784190963
MIN_TREND_VALUE = 30
FILTER_MODE = True

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
    with open(file, "a", encoding="utf-8") as f:
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

# === Фильтрация брендов ===
def is_probable_new_brand(query: str) -> bool:
    q = query.lower()
    NOISE_KEYWORDS = ["how to","trick","strategy","tips","near me","is legal","rules","best","online gambling"]
    if any(phrase in q for phrase in NOISE_KEYWORDS) or len(q.split())>5:
        return False
    BRAND_KEYWORDS = ["login","register","official","app","apk","casino","slots","bet","rummy","teenpatti","bonus","play","earn","win"]
    if any(word in q for word in BRAND_KEYWORDS): return True
    patterns = [r"\b(win|fox|cash|luck|mega|star|super)[a-z]{2,}",r"[a-z]+(bet|play|win|club|cash|app)\b",r"\b[a-z]{3,10}(casino|game|jackpot)\b",r"(teenpatti|rummy)\s+(cash|plus|king|master)"]
    return any(re.search(p,q) for p in patterns)

# === Экспорт в Excel ===
def export_to_xlsx() -> str:
    if not recent_trends: return None
    df = pd.DataFrame(recent_trends)
    filename = "trends_export.xlsx"
    df.to_excel(filename, index=False)
    return filename

# === Проверка трендов ===
def check_trends():
    log(f"DEBUG: Запускаю check_trends() timeframe={CURRENT_TIMEFRAME}, geo={CURRENT_GEO}")
    try:
        pytrends.build_payload(['online casino'], geo=CURRENT_GEO, timeframe=CURRENT_TIMEFRAME)
        related = pytrends.related_queries()
        log(f"DEBUG: related type {type(related)}, keys {list(related.keys())}")
        try:
            log(f"DEBUG: raw related {json.dumps(related,default=str,ensure_ascii=False)}")
        except Exception as ex:
            log(f"DEBUG: не сериализуется related: {ex}, type {type(related)}")
        rising = related.get('online casino',{}).get('rising')
        if rising is None:
            log("DEBUG: rising is None")
        elif hasattr(rising,'empty') and rising.empty:
            log("DEBUG: rising empty DataFrame")
        else:
            log(f"DEBUG: rising rows {len(rising)} columns {list(rising.columns)} sample {rising.head().to_dict()}")
            for _,row in rising.iterrows():
                q,val = row['query'],row['value']
                if (not VAL_FILTER_ENABLED or val>=MIN_TREND_VALUE) and q not in checked_queries:
                    if not FILTER_MODE or is_probable_new_brand(q):
                        checked_queries.add(q)
                        info={"query":q,"value":val,"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        recent_trends.append(info)
                        msg=f"🆕 Новый запуск казино в {CURRENT_GEO} (период {CURRENT_TIMEFRAME}):\n<b>{q}</b> (value: {val})"
                        send_telegram(msg)
                        log(msg,"log_new_casinos.txt")
    except Exception as e:
        log(f"⚠️ Ошибка цикла: {e}")

# === Фоновый цикл ===
def trends_loop():
    while True:
        try: check_trends()
        except Exception as e: log(f"⚠️ ошибка в фоне: {e}")
        time.sleep(CHECK_INTERVAL)

# === Webhook ===
@app.route(f'/{TELEGRAM_TOKEN}',methods=['POST'])
def webhook():
    global MIN_TREND_VALUE,FILTER_MODE,VAL_FILTER_ENABLED,CURRENT_GEO,CURRENT_TIMEFRAME,ACTION_STATE,KEYWORDS,CHECK_INTERVAL
    data=request.get_json(force=True)
    log(f"⚙️ Incoming update {json.dumps(data,ensure_ascii=False)}")
    log(f"DEBUG callback_query {data.get('callback_query')}")
    cq=data.get('callback_query')
    if cq:
        cmd=cq.get('data','')
        answer=None
        if cmd.startswith('set_value_'):
            v=int(cmd.split('_')[-1]); MIN_TREND_VALUE=v; answer=f"✅ Порог value: ≥ {v}"
        elif cmd.startswith('geo_'):
            CURRENT_GEO=cmd.split('_')[-1];answer=f"🌍 Страна: {CURRENT_GEO}"
        elif cmd.startswith('tf_'):
            m={'1d':'now 1-d','7d':'now 7-d','30d':'now 30-d'};l={'1d':'1д','7d':'7д','30d':'30д'}
            tf=cmd.split('_')[-1];CURRENT_TIMEFRAME=m[tf];answer=f"⏱ Период: {l[tf]}"
        elif cmd.startswith('int_'):
            sec=int(cmd.split('_')[-1]);CHECK_INTERVAL=sec;answer=f"⏲ Интервал: {sec//60}мин"
        if answer:
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery',data={'callback_query_id':cq['id'],'text':answer})
            send_telegram(answer)
        return{"ok":True}
    text=data.get('message',{}).get('text','')
    log(f"DEBUG message text {text}")
    if text=='/start':
        kb=[
            [{'text':'📊 Статус бота'},{'text':'🕵️ Последние 10'}],
            [{'text':'📥 Excel'},{'text':'⚙️ Порог'}],
            [{'text':'🎚 Фильтр'},{'text':'🔢 Фильтр value'}],
            [{'text':'🌍 Страна'},{'text':'📆 Период'}],
            [{'text':'⏱ Интервал'}],
            [{'text':'➕ Добавить слова'},{'text':'🔍 Показать слова'}],
            [{'text':'🗑 Удалить слова'},{'text':'🔄 Сброс слов'}],
            [{'text':'🔍 Тест трендов'}]
        ]
        send_telegram('👋 Выбери действие:',reply_markup={'keyboard':kb,'resize_keyboard':True})
    elif text=='🔍 Тест трендов':
        check_trends();send_telegram('🔍 Тест трендов выполнен — глянь логи.')
    elif text=='📊 Статус бота':
        vs=('ON' if VAL_FILTER_ENABLED else 'OFF');p={'now 1-d':'1д','now 7-d':'7д','now 30-d':'30д'}[CURRENT_TIMEFRAME]
        im=CHECK_INTERVAL//60
        send_telegram(f"📡✅ Подключен\n🌍 {CURRENT_GEO}\n⏱ {p}\n⏲ {im}мин\n💹≥{MIN_TREND_VALUE}\n🎚 {('ВКЛ' if FILTER_MODE else 'ВЫКЛ')}\n🔤{','.join(KEYWORDS)}")
    elif text=='🕵️ Последние 10':
        if recent_trends:
            t='\n'.join([f"{i['time']} – {i['query']} ({i['value']})" for i in recent_trends[-10:]]);
            send_telegram(f"🧾 Последние 10:\n{t}")
        else: send_telegram('Нет данных.')
    elif text=='📥 Excel':
        path=export_to_xlsx()
        if path:
            with open(path,'rb')as f:requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',files={'document':f},data={'chat_id':TELEGRAM_CHAT_ID})
        else: send_telegram('Нет данных для экспорта.')
    elif text=='⚙️ Порог':
        send_telegram('🔧 Выбери порог value:',reply_markup={'inline_keyboard':[[{'text':str(v),'callback_data':f'set_value_{v}'} for v in range(0,101,10)]]})
    elif text=='🎚 Фильтр':
        FILTER_MODE=not FILTER_MODE;send_telegram(f"🎚 Фильтр брендов {('ВКЛ' if FILTER_MODE else 'ВЫКЛ')}")
    elif text=='🔢 Фильтр value':
        VAL_FILTER_ENABLED=not VAL_FILTER_ENABLED;send_telegram(f"🔢 Фильтр value {('ON' if VAL_FILTER_ENABLED else 'OFF')}")
    elif text=='🌍 Страна':
        send_telegram('🌍 Выбери страну:',reply_markup={'inline_keyboard':[[{'text':'🇮🇳 IN','callback_data':'geo_IN'},{'text':'🇪🇬 EG','callback_data':'geo_EG'},{'text':'🇺🇸 US','callback_data':'geo_US'}]]})
    elif text=='📆 Период':
        send_telegram('⏱ Выберите период:',reply_markup={'inline_keyboard':[[{'text':'1 день','callback_data':'tf_1d'},{'text':'7 дней','callback_data':'tf_7d'},{'text':'30 дней','callback_data':'tf_30d'}]]})
    elif text=='⏱ Интервал':
        send_telegram('⏱ Выберите интервал:',reply_markup={'inline_keyboard':[[{'text':'1 мин','callback_data':'int_60'},{'text':'5 мин','callback_data':'int_300'},{'text':'15 мин','callback_data':'int_900'}]]})
    elif text=='➕ Добавить слова':
        ACTION_STATE='add';send_telegram('✍️ Введи слова через запятую:')
    elif text=='🔍 Показать слова':
        send_telegram(f"🔤 Текущие слова: {', '.join(KEYWORDS)}")
    elif text=='🗑 Удалить слова':
        ACTION_STATE='delete';send_telegram('✂️ Введи слова для удаления:')
    elif text=='🔄 Сброс слов':
        KEYWORDS=DEFAULT_KEYWORDS.copy();open('keywords_base.txt','w',encoding='utf-8').write(','.join(KEYWORDS));send_telegram(f"🔁 Сброс слов: {', '.join(KEYWORDS)}")
    elif ACTION_STATE=='add' and text:
        new=[w.strip().lower() for w in text.split(',') if w.strip()]
        for w in new:
            if w not in KEYWORDS: KEYWORDS.append(w)
        open('keywords_base.txt','w',encoding='utf-8').write(','.join(KEYWORDS))
        send_telegram(f"✅ Добавлено: {', '.join(new)}");ACTION_STATE=None
    elif ACTION_STATE=='delete' and text:
        rem=[w.strip().lower() for w in text.split(',') if w.strip()]
        KEYWORDS=[w for w in KEYWORDS if w not in rem]
        open('keywords_base.txt','w',encoding='utf-8').write(','.join(KEYWORDS))
        send_telegram(f"🗑 Удалено: {', '.join(rem)}");ACTION_STATE=None
    return {"ok":True}

if __name__=='__main__':
    url=f'https://telegram-trends-bot.onrender.com/{TELEGRAM_TOKEN}'
    try:requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={url}');log(f"Webhook установлен {url}")
    except Exception as e:log(f"Webhook error: {e}")
    threading.Thread(target=trends_loop,daemon=True).start()
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
