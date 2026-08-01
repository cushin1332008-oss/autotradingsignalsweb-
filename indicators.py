"""
indicators.py
-------------
Module dùng chung cho toàn bộ logic phân tích kỹ thuật: trend, RSI, hỗ trợ/kháng cự,
Fibonacci, chấm điểm hội tụ đa khung, và quản lý vốn theo % rủi ro.

Được import bởi CẢ autoscreener.py (bot chạy realtime) LẪN backtest.py (kiểm tra lịch sử),
để đảm bảo backtest phản ánh đúng 100% logic mà bot thật đang chạy — tránh tình trạng
"code backtest" và "code live" lệch nhau dẫn đến kết quả backtest không có ý nghĩa.
"""

import pandas as pd
import pandas_ta as ta

# ------------------------------------------------------------------
# KHUNG THỜI GIAN & TRỌNG SỐ (khung lớn quan trọng hơn khung nhỏ)
# ------------------------------------------------------------------
TIMEFRAMES = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
}
TF_WEIGHT = {"M1": 1, "M5": 1.5, "M15": 2, "H1": 3, "H4": 4}
TOTAL_WEIGHT = sum(TF_WEIGHT.values())

# ------------------------------------------------------------------
# HỖ TRỢ / KHÁNG CỰ / FIBONACCI
# ------------------------------------------------------------------
def find_support_resistance(df, lookback=50, window=3):
    """Tìm vùng hỗ trợ/kháng cự dựa trên đỉnh/đáy cục bộ (swing high/low)."""
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = [], []
    for i in range(window, len(recent) - window):
        seg_h = recent['high'].iloc[i - window: i + window + 1]
        seg_l = recent['low'].iloc[i - window: i + window + 1]
        if recent['high'].iloc[i] == seg_h.max():
            highs.append(recent['high'].iloc[i])
        if recent['low'].iloc[i] == seg_l.min():
            lows.append(recent['low'].iloc[i])
    resistance = max(highs) if highs else recent['high'].max()
    support = min(lows) if lows else recent['low'].min()
    return float(support), float(resistance)

def fibonacci_levels(support, resistance):
    diff = resistance - support
    if diff <= 0:
        return {}
    return {
        "0.236": resistance - diff * 0.236,
        "0.382": resistance - diff * 0.382,
        "0.5":   resistance - diff * 0.5,
        "0.618": resistance - diff * 0.618,
        "0.786": resistance - diff * 0.786,
    }

def nearest_fib_level(price, fib_levels, tolerance_pct=0.5):
    for label, level in fib_levels.items():
        if level <= 0:
            continue
        diff_pct = abs(price - level) / level * 100
        if diff_pct <= tolerance_pct:
            return label
    return None

# ------------------------------------------------------------------
# PHÂN TÍCH 1 KHUNG THỜI GIAN
# ------------------------------------------------------------------
def analyze_timeframe(df):
    """
    Nhận vào DataFrame nến (cột open/high/low/close), trả về dict:
    trend, RSI, giá, hỗ trợ/kháng cự, điểm Fib gần nhất — cho khung thời gian đó.
    Dùng nến đã đóng cửa gần nhất (index -2), tránh lấy nến đang chạy dở (-1).
    """
    if df is None or len(df) < 60:
        return None

    df = df.copy()
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI14'] = ta.rsi(df['close'], length=14)

    price = df['close'].iloc[-2]
    ema20 = df['EMA20'].iloc[-2]
    ema50 = df['EMA50'].iloc[-2]
    rsi = df['RSI14'].iloc[-2]

    if pd.isna(ema50) or pd.isna(rsi):
        return None

    if price > ema20 > ema50:
        trend = "UP"
    elif price < ema20 < ema50:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support, resistance = find_support_resistance(df)
    fibs = fibonacci_levels(support, resistance)
    near_fib = nearest_fib_level(price, fibs)

    return {
        "price": float(price),
        "rsi": float(rsi),
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "near_fib": near_fib,
    }

