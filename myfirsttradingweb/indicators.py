"""
indicators.py
-------------
Module dùng chung cho phân tích kỹ thuật + sinh tín hiệu theo 3 "khung giao dịch"
(profile) riêng biệt: SCALP (M15), SWING (H1), POSITION (H4). 
Đã tích hợp ATR (Average True Range) để Stop Loss co giãn theo biến động thực tế của coin.
"""

import pandas as pd
import pandas_ta as ta

# ------------------------------------------------------------------
# KHUNG THỜI GIAN DÙNG ĐỂ PHÂN TÍCH & TRỌNG SỐ (khung lớn quan trọng hơn)
# ------------------------------------------------------------------
TIMEFRAMES = {
    "M15": "15m",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1d",
}
TF_WEIGHT = {"M15": 1, "H1": 2, "H4": 3, "D1": 4}
TOTAL_WEIGHT = sum(TF_WEIGHT.values())

# ------------------------------------------------------------------
# 3 PROFILE GIAO DỊCH
# ------------------------------------------------------------------
TRADE_PROFILES = {
    "SCALP": {
        "label": "Lướt sóng (M15)",
        "entry_tf": "M15",
        "bias_tfs": ["H1", "H4"],
        "rsi_buy": 45, "rsi_sell": 55,
        "tolerance_pct": 0.5,
    },
    "SWING": {
        "label": "Trung hạn (H1)",
        "entry_tf": "H1",
        "bias_tfs": ["H4", "D1"],
        "rsi_buy": 45, "rsi_sell": 55,
        "tolerance_pct": 0.8,
    },
    "POSITION": {
        "label": "Dài hạn (H4)",
        "entry_tf": "H4",
        "bias_tfs": ["D1"],
        "rsi_buy": 45, "rsi_sell": 55,
        "tolerance_pct": 1.2,
    },
}

# ------------------------------------------------------------------
# HỖ TRỢ / KHÁNG CỰ / FIBONACCI
# ------------------------------------------------------------------
def find_support_resistance(df, lookback=50, window=3):
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
# PHÂN TÍCH 1 KHUNG THỜI GIAN (Có tính ATR)
# ------------------------------------------------------------------
def analyze_timeframe(df):
    if df is None or len(df) < 60:
        return None

    df = df.copy()
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI14'] = ta.rsi(df['close'], length=14)
    df['ATR14'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    price = df['close'].iloc[-2]
    ema20 = df['EMA20'].iloc[-2]
    ema50 = df['EMA50'].iloc[-2]
    rsi = df['RSI14'].iloc[-2]
    atr = df['ATR14'].iloc[-2]

    if pd.isna(ema50) or pd.isna(rsi) or pd.isna(atr):
        return None

    if price > ema20 > ema50:
        trend = "UP"
    elif price < ema20 < ema50:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support, resistance = find_support_resistance(df)

    return {
        "price": float(price),
        "rsi": float(rsi),
        "atr": float(atr),
        "trend": trend,
        "support": support,
        "resistance": resistance,
    }

# ------------------------------------------------------------------
# SINH TÍN HIỆU CHO 1 PROFILE CỤ THỂ (Dùng ATR để tối ưu SL)
# ------------------------------------------------------------------
def generate_signal_for_profile(tf_results, profile_key):
    profile = TRADE_PROFILES[profile_key]
    entry = tf_results.get(profile["entry_tf"])
    biases = [tf_results.get(tf) for tf in profile["bias_tfs"]]

    if not entry or any(b is None for b in biases):
        return None

    bull_bias = all(b["trend"] == "UP" for b in biases)
    bear_bias = all(b["trend"] == "DOWN" for b in biases)

    tol = profile["tolerance_pct"]
    fibs = fibonacci_levels(entry["support"], entry["resistance"])
    near_fib = nearest_fib_level(entry["price"], fibs, tolerance_pct=tol)

    signal_type = None
    reasons = []
    bias_label = " & ".join(profile["bias_tfs"])

    if bull_bias and entry["rsi"] < profile["rsi_buy"]:
        near_support = abs(entry["price"] - entry["support"]) / entry["support"] * 100 < tol * 2
        if near_fib or near_support:
            signal_type = "BUY (LONG)"
            reasons.append(f"{bias_label} cùng xu hướng Tăng")
            reasons.append(f"{profile['entry_tf']} RSI thấp ({round(entry['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {near_fib}" if near_fib else f"Giá chạm vùng hỗ trợ {profile['entry_tf']}")

    elif bear_bias and entry["rsi"] > profile["rsi_sell"]:
        near_resistance = abs(entry["price"] - entry["resistance"]) / entry["resistance"] * 100 < tol * 2
        if near_fib or near_resistance:
            signal_type = "SELL (SHORT)"
            reasons.append(f"{bias_label} cùng xu hướng Giảm")
            reasons.append(f"{profile['entry_tf']} RSI cao ({round(entry['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {near_fib}" if near_fib else f"Giá chạm vùng kháng cự {profile['entry_tf']}")

    if not signal_type:
        return None

    price = entry["price"]
    atr = entry["atr"]
    
    # Tính toán SL theo biến động (ATR) kết hợp Hỗ trợ/Kháng cự
    if "BUY" in signal_type:
        sl = entry["support"] - (1.0 * atr)  # Cách hỗ trợ 1 khoảng ATR
        if sl >= price:                      # Dự phòng lỗi nến giật
            sl = price - (1.5 * atr)
        tp = price + (price - sl) * 2
    else:
        sl = entry["resistance"] + (1.0 * atr) # Cách kháng cự 1 khoảng ATR
        if sl <= price:
            sl = price + (1.5 * atr)
        tp = price - (sl - price) * 2

    # Điểm hội tụ đa khung
    bull_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "UP")
    bear_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "DOWN")
    confluence_pct = round((bull_w if "BUY" in signal_type else bear_w) / TOTAL_WEIGHT * 100, 1)

    return {
        "profile": profile_key,
        "trade_timeframe": profile["label"],
        "entry_tf": profile["entry_tf"],
        "bias_tfs": profile["bias_tfs"],
        "signal": signal_type,
        "price": float(price),
        "entry": float(price),
        "stop_loss": round(float(sl), 6),
        "take_profit": round(float(tp), 6),
        "atr": round(float(atr), 6),
        "reason": " + ".join(reasons),
        "rsi_entry_tf": round(float(entry["rsi"]), 2),
        "confluence_pct": confluence_pct,
        "support": round(entry["support"], 6),
        "resistance": round(entry["resistance"], 6),
    }

def generate_all_signals(tf_results):
    signals = {}
    for key in TRADE_PROFILES:
        sig = generate_signal_for_profile(tf_results, key)
        if sig:
            signals[key] = sig
    return signals

# ------------------------------------------------------------------
# QUẢN LÝ VỐN: RỦI RO & KHỐI LƯỢNG (Giữ nguyên)
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
    risk_label, risk_percent = classify_risk(confluence_pct)
    sl_distance_pct = abs(entry - stop_loss) / entry * 100
    if sl_distance_pct <= 0:
        return risk_label, risk_percent, 0.0, False
    position_pct = risk_percent / sl_distance_pct * 100
    needs_leverage = position_pct > 100
    position_pct = min(position_pct, 100.0)
    return risk_label, risk_percent, round(position_pct, 2), needs_leverage
