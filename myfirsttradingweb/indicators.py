"""
indicators.py — Thuật toán phân tích & Quản lý vốn
--------------------------------------------------
- Lọc tín hiệu Altcoin theo Trend BTC (H4/D1)
- Entry DCA (40% Entry 1, 60% Entry 2)
- Quản lý vốn Risk cố định (1% - 3% tài khoản)
- Đòn bẩy 20x - 500x linh hoạt
"""

import os
import pandas as pd
import pandas_ta as ta

TIMEFRAMES = {
    "M15": "15m",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1d",
}
TF_WEIGHT = {"M15": 1, "H1": 2, "H4": 3, "D1": 4}
TOTAL_WEIGHT = sum(TF_WEIGHT.values())

RSI_OVERSOLD = float(os.environ.get("RSI_OVERSOLD", "38"))
RSI_OVERBOUGHT = float(os.environ.get("RSI_OVERBOUGHT", "62"))

TRADE_PROFILES = {
    "SCALP": {
        "label": "Lướt sóng chuẩn (M15)",
        "entry_tf": "M15",
        "bias_tfs": ["H1", "H4"],
        "default_leverage": 100,
    },
    "SWING": {
        "label": "Trung hạn (H1)",
        "entry_tf": "H1",
        "bias_tfs": ["H4", "D1"],
        "default_leverage": 50,
    },
    "POSITION": {
        "label": "Dài hạn (H4)",
        "entry_tf": "H4",
        "bias_tfs": ["D1"],
        "default_leverage": 20,
    },
}

def find_support_resistance(df, lookback=60, window=4):
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

def detect_reversal_candle(df):
    if len(df) < 4:
        return False, False
    c2_open, c2_close = df['open'].iloc[-2], df['close'].iloc[-2]
    c2_high, c2_low = df['high'].iloc[-2], df['low'].iloc[-2]
    c3_open, c3_close = df['open'].iloc[-3], df['close'].iloc[-3]

    bullish_engulfing = (c3_close < c3_open) and (c2_close > c2_open) and (c2_close >= c3_open) and (c2_open <= c3_close)
    bearish_engulfing = (c3_close > c3_open) and (c2_close < c2_open) and (c2_close <= c3_open) and (c2_open >= c3_close)

    body = abs(c2_close - c2_open)
    candle_range = c2_high - c2_low
    lower_wick = min(c2_open, c2_close) - c2_low
    upper_wick = c2_high - max(c2_open, c2_close)

    is_hammer = candle_range > 0 and lower_wick > body * 1.8 and upper_wick < body * 0.4
    is_shooting_star = candle_range > 0 and upper_wick > body * 1.8 and lower_wick < body * 0.4

    return (bullish_engulfing or is_hammer), (bearish_engulfing or is_shooting_star)

