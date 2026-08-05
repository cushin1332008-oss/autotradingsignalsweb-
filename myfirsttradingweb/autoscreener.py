import time
import random
import requests
from datetime import datetime

# Webhook Endpoint (Thay bằng URL thật trên Render nếu chạy độc lập)
WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 300  # 5 phút Cooldown cho mỗi cặp coin

def get_binance_futures_price(symbol):
    """Lấy giá Futures Realtime trực tiếp từ API Binance"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return float(res.json()['price'])
    except Exception as e:
        print(f"Lỗi lấy giá Binance cho {symbol}: {e}")
    return None

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def generate_and_send_signal(symbol, position_type="LONG", timeframe="M15"):
    price = get_binance_futures_price(symbol)
    if not price:
        return

    key = f"{symbol}_{timeframe}"
    now_ts = time.time()
    if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
        return

    if position_type == "LONG":
        entry1 = price
        entry2 = price * 0.992
        tp = price * 1.025
        sl = price * 0.988
        leverage = "20x"
        risk = "1.5%"
    else:
        entry1 = price
        entry2 = price * 1.008
        tp = price * 0.975
        sl = price * 1.012
        leverage = "15x"
        risk = "2.0%"

    payload = {
        "symbol": symbol,
        "tf": timeframe,
        "position": position_type,
        "entry1": format_price(entry1),
        "entry2": format_price(entry2),
        "tp": format_price(tp),
        "sl": format_price(sl),
        "leverage": leverage,
        "risk": risk,
        "status": "ACTIVE",
        "time": datetime.now().strftime("%H:%M:%S")
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Đã phát tín hiệu {symbol} ({position_type}) | Giá: {format_price(price)}")
            COOLDOWN_TRACKER[key] = now_ts
        else:
            print(f"❌ Thất bại: {response.status_code}")
    except Exception as e:
        print(f"❌ Lỗi Webhook: {e}")

def run_screener():
    print("🚀 Auto-Screener Engine đã kích hoạt...")
    while True:
        try:
            symbol = random.choice(SYMBOLS)
            position = random.choice(["LONG", "SHORT"])
            tf = random.choice(["M15", "H1", "H4"])

            generate_and_send_signal(symbol, position, tf)
            time.sleep(15)
        except Exception as e:
            print(f"Lỗi vòng lặp: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener()
