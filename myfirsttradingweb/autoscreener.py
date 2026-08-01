import os
import json
import time
import threading
import requests
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from datetime import datetime
from zoneinfo import ZoneInfo

from indicators import (
    TIMEFRAMES, analyze_timeframe, generate_signal, calc_position_sizing
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def now_vn_str():
    """Trả về chuỗi giờ hiện tại theo múi giờ Việt Nam (UTC+7), bất kể server chạy ở đâu."""
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
# Lấy từ @BotFather (token) và @userinfobot hoặc getUpdates API (chat_id).
# Nếu không set biến môi trường, bot vẫn chạy bình thường, chỉ là không gửi Telegram.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Nhớ tín hiệu đã gửi lần quét trước, để chỉ báo khi có tín hiệu MỚI hoặc ĐỔI CHIỀU,
# tránh spam Telegram mỗi 5 phút với cùng 1 tín hiệu cũ.
_last_alerted = {}

def send_telegram_alert(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        emoji = "🟢" if "BUY" in item["signal"] else "🔴"
        text = (
            f"{emoji} <b>{item['symbol']}</b> — {item['signal']}\n\n"
            f"💰 Entry: <code>{item['entry']}</code>\n"
            f"🛑 SL: <code>{item['stop_loss']}</code>\n"
            f"🎯 TP: <code>{item['take_profit']}</code>\n"
            f"📊 RSI M15: {item['rsi_m15']} | Hội tụ: {item['confluence_pct']}%\n"
            f"💵 Volume 24h: {item.get('volume_24h_fmt', 'N/A')}\n"
            f"⚖️ Risk: {item['risk_level']} ({item['risk_percent']}% TK) | "
            f"Khối lượng đề xuất: {item['position_pct']}% TK\n"
            f"💡 {item['reason']}\n"
            f"🕐 {item['time_str']}"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=8)
    except Exception as e:
        print(f"[⚠️ TELEGRAM] Lỗi gửi thông báo cho {item.get('symbol')}: {e}")

def notify_new_signals(signals_to_upload):
    """So sánh với lần quét trước, chỉ gửi Telegram cho tín hiệu MỚI hoặc ĐỔI CHIỀU."""
    global _last_alerted
    for symbol, item in signals_to_upload.items():
        prev_signal = _last_alerted.get(symbol)
        if prev_signal != item["signal"]:
            send_telegram_alert(item)
    _last_alerted = {symbol: item["signal"] for symbol, item in signals_to_upload.items()}

# ------------------------------------------------------------------
# 3. WATCHLIST TOP 100 THEO VỐN HÓA + LỌC THEO VOLUME 24H
# ------------------------------------------------------------------
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

STABLECOIN_BASES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "PYUSD"}

# Ngưỡng volume 24h tối thiểu (đơn vị USDT) để coin được đưa vào watchlist.
# Đặt qua biến môi trường MIN_VOLUME_USDT nếu muốn đổi, mặc định 5 triệu USDT/24h
# (lọc bớt coin thanh khoản yếu, dễ trượt giá / spread lớn khi vào lệnh thật).
MIN_VOLUME_USDT = float(os.environ.get("MIN_VOLUME_USDT", "5000000"))

FALLBACK_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"
]

_watchlist_cache = {"list": [], "ts": 0}
_volume_cache = {"map": {}, "ts": 0}
WATCHLIST_TTL = 3600  # làm mới top 100 + volume mỗi 1 giờ

def get_binance_usdt_bases():
    res = session.get(BINANCE_EXCHANGE_INFO_URL, timeout=10)
    data = res.json()
    return {
        s["baseAsset"].upper()
        for s in data.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }

def get_binance_24h_volumes():
    """1 lệnh gọi lấy volume 24h (quote volume, đơn vị USDT) của TẤT CẢ cặp trên Binance."""
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
        skipped_low_volume = 0
        for c in coins:
            base = c.get("symbol", "").upper()
            if not base or base in STABLECOIN_BASES:
                continue
            if base not in binance_bases:
                continue

            pair = base + "USDT"
            vol = volumes.get(pair, 0)
            if vol < MIN_VOLUME_USDT:
                skipped_low_volume += 1
                continue

            symbols.append(pair)
            if len(symbols) >= 100:
                break

        if symbols:
            _watchlist_cache["list"] = symbols
            _watchlist_cache["ts"] = now
            print(f"[📋 WATCHLIST] {len(symbols)} coin đạt chuẩn "
                  f"(loại {skipped_low_volume} coin volume < {MIN_VOLUME_USDT:,.0f} USDT/24h)")
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
        import pandas as pd
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
# 5. QUÉT 1 COIN QUA TẤT CẢ KHUNG THỜI GIAN (dùng logic chung từ indicators.py)
# ------------------------------------------------------------------
def scan_symbol(symbol, volumes_map):
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval)
        result = analyze_timeframe(df)
        if result:
            tf_results[tf_label] = result
        time.sleep(0.05)  # tránh dồn request quá nhanh lên Binance

    signal = generate_signal(tf_results)
    if not signal:
        return None

    risk_label, risk_percent, position_pct, needs_leverage = calc_position_sizing(
        entry=signal["entry"], stop_loss=signal["stop_loss"], confluence_pct=signal["confluence_pct"]
    )

    volume_24h = volumes_map.get(symbol, 0)

    return {
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

# ------------------------------------------------------------------
# 6. MINI WEB SERVER (để Render Web Service nhận diện có port mở)
# ------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def health_check():
    return {
        "status": "ok",
        "watchlist_size": len(_watchlist_cache["list"]) or len(FALLBACK_WATCHLIST),
        "min_volume_usdt": MIN_VOLUME_USDT,
        "telegram_enabled": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
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
            if result:
                signals_to_upload[symbol] = result
        except Exception as e:
            print(f"[⚠️ ERROR] {symbol}: {e}")
            continue

        if idx % 20 == 0:
            print(f"[...] Đã quét {idx}/{len(watchlist)} coin")

    if signals_to_upload:
        ref.set(signals_to_upload)
        print(f"[🔥 FIREBASE] Tìm thấy {len(signals_to_upload)} kèo chất lượng cao trên {len(watchlist)} coin!")
    else:
        ref.set({})
        print(f"[ℹ️ FIREBASE] Không có coin nào hội tụ đủ điều kiện trong {len(watchlist)} coin quét.")

    notify_new_signals(signals_to_upload)

if __name__ == "__main__":
    print("🔥 Đang bật Bot Quét Nâng Cao — Top 100 Coin / Đa Khung / Lọc Volume / Telegram Alert...")

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
