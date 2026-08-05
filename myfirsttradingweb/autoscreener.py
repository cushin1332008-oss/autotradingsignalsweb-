import time
import requests
import pandas as pd
from datetime import datetime
from indicators import apply_all_indicators

WEBHOOK_URL = "http://127.0.0.1:5000/api/webhook"

def get_top_binance_symbols(limit=100):
    """Tự động lấy Top symbol có volume 24h lớn nhất trên Binance Futures realtime"""
    try:
        print("🔄 Đang đồng bộ danh sách Top 100 Coin có Volume lớn nhất từ Binance Futures...")
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            usdt_pairs = [item for item in data if item['symbol'].endswith('USDT')]
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)
            top_symbols = [item['symbol'] for item in sorted_pairs[:limit]]
            print(f"✅ Đã tải thành công {len(top_symbols)} mã coin dẫn đầu dòng tiền!")
            return top_symbols
    except Exception as e:
        print(f"⚠️ Lỗi kết nối lấy danh sách coin từ Binance: {e}")
    
    # Danh sách dự phòng nếu mất kết nối mạng
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# Lấy tự động Top 100 Coin
SYMBOLS = get_top_binance_symbols(100)

# Đa khung thời gian quét (M5, M15, H1, H4)
TIMEFRAMES = ["5m", "15m", "1h", "4h"]

COOLDOWN_TRACKER = {}
COOLDOWN_SECONDS = 600  # Chống spam tín hiệu lặp lại trong 10 phút

def get_klines(symbol, timeframe="15m", limit=200):
    """Lấy dữ liệu nến Binance Futures"""
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
        pass
    return None

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"

def analyze_and_screen():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Cu Shin Bot đang quét Top 100 Coin & Đa Khung (M5, M15, H1, H4)...")
    
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            df = get_klines(symbol, timeframe=tf, limit=200)
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

            # Điều kiện Volume đột biến (> 1.4 lần trung bình)
            is_volume_valid = curr_vol > (avg_vol * 1.4)
            position = None

            # Chiến lược Lọc Chuẩn Xác: Xu hướng EMA200 kết hợp RSI Quá Mua/Quá Bán
            if last_price > ema200 and last_rsi < 36 and is_volume_valid:
                position = "LONG"
            elif last_price < ema200 and last_rsi > 64 and is_volume_valid:
                position = "SHORT"

            if position:
                key = f"{symbol}_{tf}"
                now_ts = time.time()
                if key in COOLDOWN_TRACKER and (now_ts - COOLDOWN_TRACKER[key]) < COOLDOWN_SECONDS:
                    continue

                # Tối ưu hóa Entry phân bổ DCA (Entry 1: 40% vốn, Entry 2 DCA: 60% vốn)
                if position == "LONG":
                    entry1 = last_price
                    entry2 = last_price * 0.992  # DCA rải sâu 0.8%
                    sl = last_price * 0.985      # Stop Loss chặt chẽ -1.5%
                    tp = last_price * 1.035      # Take Profit mục tiêu +3.5%
                    leverage = "50x - 500x"
                else:
                    entry1 = last_price
                    entry2 = last_price * 1.008  # DCA rải cao 0.8%
                    sl = last_price * 1.015      # Stop Loss chặt chẽ +1.5%
                    tp = last_price * 0.965      # Take Profit mục tiêu -3.5%
                    leverage = "50x - 500x"

                payload = {
                    "symbol": symbol,
                    "tf": tf.upper(),
                    "position": position,
                    "entry1": format_price(entry1),
                    "entry2": format_price(entry2),
                    "tp": format_price(tp),
                    "sl": format_price(sl),
                    "leverage": leverage,
                    "risk": "Chia Vol 40/60"
                }

                try:
                    res = requests.post(WEBHOOK_URL, json=payload, timeout=5)
                    if res.status_code == 200:
                        print(f"🔥 [SIGNAL] #{symbol} [{tf.upper()}] | {position} | Giá: {format_price(last_price)} | RSI: {last_rsi:.1f}")
                        COOLDOWN_TRACKER[key] = now_ts
                except Exception as e:
                    pass

def run_screener():
    print("🚀 Cu Shin Pro Signals Bot Engine (Top 100 Realtime) đã kích hoạt thành công...")
    while True:
        try:
            analyze_and_screen()
            time.sleep(15)  # Quét liên tục quy mô lớn mỗi 15 giây
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    run_screener()
