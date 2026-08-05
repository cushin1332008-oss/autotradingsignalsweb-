import time
import requests
import pandas as pd
from datetime import datetime

# URL Webhook (Đổi tên miền nếu bạn deploy server lên mạng)
WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 900  # Cooldown 15 phút (tránh spam 1 coin nhiều lần)

def get_klines(symbol, timeframe="15m", limit=200):
    """Lấy dữ liệu nến từ Binance Futures"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=[
                'time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
    except Exception as e:
        print(f"Lỗi gọi API Binance ({symbol}): {e}")
    return None

def calculate_indicators(df):
    """Tính EMA 200, RSI 14 và Volume MA20"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()

    return df

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def analyze_and_screen():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Đang quét thị trường (Multi-Filter Pro)...")
    
    for symbol in SYMBOLS:
        df = get_klines(symbol, timeframe="15m", limit=200)
        if df is None or len(df) < 200:
            continue

        df = calculate_indicators(df)

        last_row = df.iloc[-1]
        last_price = last_row['close']
        last_rsi = last_row['rsi']
        ema200 = last_row['ema200']
        curr_vol = last_row['volume']
        avg_vol = last_row['vol_ma20']

        # Bộ lọc Volume Đột Biến (> 1.3 lần TB 20 nến)
        is_volume_valid = curr_vol > (avg_vol * 1.3)

        position = None

        # THUẬT TOÁN TÍN HIỆU:
        # LONG: Giá > EMA200 (Uptrend) + RSI < 38 + Volume tốt
        if last_price > ema200 and last_rsi < 38 and is_volume_valid:
            position = "LONG"

        # SHORT: Giá < EMA200 (Downtrend) + RSI > 62 + Volume tốt
        elif last_price < ema200 and last_rsi > 62 and is_volume_valid:
            position = "SHORT"

        if position:
            key = f"{symbol}_M15"
            now_ts = time.time()
            if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
                continue

            # DCA & Quản lý Risk (R:R = 1:2)
            if position == "LONG":
                entry1 = last_price
                entry2 = last_price * 0.993  # DCA 2 thấp hơn 0.7%
                sl = last_price * 0.988      # Stop Loss: -1.2%
                tp = last_price * 1.024      # Take Profit: +2.4% (R:R 1:2)
            else: # SHORT
                entry1 = last_price
                entry2 = last_price * 1.007  # DCA 2 cao hơn 0.7%
                sl = last_price * 1.012      # Stop Loss: +1.2%
                tp = last_price * 0.976      # Take Profit: -2.4% (R:R 1:2)

            payload = {
                "symbol": symbol,
                "tf": "M15",
                "position": position,
                "entry1": format_price(entry1),
                "entry2": format_price(entry2),
                "tp": format_price(tp),
                "sl": format_price(sl),
                "leverage": "20x - 100x+",
                "risk": "Tùy chỉnh Vol",
                "status": "ACTIVE"
            }

            try:
                res = requests.post(WEBHOOK_URL, json=payload, timeout=5)
                if res.status_code == 200:
                    print(f"🔥 [SIGNAL] #{symbol} | {position} | Giá: {format_price(last_price)} | RSI: {last_rsi:.1f}")
                    COOLDOWN_TRACKER[key] = now_ts
            except Exception as e:
                print(f"Lỗi Webhook: {e}")

def run_screener():
    print("🚀 Auto-Screener Engine (Version Pro) đang chạy...")
    while True:
        try:
            analyze_and_screen()
            time.sleep(15) # Quét mỗi 15s
        except Exception as e:
            print(f"Lỗi vòng lặp: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener()