def analyze_timeframe(df):
    if df is None or len(df) < 60:
        return None
    df = df.copy()
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI14'] = ta.rsi(df['close'], length=14)
    df['ATR14'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    price = df['close'].iloc[-2]
    ema20, ema50 = df['EMA20'].iloc[-2], df['EMA50'].iloc[-2]
    rsi, atr = df['RSI14'].iloc[-2], df['ATR14'].iloc[-2]

    if pd.isna(ema50) or pd.isna(rsi) or pd.isna(atr):
        return None

    if price > ema20 > ema50 and (price - ema50) > 0.3 * atr:
        trend = "UP"
    elif price < ema20 < ema50 and (ema50 - price) > 0.3 * atr:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support, resistance = find_support_resistance(df)
    bull_rev, bear_rev = detect_reversal_candle(df)

    return {
        "price": float(price),
        "rsi": float(rsi),
        "atr": float(atr),
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "bullish_reversal_candle": bull_rev,
        "bearish_reversal_candle": bear_rev,
    }

def generate_signal_for_profile(tf_results, profile_key, btc_context=None, is_btc=False):
    profile = TRADE_PROFILES[profile_key]
    entry = tf_results.get(profile["entry_tf"])
    biases = [tf_results.get(tf) for tf in profile["bias_tfs"]]

    if not entry or any(b is None for b in biases):
        return None

    bull_bias = all(b["trend"] == "UP" for b in biases)
    bear_bias = all(b["trend"] == "DOWN" for b in biases)

    signal_type = None
    reasons = []

    if bull_bias and entry["rsi"] < RSI_OVERSOLD and entry.get("bullish_reversal_candle"):
        signal_type = "BUY (LONG)"
        reasons.append(f"Xu hướng bản thân TĂNG ({profile['entry_tf']})")
    elif bear_bias and entry["rsi"] > RSI_OVERBOUGHT and entry.get("bearish_reversal_candle"):
        signal_type = "SELL (SHORT)"
        reasons.append(f"Xu hướng bản thân GIẢM ({profile['entry_tf']})")

    if not signal_type:
        return None

    # Bộ lọc Trend BTC
    if not is_btc and btc_context:
        btc_main_trend = btc_context.get("H4", {}).get("trend") or btc_context.get("D1", {}).get("trend")
        if signal_type == "BUY (LONG)" and btc_main_trend != "UP":
            return None
        elif signal_type == "SELL (SHORT)" and btc_main_trend != "DOWN":
            return None
        reasons.append(f"Đồng thuận BTC Trend ({btc_main_trend})")

    price = entry["price"]
    atr = entry["atr"]

    # Entry DCA & TP/SL
    if "BUY" in signal_type:
        entry_1 = price
        entry_dca = price - (0.75 * atr)
        entry_avg = (entry_1 * 0.4) + (entry_dca * 0.6)

        sl = min(entry["support"] - (0.4 * atr), entry_dca - (1.1 * atr))
        risk_dist = abs(entry_avg - sl)

        tp1 = entry_avg + (1.0 * risk_dist)
        tp2 = entry_avg + (2.0 * risk_dist)
        tp3 = max(entry["resistance"], entry_avg + (3.0 * risk_dist))
    else:
        entry_1 = price
        entry_dca = price + (0.75 * atr)
        entry_avg = (entry_1 * 0.4) + (entry_dca * 0.6)

        sl = max(entry["resistance"] + (0.4 * atr), entry_dca + (1.1 * atr))
        risk_dist = abs(entry_avg - sl)

        tp1 = entry_avg - (1.0 * risk_dist)
        tp2 = entry_avg - (2.0 * risk_dist)
        tp3 = min(entry["support"], entry_avg - (3.0 * risk_dist))

    bull_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "UP")
    bear_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "DOWN")
    confluence_pct = round((bull_w if "BUY" in signal_type else bear_w) / TOTAL_WEIGHT * 100, 1)

    return {
        "profile": profile_key,
        "trade_timeframe": profile["label"],
        "entry_tf": profile["entry_tf"],
        "signal": signal_type,
        "price": float(price),
        "entry_1": round(float(entry_1), 6),
        "entry_dca": round(float(entry_dca), 6),
        "vol_split": "40% Entry 1 — 60% Entry DCA",
        "stop_loss": round(float(sl), 6),
        "tp1": round(float(tp1), 6),
        "tp2": round(float(tp2), 6),
        "tp3": round(float(tp3), 6),
        "rr_ratio": round(abs(tp2 - entry_avg) / risk_dist, 2),
        "reason": " + ".join(reasons),
        "confluence_pct": confluence_pct,
    }

def generate_all_signals(tf_results, btc_context=None, is_btc=False):
    signals = {}
    for key in TRADE_PROFILES:
        sig = generate_signal_for_profile(tf_results, key, btc_context=btc_context, is_btc=is_btc)
        if sig:
            signals[key] = sig
    return signals

def calc_position_sizing(entry_1, stop_loss, confluence_pct, profile_key, account_balance=1000.0, custom_leverage=None):
    if confluence_pct >= 85:
        risk_pct = 3.0
    elif confluence_pct >= 70:
        risk_pct = 2.0
    else:
        risk_pct = 1.0

    profile = TRADE_PROFILES.get(profile_key, {})
    lev = custom_leverage if custom_leverage is not None else profile.get("default_leverage", 50)
    leverage = max(20, min(int(lev), 500))

    sl_dist_pct = abs(entry_1 - stop_loss) / entry_1
    if sl_dist_pct == 0:
        return {}

    risk_usdt = account_balance * (risk_pct / 100.0)
    notional_usdt = risk_usdt / sl_dist_pct
    margin_usdt = notional_usdt / leverage
    margin_pct = (margin_usdt / account_balance) * 100.0

    return {
        "risk_pct": risk_pct,
        "risk_usdt": round(risk_usdt, 2),
        "leverage": leverage,
        "margin_usdt": round(margin_usdt, 2),
        "margin_pct": round(margin_pct, 2),
        "position_size_usdt": round(notional_usdt, 2)
    }
