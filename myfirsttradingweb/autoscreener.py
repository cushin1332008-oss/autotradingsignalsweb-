import time
import requests
from datetime import datetime

# URL Webhook Flask App trên Render (hoặc localhost)
WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook" 
# LƯU Ý: Nếu chạy trực tiếp trên Render chung 1 app, bạn dùng "http://127.0.0.1:5000/api/webhook"
# Hoặc truyền URL Render của bạn: "https://autotradingsignalsweb.onrender.com/api/webhook"

# Danh sách các cặp Coin quét realtime
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

# Lưu thời gian gửi tín hiệu gần nhất để tránh spam
COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 300  # 5 phút mới phát lại tín hiệu cùng cặp coin

def get_binance_futures_price(symbol):
    """Lấy giá Futures realtime từ API Binance"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return float(res.json()['price'])
    except Exception as e:
        print(f"Lỗi lấy giá Binance cho {symbol}: {e}")
    return None

def format_price(price):
    """Định dạng số thập phân đẹp theo độ lớn của giá"""
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def generate_and_send_signal(symbol, position_type="LONG", timeframe="M15"):
    """Tạo tín hiệu chuẩn định dạng và gửi về Webhook"""
    price = get_binance_futures_price(symbol)
    if not price:
        return

    # Kiểm tra Cooldown
    key = f"{symbol}_{timeframe}"
    now_ts = time.time()
    if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
        return  # Đã gửi gần đây, bỏ qua

    # Tính toán thông số kỹ thuật dựa theo vị thế
    if position_type == "LONG":
        entry1 = price
        entry2 = price * 0.992  # DCA 2 thấp hơn 0.8%
        tp = price * 1.025      # Take Profit cao hơn 2.5%
        sl = price * 0.988      # Stop Loss thấp hơn 1.2%
        leverage = "20x"
        risk = "1.5%"
    else:  # SHORT
        entry1 = price
        entry2 = price * 1.008  # DCA 2 cao hơn 0.8%
        tp = price * 0.975      # Take Profit thấp hơn 2.5%
        sl = price * 1.012      # Stop Loss cao hơn 1.2%
        leverage = "15x"
        risk = "2.0%"

    # Struct Payload chuẩn hóa với Backend Pro
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
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Đã gửi tín hiệu {symbol} ({position_type}) | Giá hiện tại: {format_price(price)}")
            COOLDOWN_TRACKER[key] = now_ts
        else:
            print(f"❌ Gửi tín hiệu thất bại: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối Webhook: {e}")

def run_screener():
    """Vòng lặp quét thị trường liên tục"""
    print("🚀 Auto-Screener Engine đã khởi động...")
    import random

    while True:
        try:
            # Chọn ngẫu nhiên cặp coin và vị thế giả định thuật toán vừa kích hoạt
            symbol = random.choice(SYMBOLS)
            position = random.choice(["LONG", "SHORT"])
            tf = random.choice(["M15", "H1", "H4"])

            generate_and_send_signal(symbol, position, tf)

            # Nghỉ 15-30 giây trước khi quét vòng tiếp theo
            time.sleep(20)
        except Exception as e:
            print(f"Lỗi vòng lặp Screener: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_screener()
