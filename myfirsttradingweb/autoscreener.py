import os
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import pandas as pd
import time

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN (Tự động nhận diện Render Secret File)
# ------------------------------------------------------------------
secret_path = "/etc/secrets/firebase.json"

if os.path.exists(secret_path):
    cred = credentials.Certificate(secret_path)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://webtrade-85ca8-default-rtdb.asia-southeast1.firebasedatabase.app'
})

ref = db.reference('signals')

WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"]
BINANCE_URL = "https://api.binance.com/api/v3/klines"

def get_klines(symbol: str, interval: str, limit: int = 100):
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        res = requests.get(BINANCE_URL, params=params, timeout=5)
        df = pd.DataFrame(res.json(), columns=[
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
# HÀM TÍNH TOÁN CHỈ BÁO BẰNG PANDAS THUẦN (KHÔNG CẦN PANDAS-TA)
# ------------------------------------------------------------------
def calculate_indicators(df_h1, df_m15):
    # Tính EMA 50 cho H1
    df_h1['EMA_50'] = df_h1['close'].ewm(span=50, adjust=False).mean()

    # Tính RSI 14 cho M15
    delta = df_m15['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df_m15['RSI_14'] = 100 - (100 / (1 + rs))

    # Tính MACD (12, 26, 9) cho M15
    exp1 = df_m15['close'].ewm(span=12, adjust=False).mean()
    exp2 = df_m15['close'].ewm(span=26, adjust=False).mean()
    df_m15['MACD'] = exp1 - exp2
    df_m15['MACD_SIGNAL'] = df_m15['MACD'].ewm(span=9, adjust=False).mean()

# ------------------------------------------------------------------
# 2. BỘ PHÂN TÍCH MÔ HÌNH NẾN & CHỈ BÁO NÂNG CAO
# ------------------------------------------------------------------
def analyze_advanced_setup(df_h1, df_m15):
    calculate_indicators(df_h1, df_m15)

    curr_close = df_m15['close'].iloc[-2]
    curr_open = df_m15['open'].iloc[-2]
    prev_close = df_m15['close'].iloc[-3]
    prev_open = df_m15['open'].iloc[-3]

    is_bullish_engulfing = (prev_close < prev_open) and (curr_close > curr_open) and (curr_close > prev_open) and (curr_open < prev_close)
    is_bearish_engulfing = (prev_close > prev_open) and (curr_close < curr_open) and (curr_close < prev_open) and (curr_open > prev_close)

    h1_ema50 = df_h1['EMA_50'].iloc[-1]
    m15_rsi = df_m15['RSI_14'].iloc[-2]
    
    macd_curr = df_m15['MACD'].iloc[-2]
    macd_sig_curr = df_m15['MACD_SIGNAL'].iloc[-2]
    macd_prev = df_m15['MACD'].iloc[-3]
    macd_sig_prev = df_m15['MACD_SIGNAL'].iloc[-3]

    macd_bullish_cross = (macd_prev < macd_sig_prev) and (macd_curr > macd_sig_curr)
    macd_bearish_cross = (macd_prev > macd_sig_prev) and (macd_curr < macd_sig_curr)

    signal_type = None
    reasons = []

    if curr_close > h1_ema50:
        if m15_rsi < 40 and (macd_bullish_cross or is_bullish_engulfing):
            signal_type = "BUY (LONG)"
            reasons.append("H1 Uptrend (Giá > EMA50)")
            if m15_rsi < 40: reasons.append(f"M15 RSI Thấp ({round(m15_rsi,1)})")
            if macd_bullish_cross: reasons.append("MACD M15 Cắt Lên")
            if is_bullish_engulfing: reasons.append("Nến Bullish Engulfing")

    elif curr_close < h1_ema50:
        if m15_rsi > 60 and (macd_bearish_cross or is_bearish_engulfing):
            signal_type = "SELL (SHORT)"
            reasons.append("H1 Downtrend (Giá < EMA50)")
            if m15_rsi > 60: reasons.append(f"M15 RSI Cao ({round(m15_rsi,1)})")
            if macd_bearish_cross: reasons.append("MACD M15 Cắt Xuống")
            if is_bearish_engulfing: reasons.append("Nến Bearish Engulfing")

    return signal_type, " + ".join(reasons), curr_close, m15_rsi

# ------------------------------------------------------------------
# 3. QUÉT & ĐẨY FIREBASE
# ------------------------------------------------------------------
def scan_and_push_to_firebase():
    print(f"\n[🚀 SCANNING] Quét thuật toán Nâng Cao lúc: {time.strftime('%H:%M:%S')}...")
    signals_to_upload = {}

    for symbol in WATCHLIST:
        df_h1 = get_klines(symbol, "1h")
        df_m15 = get_klines(symbol, "15m")

        if df_h1 is None or df_m15 is None or df_h1.empty or df_m15.empty:
            continue

        try:
            signal_type, reason, current_price, rsi = analyze_advanced_setup(df_h1, df_m15)

            if signal_type:
                recent_low = df_m15['low'].tail(10).min()
                recent_high = df_m15['high'].tail(10).max()

                if "BUY" in signal_type:
                    sl = recent_low * 0.998
                    tp = current_price + ((current_price - sl) * 2)
                else:
                    sl = recent_high * 1.002
                    tp = current_price - ((sl - current_price) * 2)

                signals_to_upload[symbol] = {
                    "symbol": symbol,
                    "signal": signal_type,
                    "price": float(current_price),
                    "entry": float(current_price),
                    "stop_loss": round(float(sl), 4),
                    "take_profit": round(float(tp), 4),
                    "reason": reason,
                    "rsi_m15": round(float(rsi), 2),
                    "time_str": time.strftime('%H:%M:%S %d/%m/%Y')
                }
        except Exception:
            continue

    if signals_to_upload:
        ref.set(signals_to_upload)
        print(f"[🔥 FIREBASE] Tìm thấy {len(signals_to_upload)} kèo chất lượng cao!")
    else:
        ref.set({})
        print("[ℹ️ FIREBASE] Chưa có coin nào hội tụ đủ 3 yếu tố kỹ thuật.")

if __name__ == "__main__":
    print("🔥 Đang bật Bot Quét Nâng Cao...")
    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
