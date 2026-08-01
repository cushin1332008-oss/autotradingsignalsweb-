import os
import json
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from datetime import datetime
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def now_vn_str():
    """Trả về chuỗi giờ hiện tại theo múi giờ Việt Nam (UTC+7), bất kể server chạy ở đâu."""
    return datetime.now(VN_TZ).strftime('%H:%M:%S %d/%m/%Y')

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN (giữ nguyên logic 3 cách như bản cũ)
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
# 2. CẤU HÌNH WATCHLIST TOP 100 (lấy từ CoinGecko, khớp với cặp USDT trên Binance)
# ------------------------------------------------------------------
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

STABLECOIN_BASES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "PYUSD"}

FALLBACK_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"
]

_watchlist_cache = {"list": [], "ts": 0}
WATCHLIST_TTL = 3600  # làm mới danh sách top 100 mỗi 1 giờ

def get_binance_usdt_bases():
    res = session.get(BINANCE_EXCHANGE_INFO_URL, timeout=10)
    data = res.json()
    return {
        s["baseAsset"].upper()
        for s in data.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }

def get_top_100_watchlist():
    now = time.time()
    if _watchlist_cache["list"] and now - _watchlist_cache["ts"] < WATCHLIST_TTL:
        return _watchlist_cache["list"]

    try:
        binance_bases = get_binance_usdt_bases()
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 150, "page": 1}
        res = session.get(COINGECKO_MARKETS_URL, params=params, timeout=15)
        coins = res.json()

        symbols = []
        for c in coins:
            base = c.get("symbol", "").upper()
            if not base or base in STABLECOIN_BASES:
                continue
            if base in binance_bases:
                symbols.append(base + "USDT")
            if len(symbols) >= 100:
                break

        if symbols:
            _watchlist_cache["list"] = symbols
            _watchlist_cache["ts"] = now
            print(f"[📋 WATCHLIST] Cập nhật {len(symbols)} coin từ CoinGecko top market cap.")
            return symbols
    except Exception as e:
        print(f"[⚠️ WATCHLIST] Lỗi lấy danh sách top 100: {e}")

    return _watchlist_cache["list"] or FALLBACK_WATCHLIST

# ------------------------------------------------------------------
# 3. KHUNG THỜI GIAN & TRỌNG SỐ (khung lớn quan trọng hơn khung nhỏ)
# ------------------------------------------------------------------
TIMEFRAMES = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
}
TF_WEIGHT = {"M1": 1, "M5": 1.5, "M15": 2, "H1": 3, "H4": 4}
TOTAL_WEIGHT = sum(TF_WEIGHT.values())

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
# 4. PHÂN TÍCH KỸ THUẬT: TREND + RSI + HỖ TRỢ/KHÁNG CỰ + FIBONACCI
# ------------------------------------------------------------------
def find_support_resistance(df, lookback=50, window=3):
    """Tìm vùng hỗ trợ/kháng cự dựa trên đỉnh/đáy cục bộ (swing high/low)."""
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = [], []
    for i in range(window, len(recent) - window):
        seg_h = recent['high'].iloc[i - window: i + window + 1]
        seg_l = recent['low'].iloc[i - window: i + window + 1]
        if recent['high'].iloc[i] == seg_h.max():
            highs.append(recent['high'].iloc[i])
        if recent['low'].iloc[i] == seg_l.min():
            lows.append(recent['low'].iloc[i])
    resistance = max(highs) if highs else recent['high'].max()
    support = min(lows) if lows else recent['low'].min()
    return float(support), float(resistance)

def fibonacci_levels(support, resistance):
    diff = resistance - support
    if diff <= 0:
        return {}
    return {
        "0.236": resistance - diff * 0.236,
        "0.382": resistance - diff * 0.382,
        "0.5":   resistance - diff * 0.5,
        "0.618": resistance - diff * 0.618,
        "0.786": resistance - diff * 0.786,
    }

def nearest_fib_level(price, fib_levels, tolerance_pct=0.5):
    for label, level in fib_levels.items():
        if level <= 0:
            continue
        diff_pct = abs(price - level) / level * 100
        if diff_pct <= tolerance_pct:
            return label
    return None

