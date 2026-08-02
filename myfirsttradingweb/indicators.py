"""
indicators.py
-------------
Module dùng chung cho phân tích kỹ thuật + sinh tín hiệu theo 3 "khung giao dịch"
(profile) riêng biệt: SCALP (M15), SWING (H1), POSITION (H4).
Tích hợp ATR (Average True Range) để Stop Loss co giãn theo biến động thực tế của coin,
và tính đòn bẩy đề xuất cụ thể dựa trên RISK% CỐ ĐỊNH do người dùng chọn (không tự giảm
theo độ mạnh tín hiệu), phù hợp với người giao dịch chấp nhận rủi ro cao hơn.
"""

import os
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

# Tỷ lệ Risk:Reward — quyết định TP cách entry bao xa so với SL.
# Mặc định 2.0 (rủi ro 1 ăn 2), có thể chỉnh qua biến môi trường RR_RATIO trên Render.
RR_RATIO = float(os.environ.get("RR_RATIO", "2.0"))

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
# PHÂN TÍCH 1 KHUNG THỜI GIAN (có tính ATR)
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
# SINH TÍN HIỆU CHO 1 PROFILE CỤ THỂ (dùng ATR để tối ưu SL)
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

    # Tính SL theo biến động (ATR) kết hợp Hỗ trợ/Kháng cự, TP theo tỷ lệ RR_RATIO cấu hình được
    if "BUY" in signal_type:
        sl = entry["support"] - (1.0 * atr)
        if sl >= price:
            sl = price - (1.5 * atr)
        tp = price + (price - sl) * RR_RATIO
    else:
        sl = entry["resistance"] + (1.0 * atr)
        if sl <= price:
            sl = price + (1.5 * atr)
        tp = price - (sl - price) * RR_RATIO

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
# QUẢN LÝ VỐN: RISK% CỐ ĐỊNH (theo lựa chọn của bạn) + MARGIN & ĐÒN BẨY ĐỀ XUẤT
# ------------------------------------------------------------------
# Khác với bản trước (tự giảm risk khi tín hiệu yếu), giờ risk_percent CỐ ĐỊNH theo
# đúng mức bạn chấp nhận (mặc định 1.5%, giữa khoảng 1-2% bạn nói) cho MỌI tín hiệu,
# không phân biệt mạnh/yếu. Độ mạnh tín hiệu (confluence_pct) giờ chỉ dùng để hiển thị
# "độ tin cậy" tham khảo, KHÔNG còn tự động thu hẹp risk nữa.
#
# LƯU Ý QUAN TRỌNG: vì risk% giữ cố định bất kể tín hiệu mạnh/yếu, những tín hiệu có
# khoảng cách entry→SL hẹp (do ATR thấp) sẽ cần ĐÒN BẨY CAO HƠN mới đạt đúng risk% đó.
# Đòn bẩy càng cao, biên độ "wick" chịu được trước khi bị thanh lý càng nhỏ — đây là rủi ro
# thật ngoài con số % risk trên lý thuyết, không phải rủi ro có thể loại bỏ bằng công thức.
RISK_PERCENT_DEFAULT = float(os.environ.get("RISK_PERCENT", "1.5"))       # % tài khoản risk mỗi lệnh
MARGIN_PCT_TARGET_DEFAULT = float(os.environ.get("MARGIN_PCT_TARGET", "8.0"))  # % tài khoản dùng làm ký quỹ

# Khung đòn bẩy riêng theo từng khung giao dịch (timeframe) — khung nhỏ (M15) có SL
# co giãn theo ATR hẹp hơn nên tự nhiên cần đòn bẩy cao hơn mới đạt đúng risk_percent;
# khung lớn (H4) có SL rộng hơn nên cần đòn bẩy thấp hơn dù risk% giữ nguyên.
# Chỉnh trực tiếp các số này nếu muốn khung khác (VD: BingX giới hạn theo từng cặp coin,
# tự sàn sẽ cắt xuống mức cho phép nếu bot đề xuất vượt mức, không lỗi gì cả).
LEVERAGE_RANGE_BY_PROFILE = {
    "SCALP":    (50, 200),   # M15 — biến động ngắn hạn, SL hẹp
    "SWING":    (30, 125),   # H1
    "POSITION": (20, 75),    # H4 — biến động rộng hơn, SL xa hơn
}
DEFAULT_LEVERAGE_RANGE = (20, 100)

# Số dư tài khoản THỰC (USDT) — khai báo để bot tính ra số tiền ký quỹ cụ thể (USDT) và
# tự nâng đòn bẩy khi cần để đạt khối lượng lệnh tối thiểu sàn yêu cầu với vốn nhỏ.
# Để 0 nếu chỉ muốn tính theo %, không cần số tiền cụ thể.
ACCOUNT_BALANCE_USDT = float(os.environ.get("ACCOUNT_BALANCE_USDT", "0"))
# Khối lượng lệnh tối thiểu (USDT) sàn yêu cầu — BingX thường ~2-5 USDT tùy cặp,
# để giá trị an toàn hơn (5) làm mặc định, bạn có thể chỉnh theo cặp mình hay đánh.
MIN_NOTIONAL_USDT = float(os.environ.get("MIN_NOTIONAL_USDT", "5.0"))

