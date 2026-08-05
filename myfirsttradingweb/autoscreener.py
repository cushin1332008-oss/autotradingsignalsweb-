import time
import requests
import pandas as pd
from datetime import datetime
from indicators import (
    TIMEFRAMES, 
    calculate_technical_indicators, 
    get_market_trend, 
    check_candlestick_patterns
)

# Cấu hình Token & ID Telegram của bạn
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"
WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", 
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "NEARUSDT"
]

def fetch_klines(symbol, interval, limit=250):
    """Lấy dữ liệu nến Futures từ Binance API"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"Lỗi tải dữ liệu {symbol} [{interval}]: {e}")
        return pd.DataFrame()

def send_telegram_alert(message):
    """Gửi thông báo Telegram formatted HTML"""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def send_to_dashboard(signal_data):
    """Gửi dữ liệu trực tiếp về Dashboard Web qua REST API"""
    try:
        requests.post(WEBHOOK_URL, json=signal_data, timeout=5)
    except Exception:
        pass

def get_btc_bias():
    """Xác định định hướng xu hướng chính từ BTC trên khung H4 & D1"""
    df_h4 = fetch_klines("BTCUSDT", TIMEFRAMES["H4"])
    df_d1 = fetch_klines("BTCUSDT", TIMEFRAMES["D1"])
    
    if df_h4.empty or df_d1.empty:
        return "NEUTRAL"

    df_h4 = calculate_technical_indicators(df_h4)
    df_d1 = calculate_technical_indicators(df_d1)

    trend_h4 = get_market_trend(df_h4)
    trend_d1 = get_market_trend(df_d1)

    if trend_h4 == "BULLISH" and trend_d1 in ["BULLISH", "SIDEWAYS"]:
        return "BULLISH"
    elif trend_h4 == "BEARISH" and trend_d1 in ["BEARISH", "SIDEWAYS"]:
        return "BEARISH"
    return "NEUTRAL"

def process_screener():
    """Hàm quét toàn bộ danh mục theo logic 3 Trade Profiles"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang tiến hành quét tín hiệu...")
    btc_bias = get_btc_bias()

    for symbol in SYMBOLS:
        for tf_key in ["M15", "H1", "H4"]:
            interval = TIMEFRAMES[tf_key]
            df = fetch_klines(symbol, interval)
            
            if df.empty or len(df) < 50:
                continue

            df = calculate_technical_indicators(df)
            last_row = df.iloc[-1]
            rsi = last_row['RSI']
            atr = last_row['ATR'] if 'ATR' in last_row else (last_row['close'] * 0.01)
            pattern = check_candlestick_patterns(df)
            curr_price = last_row['close']

            position = None

            # 1. Điều kiện vào lệnh LONG (Ưu tiên khi BTC Bullish/Neutral)
            if btc_bias != "BEARISH" and rsi < 38 and pattern in ["BULLISH_ENGULFING", "HAMMER"]:
                position = "LONG"
                entry_1 = curr_price
                entry_2 = round(curr_price - (1.2 * atr), 4)
                tp = round(curr_price + (2.5 * atr), 4)
                sl = round(entry_2 - (1.0 * atr), 4)

            # 2. Điều kiện vào lệnh SHORT (Ưu tiên khi BTC Bearish/Neutral)
            elif btc_bias != "BULLISH" and rsi > 62 and pattern in ["BEARISH_ENGULFING", "SHOOTING_STAR"]:
                position = "SHORT"
                entry_1 = curr_price
                entry_2 = round(curr_price + (1.2 * atr), 4)
                tp = round(curr_price - (2.5 * atr), 4)
                sl = round(entry_2 + (1.0 * atr), 4)

            if position:
                # Quản trị rủi ro & Đòn bẩy phân tầng theo Timeframe
                if tf_key == "M15":
                    profile, leverage, risk = "SCALP", "20x - 50x", "1.0%"
                elif tf_key == "H1":
                    profile, leverage, risk = "SWING", "10x - 20x", "2.0%"
                else:
                    profile, leverage, risk = "POSITION", "5x - 10x", "3.0%"

                now_time = datetime.now().strftime("%H:%M:%S")

                signal_payload = {
                    "symbol": symbol,
                    "tf": tf_key,
                    "profile": profile,
                    "position": position,
                    "entry1": entry_1,
                    "entry2": entry_2,
                    "tp": tp,
                    "sl": sl,
                    "leverage": leverage,
                    "risk": risk,
                    "pattern": pattern,
                    "time": now_time
                }

                # Đẩy sang Dashboard & Telegram
                send_to_dashboard(signal_payload)

                telegram_msg = (
                    f"🎯 <b>TÍN HIỆU {position} | #{symbol} ({tf_key})</b>\n"
                    f"⚙️ <b>Chiến lược:</b> {profile}\n"
                    f"🔹 <b>Nến đảo chiều:</b> {pattern}\n\n"
                    f"📍 <b>Entry DCA 1 (40%):</b> {entry_1}\n"
                    f"📍 <b>Entry DCA 2 (60%):</b> {entry_2}\n"
                    f"🎯 <b>Take Profit (TP):</b> {tp}\n"
                    f"🛑 <b>Stop Loss (SL):</b> {sl}\n\n"
                    f"⚡ <b>Đòn bẩy:</b> {leverage} | 🛡️ <b>Risk:</b> {risk}\n"
                    f"🕒 <b>Thời gian:</b> {now_time}"
                )
                send_telegram_alert(telegram_msg)
                print(f" -> Phát hiện tín hiệu: {symbol} {position} ({tf_key})")

            time.sleep(0.5)

def run_screener_loop():
    print("=== ĐÃ KÍCH HOẠT HỆ THỐNG SCREENER TỰ ĐỘNG ===")
    while True:
        try:
            process_screener()
            time.sleep(60) # Tần suất quét: 60 giây / lượt
        except Exception as err:
            print(f"Lỗi trong quá trình quét: {err}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener_loop()
