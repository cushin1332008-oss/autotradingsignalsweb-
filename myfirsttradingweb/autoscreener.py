import os
import json
import time
import threading
import requests
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from datetime import datetime
from zoneinfo import ZoneInfo

from indicators import (
    TIMEFRAMES, TRADE_PROFILES, analyze_timeframe, generate_all_signals, calc_position_sizing
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def now_vn_str():
    return datetime.now(VN_TZ).strftime('%H:%M:%S %d/%m/%Y')

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN
# ------------------------------------------------------------------
secret_path = "/etc/secrets/firebase.json"
env_cred = os.environ.get("FIREBASE_CREDENTIALS")
local_path = "serviceAccountKey.json"

if os.path.exists(secret_path):
    print(f"[🔑 AUTH] Dùng Render Secret File: {secret_path}")
    cred = credentials.Certificate(secret_path)
elif env_cred:
    print("[🔑 AUTH] Dùng biến môi trường FIREBASE_CREDENTIALS")
    cred = credentials.Certificate(json.loads(env_cred))
elif os.path.exists(local_path):
    print(f"[🔑 AUTH] Dùng file local: {local_path}")
    cred = credentials.Certificate(local_path)
else:
    raise RuntimeError(
        "Không tìm thấy Firebase credentials. Xem hướng dẫn Secret File / "
        "biến môi trường FIREBASE_CREDENTIALS / file serviceAccountKey.json."
    )

firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://webtrade-85ca8-default-rtdb.asia-southeast1.firebasedatabase.app'
})

ref = db.reference('signals')
session = requests.Session()

# ------------------------------------------------------------------
# 2. CẤU HÌNH TELEGRAM ALERT
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

_last_alerted = {}  # key: "SYMBOL_PROFILE" -> loại tín hiệu lần quét trước

def send_telegram_alert(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        emoji = "🟢" if "BUY" in item["signal"] else "🔴"
        text = (
            f"{emoji} <b>{item['symbol']}</b> — {item['signal']}\n"
            f"🕒 Khung giao dịch: <b>{item['trade_timeframe']}</b>\n\n"
            f"💰 Entry: <code>{item['entry']}</code>\n"
            f"🛑 SL: <code>{item['stop_loss']}</code>\n"
            f"🎯 TP: <code>{item['take_profit']}</code>\n"
            f"📊 RSI {item['entry_tf']}: {item['rsi_entry_tf']} | Hội tụ: {item['confluence_pct']}%\n"
            f"💵 Volume 24h: {item.get('volume_24h_fmt', 'N/A')}\n"
            f"⚖️ Risk: {item['risk_level']} ({item['risk_percent']}% TK) | "
            f"Khối lượng đề xuất: {item['position_pct']}% TK\n"
            f"💡 {item['reason']}\n"
            f"🕐 {item['time_str']}"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"
        }, timeout=8)
    except Exception as e:
        print(f"[⚠️ TELEGRAM] Lỗi gửi thông báo cho {item.get('symbol')}: {e}")

def notify_new_signals(signals_to_upload):
    global _last_alerted
    for key, item in signals_to_upload.items():
        prev_signal = _last_alerted.get(key)
        if prev_signal != item["signal"]:
            send_telegram_alert(item)
    _last_alerted = {key: item["signal"] for key, item in signals_to_upload.items()}

# ------------------------------------------------------------------
# 3. WATCHLIST TOP 100 THEO VỐN HÓA + LỌC THEO VOLUME 24H
# ------------------------------------------------------------------
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

STABLECOIN_BASES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "PYUSD"}
MIN_VOLUME_USDT = float(os.environ.get("MIN_VOLUME_USDT", "5000000"))

FALLBACK_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"
]

_watchlist_cache = {"list": [], "ts": 0}
_volume_cache = {"map": {}, "ts": 0}
WATCHLIST_TTL = 3600

def get_binance_usdt_bases():
    res = session.get(BINANCE_EXCHANGE_INFO_URL, timeout=10)
    data = res.json()
    return {
        s["baseAsset"].upper()
        for s in data.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }

def get_binance_24h_volumes():
    now = time.time()
    if _volume_cache["map"] and now - _volume_cache["ts"] < WATCHLIST_TTL:
        return _volume_cache["map"]
    try:
        res = session.get(BINANCE_TICKER_24H_URL, timeout=15)
        data = res.json()
        volumes = {d["symbol"]: float(d["quoteVolume"]) for d in data if d["symbol"].endswith("USDT")}
        _volume_cache["map"] = volumes
        _volume_cache["ts"] = now
        return volumes
    except Exception as e:
        print(f"[⚠️ VOLUME] Lỗi lấy volume 24h: {e}")
        return _volume_cache["map"]