LEVERAGE_STEPS = [1, 2, 3, 5, 10, 15, 20, 25, 30, 50, 75, 100, 125, 150, 200]  # mức đòn bẩy phổ biến trên sàn

def classify_confidence(confluence_pct):
    """Chỉ dùng để HIỂN THỊ độ tin cậy tín hiệu — KHÔNG còn dùng để tự giảm risk%."""
    if confluence_pct >= 85:
        return "Tin cậy cao"
    if confluence_pct >= 70:
        return "Tin cậy trung bình"
    return "Tin cậy thấp"

def snap_leverage(raw_leverage):
    """Làm tròn lên mức đòn bẩy phổ biến gần nhất mà sàn thường hỗ trợ (5x, 10x, 20x...)."""
    for step in LEVERAGE_STEPS:
        if raw_leverage <= step:
            return step
    return LEVERAGE_STEPS[-1]

def calc_position_sizing(entry, stop_loss, confluence_pct, profile_key,
                          risk_percent=None, margin_pct_target=None, account_balance=None):
    """
    Trả về dict:
    - confidence_level: nhãn độ tin cậy tín hiệu (chỉ để hiển thị)
    - risk_percent, margin_pct: % tài khoản
    - leverage: đòn bẩy đề xuất, đã kẹp trong khung riêng của profile (VD SCALP: 50-200x)
    - leverage_capped: True nếu công thức ra leverage CAO HƠN trần của profile (đã kẹp xuống
      trần — risk thực tế khi đó sẽ CAO HƠN risk_percent bạn chọn, vì không đủ đòn bẩy để
      đạt đúng risk% mong muốn với margin đã định — cân nhắc kỹ trước khi vào lệnh này)
    - margin_usdt, notional_usdt: số tiền cụ thể (USDT) NẾU bạn khai báo ACCOUNT_BALANCE_USDT,
      None nếu không khai báo
    - min_notional_adjusted: True nếu đòn bẩy đã được nâng lên để đạt khối lượng lệnh tối thiểu
      sàn yêu cầu (áp dụng khi vốn nhỏ khiến margin quá ít USDT)
    """
    risk_percent = risk_percent if risk_percent is not None else RISK_PERCENT_DEFAULT
    margin_pct = margin_pct_target if margin_pct_target is not None else MARGIN_PCT_TARGET_DEFAULT
    account_balance = account_balance if account_balance is not None else ACCOUNT_BALANCE_USDT
    confidence_label = classify_confidence(confluence_pct)
    min_lev, max_lev = LEVERAGE_RANGE_BY_PROFILE.get(profile_key, DEFAULT_LEVERAGE_RANGE)

    sl_distance_pct = abs(entry - stop_loss) / entry * 100
    if sl_distance_pct <= 0:
        return {
            "confidence_level": confidence_label, "risk_percent": risk_percent,
            "margin_pct": margin_pct, "leverage": min_lev, "leverage_capped": False,
            "margin_usdt": None, "notional_usdt": None, "min_notional_adjusted": False,
        }

    # % tài khoản cần "phơi nhiễm" (notional) để đúng risk_percent nếu không dùng đòn bẩy (1x)
    notional_pct = risk_percent / sl_distance_pct * 100
    raw_leverage = notional_pct / margin_pct if margin_pct > 0 else min_lev

    leverage = snap_leverage(raw_leverage)
    leverage_capped = raw_leverage > max_lev
    leverage = max(min_lev, min(leverage, max_lev))  # kẹp trong khung riêng của profile

    margin_usdt = None
    notional_usdt = None
    min_notional_adjusted = False

    # Nếu có khai báo vốn thực, kiểm tra xem margin quy ra USDT có đủ khối lượng lệnh tối thiểu
    # sàn yêu cầu không — vốn nhỏ thường cần đòn bẩy cao hơn mới mở được lệnh hợp lệ.
    if account_balance and account_balance > 0:
        margin_usdt = round(account_balance * margin_pct / 100, 2)
        notional_usdt = round(margin_usdt * leverage, 2)
        if margin_usdt > 0 and notional_usdt < MIN_NOTIONAL_USDT:
            needed_leverage = MIN_NOTIONAL_USDT / margin_usdt
            adjusted = snap_leverage(needed_leverage)
            adjusted = min(adjusted, max_lev)
            if adjusted > leverage:
                leverage = adjusted
                min_notional_adjusted = True
            notional_usdt = round(margin_usdt * leverage, 2)

    return {
        "confidence_level": confidence_label,
        "risk_percent": risk_percent,
        "margin_pct": round(margin_pct, 2),
        "leverage": leverage,
        "leverage_capped": leverage_capped,
        "margin_usdt": margin_usdt,
        "notional_usdt": notional_usdt,
        "min_notional_adjusted": min_notional_adjusted,
    }