# ------------------------------------------------------------------
# CHẤM ĐIỂM HỘI TỤ ĐA KHUNG & SINH TÍN HIỆU (LOGIC CỐT LÕI)
# ------------------------------------------------------------------
def generate_signal(tf_results):
    """
    Nhận vào dict {tf_label: analyze_timeframe_result}, trả về tín hiệu cuối cùng
    (hoặc None nếu không đủ điều kiện). Đây là "bộ não" ra quyết định — dùng chung
    cho cả bot live và backtest.
    """
    h4 = tf_results.get("H4")
    h1 = tf_results.get("H1")
    m15 = tf_results.get("M15")

    if not (h4 and h1 and m15):
        return None

    bull_weight = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "UP")
    bear_weight = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "DOWN")

    signal_type = None
    reasons = []

    if h4["trend"] == "UP" and h1["trend"] == "UP" and m15["rsi"] < 45:
        near_support = abs(m15["price"] - m15["support"]) / m15["support"] * 100 < 1.0
        if m15["near_fib"] or near_support:
            signal_type = "BUY (LONG)"
            reasons.append("H4 & H1 cùng xu hướng Tăng")
            reasons.append(f"M15 RSI thấp ({round(m15['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {m15['near_fib']}" if m15["near_fib"] else "Giá chạm vùng hỗ trợ M15")

    elif h4["trend"] == "DOWN" and h1["trend"] == "DOWN" and m15["rsi"] > 55:
        near_resistance = abs(m15["price"] - m15["resistance"]) / m15["resistance"] * 100 < 1.0
        if m15["near_fib"] or near_resistance:
            signal_type = "SELL (SHORT)"
            reasons.append("H4 & H1 cùng xu hướng Giảm")
            reasons.append(f"M15 RSI cao ({round(m15['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {m15['near_fib']}" if m15["near_fib"] else "Giá chạm vùng kháng cự M15")

    if not signal_type:
        return None

    price = m15["price"]
    if "BUY" in signal_type:
        sl = m15["support"] * 0.998
        tp = price + (price - sl) * 2
        confluence_pct = round(bull_weight / TOTAL_WEIGHT * 100, 1)
    else:
        sl = m15["resistance"] * 1.002
        tp = price - (sl - price) * 2
        confluence_pct = round(bear_weight / TOTAL_WEIGHT * 100, 1)

    return {
        "signal": signal_type,
        "price": float(price),
        "entry": float(price),
        "stop_loss": round(float(sl), 6),
        "take_profit": round(float(tp), 6),
        "reason": " + ".join(reasons),
        "rsi_m15": round(float(m15["rsi"]), 2),
        "confluence_pct": confluence_pct,
        "support": round(m15["support"], 6),
        "resistance": round(m15["resistance"], 6),
    }

# ------------------------------------------------------------------
# QUẢN LÝ VỐN: PHÂN LOẠI RỦI RO & KHỐI LƯỢNG VÀO LỆNH THEO % TÀI KHOẢN
# ------------------------------------------------------------------
RISK_TIERS = [
    (85, "Thấp", 2.0),
    (70, "Trung bình", 1.0),
    (0,  "Cao", 0.5),
]

def classify_risk(confluence_pct):
    for threshold, label, risk_percent in RISK_TIERS:
        if confluence_pct >= threshold:
            return label, risk_percent
    return "Cao", 0.5

def calc_position_sizing(entry, stop_loss, confluence_pct):
    """
    % tài khoản nên vào lệnh = risk_percent / khoảng_cách_SL(%) * 100
    (áp dụng cho spot / futures 1x, không đòn bẩy; risk_percent là % tài khoản
    chấp nhận mất nếu dính Stop Loss, dựa theo độ mạnh tín hiệu).
    """
    risk_label, risk_percent = classify_risk(confluence_pct)

    sl_distance_pct = abs(entry - stop_loss) / entry * 100
    if sl_distance_pct <= 0:
        return risk_label, risk_percent, 0.0, False

    position_pct = risk_percent / sl_distance_pct * 100
    needs_leverage = position_pct > 100
    position_pct = min(position_pct, 100.0)

    return risk_label, risk_percent, round(position_pct, 2), needs_leverage