def get_top_100_watchlist():
    now = time.time()
    if _watchlist_cache["list"] and now - _watchlist_cache["ts"] < WATCHLIST_TTL:
        return _watchlist_cache["list"]
    try:
        binance_bases = get_binance_usdt_bases()
        volumes = get_binance_24h_volumes()
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": 1}
        res = session.get(COINGECKO_MARKETS_URL, params=params, timeout=15)
        coins = res.json()

        symbols = []
        skipped = 0
        for c in coins:
            base = c.get("symbol", "").upper()
            if not base or base in STABLECOIN_BASES or base not in binance_bases:
                continue
            pair = base + "USDT"
            if volumes.get(pair, 0) < MIN_VOLUME_USDT:
                skipped += 1
                continue
            symbols.append(pair)
            if len(symbols) >= 100:
                break

        if symbols:
            _watchlist_cache["list"] = symbols
            _watchlist_cache["ts"] = now
            print(f"[📋 WATCHLIST] {len(symbols)} coin đạt chuẩn (loại {skipped} coin volume thấp)")
            return symbols
    except Exception as e:
        print(f"[⚠️ WATCHLIST] Lỗi lấy danh sách top 100: {e}")

    return _watchlist_cache["list"] or FALLBACK_WATCHLIST

def format_volume(vol):
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(round(vol))

# ------------------------------------------------------------------
# 4. LẤY DỮ LIỆU NẾN TỪ BINANCE
# ------------------------------------------------------------------
def get_klines(symbol: str, interval: str, limit: int = 210):
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        res = session.get(BINANCE_KLINES_URL, params=params, timeout=8)
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

# ------------------------------------------------------------------
# 5. QUÉT 1 COIN → SINH TÍN HIỆU CHO CẢ 3 PROFILE (SCALP/SWING/POSITION)
# ------------------------------------------------------------------
def scan_symbol(symbol, volumes_map):
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval)
        result = analyze_timeframe(df)
        if result:
            tf_results[tf_label] = result
        time.sleep(0.05)

    all_signals = generate_all_signals(tf_results)
    if not all_signals:
        return {}

    volume_24h = volumes_map.get(symbol, 0)
    output = {}

    for profile_key, signal in all_signals.items():
        risk_label, risk_percent, position_pct, needs_leverage = calc_position_sizing(
            entry=signal["entry"], stop_loss=signal["stop_loss"], confluence_pct=signal["confluence_pct"]
        )
        key = f"{symbol}_{profile_key}"
        output[key] = {
            "symbol": symbol,
            **signal,
            "risk_level": risk_label,
            "risk_percent": risk_percent,
            "position_pct": position_pct,
            "needs_leverage": needs_leverage,
            "volume_24h": round(volume_24h, 0),
            "volume_24h_fmt": format_volume(volume_24h),
            "time_str": now_vn_str()
        }

    return output

# ------------------------------------------------------------------
# 6. MINI WEB SERVER
# ------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def health_check():
    return {
        "status": "ok",
        "watchlist_size": len(_watchlist_cache["list"]) or len(FALLBACK_WATCHLIST),
        "min_volume_usdt": MIN_VOLUME_USDT,
        "telegram_enabled": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "profiles": list(TRADE_PROFILES.keys()),
    }

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ------------------------------------------------------------------
# 7. QUÉT TOÀN BỘ WATCHLIST, ĐẨY FIREBASE & GỬI TELEGRAM
# ------------------------------------------------------------------
def scan_and_push_to_firebase():
    print(f"\n[🚀 SCANNING] Bắt đầu quét lúc: {now_vn_str()}...")
    watchlist = get_top_100_watchlist()
    volumes_map = get_binance_24h_volumes()
    signals_to_upload = {}

    for idx, symbol in enumerate(watchlist, start=1):
        try:
            result = scan_symbol(symbol, volumes_map)
            signals_to_upload.update(result)
        except Exception as e:
            print(f"[⚠️ ERROR] {symbol}: {e}")
            continue

        if idx % 20 == 0:
            print(f"[...] Đã quét {idx}/{len(watchlist)} coin")

    if signals_to_upload:
        ref.set(signals_to_upload)
        by_profile = {}
        for item in signals_to_upload.values():
            by_profile[item["profile"]] = by_profile.get(item["profile"], 0) + 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in by_profile.items())
        print(f"[🔥 FIREBASE] {len(signals_to_upload)} tín hiệu trên {len(watchlist)} coin ({breakdown})")
    else:
        ref.set({})
        print(f"[ℹ️ FIREBASE] Không có coin nào hội tụ đủ điều kiện trong {len(watchlist)} coin quét.")

    notify_new_signals(signals_to_upload)

if __name__ == "__main__":
    print("🔥 Đang bật Bot Quét Nâng Cao — 3 Khung Giao Dịch (Lướt sóng/Trung hạn/Dài hạn)...")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=5, max_instances=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