def analyze_timeframe(df):
    """Trả về trend, RSI, giá, hỗ trợ/kháng cự, và điểm Fib gần nhất cho 1 khung thời gian."""
    df = df.copy()
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI14'] = ta.rsi(df['close'], length=14)

    # dùng nến đã đóng cửa gần nhất (index -2, vì -1 có thể chưa đóng)
    price = df['close'].iloc[-2]
    ema20 = df['EMA20'].iloc[-2]
    ema50 = df['EMA50'].iloc[-2]
    rsi = df['RSI14'].iloc[-2]

    if pd.isna(ema50) or pd.isna(rsi):
        return None

    if price > ema20 > ema50:
        trend = "UP"
    elif price < ema20 < ema50:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support, resistance = find_support_resistance(df)
    fibs = fibonacci_levels(support, resistance)
    near_fib = nearest_fib_level(price, fibs)

    return {
        "price": float(price),
        "rsi": float(rsi),
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "near_fib": near_fib,
    }

# ------------------------------------------------------------------
# 4b. QUẢN LÝ VỐN: PHÂN LOẠI RỦI RO & KHỐI LƯỢNG VÀO LỆNH THEO % TÀI KHOẢN
# ------------------------------------------------------------------
# Nguyên tắc: rủi ro tối đa mỗi lệnh (risk_percent) tính trên % TÀI KHOẢN,
# không phải % giá coin. Tín hiệu càng nhiều khung thời gian đồng thuận
# (confluence_pct càng cao) thì được phép risk cao hơn một chút, và ngược lại.
# Đây là khung quản trị vốn tham khảo (1-2% rule phổ biến trong trading),
# không phải khuyến nghị đầu tư — bạn nên tự điều chỉnh theo khẩu vị rủi ro.
RISK_TIERS = [
    # (ngưỡng confluence_pct tối thiểu, nhãn rủi ro, % tài khoản risk mỗi lệnh)
    (85, "Thấp", 2.0),
    (70, "Trung bình", 1.0),
    (0,  "Cao", 0.5),
]

def classify_risk(confluence_pct):
    for threshold, label, risk_percent in RISK_TIERS:
        if confluence_pct >= threshold:
            return label, risk_percent
    return "Cao", 0.5

def calc_position_sizing(entry, stop_loss, confluence_pct):
    """
    Tính % tài khoản nên vào lệnh dựa trên:
    - risk_percent: % tài khoản chấp nhận mất nếu dính Stop Loss (theo mức độ tín hiệu)
    - khoảng cách entry -> stop loss (%)
    Công thức: vị thế (% tài khoản) = risk_percent / khoảng_cách_SL(%) * 100
    (Áp dụng cho spot / futures 1x, không đòn bẩy)
    """
    risk_label, risk_percent = classify_risk(confluence_pct)

    sl_distance_pct = abs(entry - stop_loss) / entry * 100
    if sl_distance_pct <= 0:
        return risk_label, risk_percent, 0.0, False

    position_pct = risk_percent / sl_distance_pct * 100
    needs_leverage = position_pct > 100
    position_pct = min(position_pct, 100.0)  # không vượt quá 100% tài khoản (không đòn bẩy)

    return risk_label, risk_percent, round(position_pct, 2), needs_leverage

