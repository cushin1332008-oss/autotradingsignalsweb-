import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import pandas as pd
import pandas_ta as ta
import time

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN
# ------------------------------------------------------------------
firebase_config_dict = {
  "type": "service_account",
  "project_id": "webtrade-85ca8",
  "private_key_id": "e352ab30b941661085686fd608e9148b3fe81c81",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCegD/1D7Iul7BU\nAdYJGwd6QAHlZLXa7R7mdLfHFJCg3o22Hqc+PJ7s4ZhRILG3V88JJ+akVuzfZvG3\n3+v52VAwhCK61TwbIzMB5ZQCisEj1VKLBJSaFZnQDgAGtZ7OIG7WG3Btt0N+lW4P\nPEGy7hduhsJm5CG38gI/iv3tF6id732h5i+jX/Fa74/2o1OqwXKNh916TvMV2jxJ\nFk4q74IzTInHcRmHR/DoO5QkiU51s5Q3MLCfllryS/l21LYSwLg5vWGX+H/xGJrQ\nH1Po2TPZ9JExdOxQBFXruD2qOPxx2kV73SJh6LzSXocZu30dekM9CwhkixYRferW\n0HZI5BLzAgMBAAECggEABjGazjfDzcBNuqqrs4Vj4GoZ6N3roVd8yqKq/9OU50Rr\nIz/FZ1A1IaqbKiht6W08AO6XO7rN3NkH/xh3/zZ3xL2VIdntVF4mwx82jnbfn0fZ\nxubx66eGcDPr2ldEkmeADUvbM95ie9LZDy1an+Rf9Ai+Fgk6LBb/8X27+IThKPLA\nJQjmK5X69udRXbzNyfnK1bbVdI8CAywwj473ujMzyybIj048SVwDmHB2tt07BSvY\n0knNPT80NKj/ZWP1p82afTlhYZkMeI/Kq5EWhd0FWCb2aPGssYEcTEkU3PNc660t\nVVxIZVYOKvFjcy0E2uvy8Vj62mif1Lkc6pLnNYkWoQKBgQDPdBY9vAwyKAH2Ts6Y\ngOCte/BilLB5aH6yOZXDOSfR1aMYvKYn0QbwxDagc8YkSNLa0vs5Ytd5oqegdO/g\nNyPPzoruucSDmiSl1Y8Nfdu5S+OcebihZ+EdMW0TznCy7acN32ceivnTwwakAmsq\nVpP9qrSHYHSg1eVzA0gSouGDUQKBgQDDl5EMi3KuBGsGNSilS06LvY7EOqO3VcWG\nSYbPzQBeEAjVS0m8Rfe70nH+dBdxgdugfNZADdHT1HhCYJ8O2/ykKaK+imSPUjqB\nlobeqc+tBJbY8BrkVDcIm14kKFRx/yRsCXTwldBFn7s1gKAwZXUHkPI5Gu5ZgkYJ\nTQDdKDq5AwKBgEYQWOqktiHCbVc4qoHLFRbCgx9oRGncpt2eoTv787zkwF68aAmO\niR+LxT9Pmp3qknwhQYPSJCAKlT6V/+Xj+Y5XnYie6QXha3sus0/FMA5W2Rqh6X9p\nzBfF96b21A06Qm9nAjbIjTO97GI8BuGXuAe2PZ5zLzCazRGZDCBvLmbhAoGAVs2E\nLPoSKhKB4N5krH7wW+oDWyjfEXU6VS96aeyD9jrNgMOJ9MlkeXGa759b7B8CdoYQ\nm5rGfWk0+dhhnrmYtM5ZkJBgso5+spY4QsdACHwZ6isc9Co/xk0ViZxwZasi4eOM\nh10lclDCR6tO7EuKlZIJPbirAQRkyqnm8T9yWDsCgYB40KNENP1Zl0MREV+LLXaS\nHqYL+GNwYYds6rmOXOEOLhAZUDIhLBJzzmAYeAnWLZtHsQbtSeF10mWVRgbBkkSm\nuSHDZmDx0xaozZJdGFZ0WSJCU8fLtAmx80Vx3UCAMfK27k6Wn64ePvsmT+nHQAI5\nia1koyLL6xdVaBKE5NjHTA==\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@webtrade-85ca8.iam.gserviceaccount.com",
  "client_id": "102991661149337777004",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40webtrade-85ca8.iam.gserviceaccount.com"
}

cred = credentials.Certificate(firebase_config_dict)
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
    macd_bullish_cross = (macd_prev < macd_sig_prev) and (macd_curr > macd_sig_curr) # MACD cắt lên
    macd_bearish_cross = (macd_prev > macd_sig_prev) and (macd_curr < macd_sig_curr) # MACD cắt xuống

    # 3. LOGIC ĐIỀU KIỆN LỆNH
    signal_type = None
    reasons = []

    # KỊCH BẢN BUY (LONG)
    if curr_close > h1_ema50: # Xu hướng H1 Tăng
        if m15_rsi < 40 and (macd_bullish_cross or is_bullish_engulfing):
            signal_type = "BUY (LONG)"
            reasons.append("H1 Uptrend (Giá > EMA50)")
            if m15_rsi < 40: reasons.append(f"M15 RSI Thấp ({round(m15_rsi,1)})")
            if macd_bullish_cross: reasons.append("MACD M15 Cắt Lên")
            if is_bullish_engulfing: reasons.append("Nến Bullish Engulfing")

    # KỊCH BẢN SELL (SHORT)
    elif curr_close < h1_ema50: # Xu hướng H1 Giảm
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
    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()