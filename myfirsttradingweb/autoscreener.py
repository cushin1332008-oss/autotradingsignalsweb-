"""
autoscreener.py — Worker chạy ngầm phân tích và gửi cảnh báo
------------------------------------------------------------
"""

import os
import json
import time
import requests
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from indicators import (
    TIMEFRAMES, analyze_timeframe, generate_all_signals, calc_position_sizing
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def now_vn_str():
    return datetime.now(VN_TZ).strftime('%H:%M:%S %d/%m/%Y')

secret_path = "/etc/secrets/firebase.json"
env_cred = os.environ.get("FIREBASE_CREDENTIALS")
local_path = "serviceAccountKey.json"

if os.path.exists(secret_path):
    cred = credentials.Certificate(secret_path)
elif env_cred:
    cred = credentials.Certificate(json.loads(env_cred))
elif os.path.exists(local_path):
    cred = credentials.Certificate(local_path)
else:
    raise RuntimeError("Không tìm thấy Firebase Credentials.")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://webtrade-85ca8-default-rtdb.asia-southeast1.firebasedatabase.app'
    })

ref = db.reference('signals')
session = requests.Session()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CUSTOM_LEVERAGE = int(os.environ.get("DEFAULT_LEVERAGE", "50"))

_last_alerted = {}

def send_telegram_alert(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        emoji = "🟢 LONG" if "BUY" in item["signal"] else "🔴 SHORT"
        text = (
            f"{emoji} <b>#{item['symbol']}</b> | {item['trade_timeframe']}\n"
            f"🎯 Bậc tin cậy: <b>{item['confluence_pct']}%</b>\n\n"
            f"📍 <b>Entry 1 (40% Vol):</b> <code>{item['entry_1']}</code>\n"
            f"📍 <b>Entry DCA (60% Vol):</b> <code>{item['entry_dca']}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>{item['stop_loss']}</code>\n\n"
            f"🎯 <b>TP1 (50% Vol):</b> <code>{item['tp1']}</code>\n"
            f"🎯 <b>TP2 (30% Vol):</b> <code>{item['tp2']}</code>\n"
            f"🎯 <b>TP3 (20% Vol):</b> <code>{item['tp3']}</code>\n\n"
            f"🛡️ <b>Rủi ro (Risk):</b> {item['risk_pct']}% TK (${item['risk_usdt']})\n"
            f"⚡ <b>Đòn bẩy:</b> {item['leverage']}x | <b>Margin ký quỹ (TK $1000):</b> ${item['margin_usdt']} ({item['margin_pct']}%)\n"
            f"💡 <b>Lý do:</b> {item['reason']}\n"
            f"🕒 <i>{item['time_str']}</i>"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"[⚠️ TELEGRAM ERROR] {item.get('symbol')}: {e}")

def get_klines(symbol: str, interval: str, limit: int = 200):
    try:
        res = session.get(
            "https://api.binance.com/api/v3/klines", 
            params={"symbol": symbol, "interval": interval, "limit": limit}, 
            timeout=10
        )
        raw = res.json()
        if not isinstance(raw, list) or len(raw) < 60:
            return None
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def analyze_symbol_tf(symbol):
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval)
        res = analyze_timeframe(df)
        if res:
            tf_results[tf_label] = res
    return tf_results

def run_screener():
    print(f"\n[🚀 SCREENER] Bắt đầu quét lúc: {now_vn_str()}")
    watchlist = ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"]
    signals_to_upload = {}

    btc_tf_results = analyze_symbol_tf("BTCUSDT")
    btc_signals = generate_all_signals(btc_tf_results, is_btc=True)
    
    for profile_key, signal in btc_signals.items():
        sizing = calc_position_sizing(signal["entry_1"], signal["stop_loss"], signal["confluence_pct"], profile_key, custom_leverage=CUSTOM_LEVERAGE)
        signals_to_upload[f"BTCUSDT_{profile_key}"] = {
            "symbol": "BTCUSDT", **signal, **sizing, "time_str": now_vn_str()
        }

    def process_altcoin(symbol):
        tf_results = analyze_symbol_tf(symbol)
        signals = generate_all_signals(tf_results, btc_context=btc_tf_results, is_btc=False)
        res = {}
        for profile_key, signal in signals.items():
            sizing = calc_position_sizing(signal["entry_1"], signal["stop_loss"], signal["confluence_pct"], profile_key, custom_leverage=CUSTOM_LEVERAGE)
            res[f"{symbol}_{profile_key}"] = {
                "symbol": symbol, **signal, **sizing, "time_str": now_vn_str()
            }
        return res

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_altcoin, sym): sym for sym in watchlist}
        for future in as_completed(futures):
            try:
                signals_to_upload.update(future.result())
            except Exception as e:
                print(f"[⚠️ ERROR] {e}")

    ref.set(signals_to_upload)
    print(f"[🔥 FIREBASE] Đã cập nhật {len(signals_to_upload)} tín hiệu tuân thủ Trend BTC.")

    global _last_alerted
    for key, item in signals_to_upload.items():
        if _last_alerted.get(key) != item["signal"]:
            send_telegram_alert(item)
    _last_alerted = {key: item["signal"] for key, item in signals_to_upload.items()}

if __name__ == "__main__":
    print(f"[✅ INITIALIZE] Khởi động Auto Screener ({now_vn_str()})")
    run_screener()
    scheduler = BlockingScheduler()
    scheduler.add_job(run_screener, 'interval', minutes=5)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[🛑 STOPPED] Đã dừng Auto Screener.")
