import time
import requests
import pandas as pd
from datetime import datetime

WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 300

def get_klines(symbol, timeframe="15m", limit=50):
    """Lấy dữ liệu nến thực tế từ Binance Futures API"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=[
                'time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            return df
    except Exception as e:
        print(f"Lỗi lấy dữ liệu nến {symbol}: {e}")
    return None

def calculate_rsi(df, period=14):
    """Tính chỉ báo Kỹ thuật RSI chuẩn"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def analyze_and_screen():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Đang quét phân tích kỹ thuật trên Binance Futures...")
    
    for symbol in SYMBOLS:
        df = get_klines(symbol, timeframe="15m")
        if df is None or len(df) < 20:
            continue

        rsi_series = calculate_rsi(df)
        last_rsi = rsi_series.iloc[-1]
        last_price = df['close'].iloc[-1]

        # Thuật toán kích hoạt tín hiệu Quantitative:
        # Tín hiệu LONG khi RSI < 35 (Vùng Quá Bán)
        # Tín hiệu SHORT khi RSI > 65 (Vùng Quá Mua)
        position = None
        if last_rsi < 35:
            position = "LONG"
        elif last_rsi > 65:
            position = "SHORT"

        if position:
            key = f"{symbol}_M15"
            now_ts = time.time()
            if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
                continue

            if position == "LONG":
                entry1 = last_price
                entry2 = last_price * 0.992
                tp = last_price * 1.025
                sl = last_price * 0.988
                leverage = "20x"
                risk = "1.5%"
            else:
                entry1 = last_price
                entry2 = last_price * 1.008
                tp = last_price * 0.975
                sl = last_price * 1.012
                leverage = "15x"
                risk = "2.0%"

            payload = {
                "symbol": symbol,
                "tf": "M15",
                "position": position,
                "entry1": format_price(entry1),
                "entry2": format_price(entry2),
                "tp": format_price(tp),
                "sl": format_price(sl),
                "leverage": leverage,
                "risk": risk,
                "status": "ACTIVE"
            }

            try:
                res = requests.post(WEBHOOK_URL, json=payload, timeout=5)
                if res.status_code == 200:
                    print(f"✅ [SIGNAL GENERATED] {symbol} | {position} | RSI: {last_rsi:.1f} | Giá: {format_price(last_price)}")
                    COOLDOWN_TRACKER[key] = now_ts
            except Exception as e:
                print(f"Lỗi gửi Webhook: {e}")

def run_screener():
    print("🚀 Quantitative Auto-Screener Engine 2026 đang chạy...")
    while True:
        try:
            analyze_and_screen()
            time.sleep(20)
        except Exception as e:
            print(f"Lỗi vòng lặp Screener: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener()
