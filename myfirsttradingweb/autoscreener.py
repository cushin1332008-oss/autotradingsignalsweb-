import os
import json
import threading
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
import requests
import pandas as pd
import pandas_ta as ta
import time

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN
#    Thử lần lượt 3 cách, theo thứ tự ưu tiên:
#    (a) Render Secret File tại /etc/secrets/firebase.json
#    (b) Biến môi trường FIREBASE_CREDENTIALS chứa nguyên JSON
#    (c) File serviceAccountKey.json cùng thư mục (chạy local)
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
        "Không tìm thấy Firebase credentials ở bất kỳ đâu.\n"
        "Trên Render: vào Environment -> Secret Files -> thêm file 'firebase.json' "
        "(sẽ tự mount vào /etc/secrets/firebase.json), "
        "hoặc thêm biến môi trường FIREBASE_CREDENTIALS chứa nội dung JSON của key.\n"
        "Chạy local: đặt file serviceAccountKey.json cùng thư mục với script này."
    )

firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://webtrade-85ca8-default-rtdb.asia-southeast1.firebasedatabase.app'
})

ref = db.reference('signals')

# Danh sách Top Coin thanh khoản cao
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
        # Ép kiểu dữ liệu số
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

# ------------------------------------------------------------------
# 2. BỘ PHÂN TÍCH MÔ HÌNH NẾN & CHỈ BÁO NÂNG CAO
# ------------------------------------------------------------------
def analyze_advanced_setup(df_h1, df_m15):
    """
    Hàm phân tích thuật toán nâng cao: H1 EMA + M15 MACD Cross + RSI + Candle Pattern
    """
    # 1. TÍNH CHỈ BÁO H1
    df_h1['EMA_50'] = ta.ema(df_h1['close'], length=50)

    # 2. TÍNH CHỈ BÁO M15
    df_m15['RSI_14'] = ta.rsi(df_m15['close'], length=14)
    macd = ta.macd(df_m15['close'], fast=12, slow=26, signal=9)
    df_m15['MACD'] = macd['MACD_12_26_9']
    df_m15['MACD_SIGNAL'] = macd['MACDs_12_26_9']

    # Lấy dữ liệu 2 cây nến gần nhất (Nến vừa đóng cửa [-2] và Nến trước đó [-3])
    curr_close = df_m15['close'].iloc[-2]
    curr_open = df_m15['open'].iloc[-2]
    curr_high = df_m15['high'].iloc[-2]
    curr_low = df_m15['low'].iloc[-2]

    prev_close = df_m15['close'].iloc[-3]
    prev_open = df_m15['open'].iloc[-3]

    # Kiểm tra Mô hình Nến Nhấn Chìm Tăng (Bullish Engulfing)
    is_bullish_engulfing = (prev_close < prev_open) and (curr_close > curr_open) and (curr_close > prev_open) and (curr_open < prev_close)

    # Kiểm tra Mô hình Nến Nhấn Chìm Giảm (Bearish Engulfing)
    is_bearish_engulfing = (prev_close > prev_open) and (curr_close < curr_open) and (curr_close < prev_open) and (curr_open > prev_close)

    # Lấy giá trị MACD & RSI mới nhất
    h1_ema50 = df_h1['EMA_50'].iloc[-1]
    m15_rsi = df_m15['RSI_14'].iloc[-2]

    macd_curr = df_m15['MACD'].iloc[-2]
    macd_sig_curr = df_m15['MACD_SIGNAL'].iloc[-2]
    macd_prev = df_m15['MACD'].iloc[-3]
    macd_sig_prev = df_m15['MACD_SIGNAL'].iloc[-3]

    # Kiểm tra Giao cắt MACD
    macd_bullish_cross = (macd_prev < macd_sig_prev) and (macd_curr > macd_sig_curr)  # MACD cắt lên
    macd_bearish_cross = (macd_prev > macd_sig_prev) and (macd_curr < macd_sig_curr)  # MACD cắt xuống

    # 3. LOGIC ĐIỀU KIỆN LỆNH
    signal_type = None
    reasons = []

    # KỊCH BẢN BUY (LONG)
    if curr_close > h1_ema50:  # Xu hướng H1 Tăng
        if m15_rsi < 40 and (macd_bullish_cross or is_bullish_engulfing):
            signal_type = "BUY (LONG)"
            reasons.append("H1 Uptrend (Giá > EMA50)")
            if m15_rsi < 40: reasons.append(f"M15 RSI Thấp ({round(m15_rsi,1)})")
            if macd_bullish_cross: reasons.append("MACD M15 Cắt Lên")
            if is_bullish_engulfing: reasons.append("Nến Bullish Engulfing")

    # KỊCH BẢN SELL (SHORT)
    elif curr_close < h1_ema50:  # Xu hướng H1 Giảm
        if m15_rsi > 60 and (macd_bearish_cross or is_bearish_engulfing):
            signal_type = "SELL (SHORT)"
            reasons.append("H1 Downtrend (Giá < EMA50)")
            if m15_rsi > 60: reasons.append(f"M15 RSI Cao ({round(m15_rsi,1)})")
            if macd_bearish_cross: reasons.append("MACD M15 Cắt Xuống")
            if is_bearish_engulfing: reasons.append("Nến Bearish Engulfing")

    return signal_type, " + ".join(reasons), curr_close, m15_rsi

# ------------------------------------------------------------------
# 2b. MINI WEB SERVER (chỉ để Render Web Service nhận diện có port mở)
# ------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def health_check():
    return {"status": "ok", "service": "autoscreener bot đang chạy"}

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

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
                # Tính Stop Loss & Take Profit chuẩn R:R = 1:2
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

    # Chạy web server tối thiểu ở thread riêng để Render nhận diện có port mở
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