# ------------------------------------------------------------------
# 5. QUÉT 1 COIN QUA TẤT CẢ KHUNG THỜI GIAN & CHẤM ĐIỂM HỘI TỤ (CONFLUENCE)
# ------------------------------------------------------------------
def scan_symbol(symbol):
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval)
        if df is None:
            continue
        result = analyze_timeframe(df)
        if result:
            tf_results[tf_label] = result
        time.sleep(0.05)  # tránh dồn request quá nhanh lên Binance

    h4 = tf_results.get("H4")
    h1 = tf_results.get("H1")
    m15 = tf_results.get("M15")

    if not (h4 and h1 and m15):
        return None

    bull_weight = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "UP")
    bear_weight = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "DOWN")

    signal_type = None
    reasons = []

    # KỊCH BẢN LONG: H4 & H1 cùng xu hướng tăng, M15 RSI thấp, giá chạm Fib hoặc vùng hỗ trợ
    if h4["trend"] == "UP" and h1["trend"] == "UP" and m15["rsi"] < 45:
        near_support = abs(m15["price"] - m15["support"]) / m15["support"] * 100 < 1.0
        if m15["near_fib"] or near_support:
            signal_type = "BUY (LONG)"
            reasons.append("H4 & H1 cùng xu hướng Tăng")
            reasons.append(f"M15 RSI thấp ({round(m15['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {m15['near_fib']}" if m15["near_fib"] else "Giá chạm vùng hỗ trợ M15")

    # KỊCH BẢN SHORT: H4 & H1 cùng xu hướng giảm, M15 RSI cao, giá chạm Fib hoặc vùng kháng cự
    elif h4["trend"] == "DOWN" and h1["trend"] == "DOWN" and m15["rsi"] > 55:
        near_resistance = abs(m15["price"] - m15["resistance"]) / m15["resistance"] * 100 < 1.0
        if m15["near_fib"] or near_resistance:
            signal_type = "SELL (SHORT)"
            reasons.append("H4 & H1 cùng xu hướng Giảm")
            reasons.append(f"M15 RSI cao ({round(m15['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {m15['near_fib']}" if m15["near_fib"] else "Giá chạm vùng kháng cự M15")

    if not signal_type:
        return None

    price = m15["price"]
    if "BUY" in signal_type:
        sl = m15["support"] * 0.998
        tp = price + (price - sl) * 2
        confluence_pct = round(bull_weight / TOTAL_WEIGHT * 100, 1)
    else:
        sl = m15["resistance"] * 1.002
        tp = price - (sl - price) * 2
        confluence_pct = round(bear_weight / TOTAL_WEIGHT * 100, 1)

    risk_label, risk_percent, position_pct, needs_leverage = calc_position_sizing(
        entry=price, stop_loss=sl, confluence_pct=confluence_pct
    )

    return {
        "symbol": symbol,
        "signal": signal_type,
        "price": float(price),
        "entry": float(price),
        "stop_loss": round(float(sl), 6),
        "take_profit": round(float(tp), 6),
        "reason": " + ".join(reasons),
        "rsi_m15": round(float(m15["rsi"]), 2),
        "confluence_pct": confluence_pct,
        "support": round(m15["support"], 6),
        "resistance": round(m15["resistance"], 6),
        "risk_level": risk_label,             # Thấp / Trung bình / Cao
        "risk_percent": risk_percent,          # % tài khoản chấp nhận mất nếu dính SL
        "position_pct": position_pct,          # % tài khoản nên phân bổ vào lệnh này
        "needs_leverage": needs_leverage,      # True nếu vị thế cần đòn bẩy mới đủ risk chuẩn
        "time_str": now_vn_str()
    }

# ------------------------------------------------------------------
# 6. MINI WEB SERVER (để Render Web Service nhận diện có port mở)
# ------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def health_check():
    return {"status": "ok", "watchlist_size": len(_watchlist_cache["list"]) or len(FALLBACK_WATCHLIST)}

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ------------------------------------------------------------------
# 7. QUÉT TOÀN BỘ WATCHLIST & ĐẨY FIREBASE
# ------------------------------------------------------------------
def scan_and_push_to_firebase():
    print(f"\n[🚀 SCANNING] Bắt đầu quét lúc: {now_vn_str()}...")
    watchlist = get_top_100_watchlist()
    signals_to_upload = {}

    for idx, symbol in enumerate(watchlist, start=1):
        try:
            result = scan_symbol(symbol)
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

if __name__ == "__main__":
    print("🔥 Đang bật Bot Quét Nâng Cao — Top 100 Coin / Đa Khung Thời Gian...")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    # Quét 100 coin x 5 khung thời gian tốn nhiều request hơn hẳn bản cũ (10 coin x 1 khung)
    # nên giãn chu kỳ quét ra 5 phút để tránh quá tải / bị Binance giới hạn tốc độ.
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=5, max_instances=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
