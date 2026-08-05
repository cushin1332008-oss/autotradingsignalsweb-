import time
import requests
import pandas as pd
from datetime import datetime
from indicators import apply_all_indicators

WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 900  # Cooldown 15 phút giữa các tín hiệu trùng lặp

def get_klines(symbol, timeframe="15m", limit=200):
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

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def analyze_and_screen():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Đang quét thị trường Binance Futures...")
    
    for symbol in SYMBOLS:
        df = get_klines(symbol, timeframe="15m", limit=200)
        if df is None:
            continue

        df = apply_all_indicators(df)
        if df is None:
            continue

        last_row = df.iloc[-1]
        last_price = last_row['close']
        last_rsi = last_row['rsi']
        ema200 = last_row['ema200']
        curr_vol = last_row['volume']
        avg_vol = last_row['vol_ma20']

        is_volume_valid = curr_vol > (avg_vol * 1.3)
        position = None

        if last_price > ema200 and last_rsi < 38 and is_volume_valid:
            position = "LONG"
        elif last_price < ema200 and last_rsi > 62 and is_volume_valid:
            position = "SHORT"

        if position:
            key = f"{symbol}_M15"
            now_ts = time.time()
            if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
                continue

            if position == "LONG":
                entry1 = last_price
                entry2 = last_price * 0.993
                sl = last_price * 0.988
                tp = last_price * 1.024
            else:
                entry1 = last_price
                entry2 = last_price * 1.007
                sl = last_price * 1.012
                tp = last_price * 0.976

            payload = {
                "symbol": symbol,
                "tf": "M15",
                "position": position,
                "entry1": format_price(entry1),
                "entry2": format_price(entry2),
                "tp": format_price(tp),
                "sl": format_price(sl),
                "leverage": "20x - 100x+",
                "risk": "Auto Filter",
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
    print("🚀 Auto-Screener Engine đang khởi động...")
    while True:
        try:
            analyze_and_screen()
            time.sleep(15)
        except Exception as e:
            print(f"Lỗi vòng lặp Screener: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener()
