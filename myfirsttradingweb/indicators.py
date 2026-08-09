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

# Tỷ lệ Risk:Reward giờ LINH HOẠT thay vì cố định — nội suy giữa RR_MIN (tín hiệu yếu,
# chốt lời sớm cho chắc) và RR_MAX (tín hiệu mạnh, nhiều khung đồng thuận, để TP chạy xa hơn),
# đồng thời bị chặn lại bởi vùng hỗ trợ/kháng cự "rộng" phía trước (xem generate_signal_for_profile).
# Chỉnh qua biến môi trường RR_MIN / RR_MAX trên Render nếu muốn đổi biên độ.
# R:R mục tiêu CỐ ĐỊNH 1:2 cho mọi tín hiệu (ổn định, dễ theo dõi/đối chiếu, thay vì dao động
# theo độ tin cậy như bản trước). Chỉnh qua biến môi trường RR_TARGET nếu muốn đổi.
RR_TARGET = float(os.environ.get("RR_TARGET", "2.0"))
# Ngưỡng R:R tối thiểu để 1 tín hiệu được coi là đáng giao dịch — dưới 1:1 nghĩa là
# lời tiềm năng THẤP HƠN rủi ro, cần thắng >50% lệnh mới hòa vốn, không đáng hiện ra.
MIN_ACCEPTABLE_RR = float(os.environ.get("MIN_ACCEPTABLE_RR", "1.0"))

# ------------------------------------------------------------------
# DCA (Dollar-Cost Averaging) — thêm 1 lệnh vào thêm ở giá tốt hơn nếu giá lùi về gần SL
# nhưng cấu trúc chưa bị phá vỡ, giúp cải thiện giá vốn trung bình nếu lệnh DCA khớp.
# SL/TP giữ nguyên ở mức CẤU TRÚC GIÁ (không dời theo DCA) — chỉ giá vốn trung bình đổi.
# ------------------------------------------------------------------
DCA_ENABLED = os.environ.get("DCA_ENABLED", "true").lower() == "true"
DCA_LEVEL_PCT = float(os.environ.get("DCA_LEVEL_PCT", "0.5"))       # đặt DCA ở giữa quãng entry->SL
DCA_ENTRY1_VOL_PCT = float(os.environ.get("DCA_ENTRY1_VOL_PCT", "60"))  # % khối lượng cho entry đầu
DCA_ENTRY2_VOL_PCT = 100 - DCA_ENTRY1_VOL_PCT                            # % khối lượng còn lại cho DCA

def _capped_tp(price, risk_distance, rr_multiple, is_buy, resistance_wide, support_wide):
    """Tính 1 mức TP theo bội số R:R, chặn không vượt quá vùng cản rộng phía trước."""
    if is_buy:
        raw_tp = price + risk_distance * rr_multiple
        cap = resistance_wide * 0.9985
        return min(raw_tp, cap) if cap > price else raw_tp
    else:
        raw_tp = price - risk_distance * rr_multiple
        cap = support_wide * 1.0015
        return max(raw_tp, cap) if cap < price else raw_tp

# ------------------------------------------------------------------
# CHỐT LỜI BẬC THANG (TP1/TP2/TP3) — thay vì 1 điểm TP duy nhất, chia khối lượng ra 3 mức
# để khoá lời từng phần, giảm rủi ro "được ăn cả ngã về không" khi giá đảo chiều sau khi
# đã đi đúng hướng một đoạn. Mức TP2 = mục tiêu chính (giữ nguyên logic R:R linh hoạt cũ).
# ------------------------------------------------------------------
TP_LEVELS_ENABLED = os.environ.get("TP_LEVELS_ENABLED", "true").lower() == "true"
TP1_RR_FACTOR = float(os.environ.get("TP1_RR_FACTOR", "0.5"))   # TP1 = 50% quãng đường tới mục tiêu chính
TP3_RR_FACTOR = float(os.environ.get("TP3_RR_FACTOR", "1.5"))   # TP3 = 150% mục tiêu chính (nếu cấu trúc cho phép)
TP1_VOL_PCT = float(os.environ.get("TP1_VOL_PCT", "50"))
TP2_VOL_PCT = float(os.environ.get("TP2_VOL_PCT", "30"))
TP3_VOL_PCT = float(os.environ.get("TP3_VOL_PCT", "20"))

def dynamic_rr_ratio(confluence_pct):
    """R:R giờ CỐ ĐỊNH 1:2 cho mọi tín hiệu, không phân biệt độ tin cậy — giữ tên hàm để
    không phải sửa nơi gọi, nhưng luôn trả về RR_TARGET bất kể confluence_pct."""
    return RR_TARGET

# ------------------------------------------------------------------
# NGƯỠNG LỌC TÍN HIỆU — tăng độ chặt để giảm SL bị dính oan do bắt tín hiệu ở vùng giằng co
# ------------------------------------------------------------------
RSI_OVERSOLD = float(os.environ.get("RSI_OVERSOLD", "42"))    # nới nhẹ từ 40 -> 42 để ra tín hiệu đều hơn
RSI_OVERBOUGHT = float(os.environ.get("RSI_OVERBOUGHT", "58"))  # nới nhẹ từ 60 -> 58
SL_ATR_MULTIPLIER = float(os.environ.get("SL_ATR_MULTIPLIER", "1.4"))       # trước: 1.0 — nới SL xa hơn
SL_ATR_FALLBACK_MULTIPLIER = float(os.environ.get("SL_ATR_FALLBACK_MULTIPLIER", "1.8"))  # trước: 1.5
TREND_STRENGTH_ATR_MULT = float(os.environ.get("TREND_STRENGTH_ATR_MULT", "0.2"))  # nới từ 0.3 -> 0.2

# ------------------------------------------------------------------
# 3 PROFILE GIAO DỊCH
# ------------------------------------------------------------------
TRADE_PROFILES = {
    "SCALP": {
        "label": "Lướt sóng (M15)",
        "entry_tf": "M15",
        "bias_tfs": ["H1", "H4"],
        "tolerance_pct": 0.5,
    },
    "SWING": {
        "label": "Trung hạn (H1)",
        "entry_tf": "H1",
        "bias_tfs": ["H4", "D1"],
        "tolerance_pct": 0.8,
    },
    "POSITION": {
        "label": "Dài hạn (H4)",
        "entry_tf": "H4",
        "bias_tfs": ["D1"],
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
# NHẬN DIỆN NẾN ĐẢO CHIỀU (xác nhận thêm cho tín hiệu, không chỉ dựa vào RSI+vị trí giá)
# ------------------------------------------------------------------
REQUIRE_CANDLE_CONFIRMATION = os.environ.get("REQUIRE_CANDLE_CONFIRMATION", "false").lower() == "true"

def detect_reversal_candle(df):
    """
    Nhận diện mẫu nến đảo chiều ở nến ĐÃ ĐÓNG CỬA gần nhất (iloc[-2]):
    - Bullish/Bearish Engulfing: nến sau "nuốt trọn" thân nến trước theo chiều ngược lại
    - Hammer / Shooting Star: bấc dài gấp ~1.5 lần thân nến, xác nhận lực từ chối giá mạnh
    Trả về (bullish_reversal: bool, bearish_reversal: bool)
    """
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

    is_hammer = candle_range > 0 and lower_wick > body * 1.5 and upper_wick < body * 0.6
    is_shooting_star = candle_range > 0 and upper_wick > body * 1.5 and lower_wick < body * 0.6

    bullish_reversal = bool(bullish_engulfing or is_hammer)
    bearish_reversal = bool(bearish_engulfing or is_shooting_star)
    return bullish_reversal, bearish_reversal

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

    # Chỉ công nhận UP/DOWN nếu giá cách EMA50 đủ xa (tối thiểu TREND_STRENGTH_ATR_MULT × ATR) —
    # tránh bắt tín hiệu ở vùng giằng co/giao cắt biên, nơi giá > EMA20 > EMA50 chỉ lệch vài đồng
    # (trend "kỹ thuật" nhưng không đủ lực đẩy thật, hay gây SL bị quét lại ngay sau khi vào lệnh).
    trend_strength_ok = abs(price - ema50) > TREND_STRENGTH_ATR_MULT * atr

    if price > ema20 > ema50 and trend_strength_ok:
        trend = "UP"
    elif price < ema20 < ema50 and trend_strength_ok:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support, resistance = find_support_resistance(df, lookback=50)
    # Vùng hỗ trợ/kháng cự "rộng" hơn (nhìn xa hơn trong lịch sử) — dùng để chặn TP không
    # đặt vượt quá 1 vùng cản lớn phía trước, giữ R:R linh hoạt nhưng vẫn bám cấu trúc giá thực tế.
    support_wide, resistance_wide = find_support_resistance(df, lookback=min(150, len(df) - 5))
    bullish_reversal_candle, bearish_reversal_candle = detect_reversal_candle(df)

    return {
        "price": float(price),
        "rsi": float(rsi),
        "atr": float(atr),
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "support_wide": support_wide,
        "resistance_wide": resistance_wide,
        "bullish_reversal_candle": bullish_reversal_candle,
        "bearish_reversal_candle": bearish_reversal_candle,
    }

# ------------------------------------------------------------------
# LỌC THEO XU HƯỚNG BTC (macro filter) — không xác nhận LONG altcoin khi BTC đang giảm mạnh,
# không xác nhận SHORT altcoin khi BTC đang tăng mạnh. Phần lớn altcoin đi theo BTC, nên đi
# ngược dòng BTC dù chỉ báo riêng coin đó đẹp vẫn là giao dịch rủi ro cao hơn cần thiết.
# ------------------------------------------------------------------
BTC_FILTER_ENABLED = os.environ.get("BTC_FILTER_ENABLED", "true").lower() == "true"

def get_btc_reference_trend(btc_context, profile_key):
    """Chọn khung tham chiếu BTC phù hợp với profile: POSITION nhìn D1, còn lại nhìn H4."""
    if not btc_context:
        return None
    if profile_key == "POSITION":
        return btc_context.get("D1") or btc_context.get("H4")
    return btc_context.get("H4") or btc_context.get("D1")

# ------------------------------------------------------------------
# SINH TÍN HIỆU CHO 1 PROFILE CỤ THỂ (dùng ATR để tối ưu SL)
# ------------------------------------------------------------------
def generate_signal_for_profile(tf_results, profile_key, btc_context=None):
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

    if bull_bias and entry["rsi"] < RSI_OVERSOLD:
        near_support = abs(entry["price"] - entry["support"]) / entry["support"] * 100 < tol * 2
        candle_ok = (not REQUIRE_CANDLE_CONFIRMATION) or entry.get("bullish_reversal_candle")
        if (near_fib or near_support) and candle_ok:
            signal_type = "BUY (LONG)"
            reasons.append(f"{bias_label} cùng xu hướng Tăng")
            reasons.append(f"{profile['entry_tf']} RSI thấp ({round(entry['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {near_fib}" if near_fib else f"Giá chạm vùng hỗ trợ {profile['entry_tf']}")
            if entry.get("bullish_reversal_candle"):
                reasons.append("Nến xác nhận đảo chiều (Engulfing/Hammer)")

    elif bear_bias and entry["rsi"] > RSI_OVERBOUGHT:
        near_resistance = abs(entry["price"] - entry["resistance"]) / entry["resistance"] * 100 < tol * 2
        candle_ok = (not REQUIRE_CANDLE_CONFIRMATION) or entry.get("bearish_reversal_candle")
        if (near_fib or near_resistance) and candle_ok:
            signal_type = "SELL (SHORT)"
            reasons.append(f"{bias_label} cùng xu hướng Giảm")
            reasons.append(f"{profile['entry_tf']} RSI cao ({round(entry['rsi'], 1)})")
            reasons.append(f"Giá chạm Fib {near_fib}" if near_fib else f"Giá chạm vùng kháng cự {profile['entry_tf']}")
            if entry.get("bearish_reversal_candle"):
                reasons.append("Nến xác nhận đảo chiều (Engulfing/Shooting Star)")

    if not signal_type:
        return None

    # Lọc theo xu hướng BTC — bỏ qua tín hiệu đi ngược dòng thị trường chung (trừ chính BTCUSDT)
    if BTC_FILTER_ENABLED and btc_context:
        btc_ref = get_btc_reference_trend(btc_context, profile_key)
        if signal_type == "BUY (LONG)" and btc_ref == "DOWN":
            return None
        if signal_type == "SELL (SHORT)" and btc_ref == "UP":
            return None

    price = entry["price"]
    atr = entry["atr"]

    # Tính SL theo biến động (ATR) kết hợp Hỗ trợ/Kháng cự — nới rộng hơn (SL_ATR_MULTIPLIER)
    # để giảm khả năng bị "wick" quét dính SL trong khi xu hướng chính vẫn đúng.
    if "BUY" in signal_type:
        sl = entry["support"] - (SL_ATR_MULTIPLIER * atr)
        if sl >= price:
            sl = price - (SL_ATR_FALLBACK_MULTIPLIER * atr)
    else:
        sl = entry["resistance"] + (SL_ATR_MULTIPLIER * atr)
        if sl <= price:
            sl = price + (SL_ATR_FALLBACK_MULTIPLIER * atr)

    # Độ hội tụ đa khung — tính TRƯỚC để dùng làm cơ sở nội suy R:R linh hoạt
    bull_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "UP")
    bear_w = sum(TF_WEIGHT[tf] for tf, r in tf_results.items() if r["trend"] == "DOWN")
    confluence_pct = round((bull_w if "BUY" in signal_type else bear_w) / TOTAL_WEIGHT * 100, 1)

    # R:R mục tiêu ban đầu — nội suy theo độ tin cậy tín hiệu (KHÔNG còn cố định 1:2 nữa)
    rr_target = dynamic_rr_ratio(confluence_pct)
    risk_distance = abs(price - sl)

    is_buy = "BUY" in signal_type
    resistance_wide = entry["resistance_wide"]
    support_wide = entry["support_wide"]

    # TP2 là mục tiêu CHÍNH (giữ nguyên logic R:R linh hoạt cũ) — vẫn là "take_profit" chuẩn
    # dùng cho backtest.py để không phá vỡ tương thích ngược.
    tp = _capped_tp(price, risk_distance, rr_target, is_buy, resistance_wide, support_wide)

    # R:R THỰC TẾ sau khi đã chặn theo cấu trúc giá — có thể thấp hoặc cao hơn rr_target ban đầu
    actual_rr = round(abs(tp - price) / risk_distance, 2) if risk_distance > 0 else rr_target

    # Nếu vùng cản quá gần khiến R:R thực tế xuống dưới ngưỡng chấp nhận được,
    # kèo này coi như không đủ hấp dẫn để giao dịch — bỏ qua thay vì trả về 1 tín hiệu tệ.
    if actual_rr < MIN_ACCEPTABLE_RR:
        return None

    # TP1 (gần hơn, chốt non 1 phần) và TP3 (xa hơn, để chạy thêm nếu cấu trúc còn cho phép)
    tp_levels = None
    if TP_LEVELS_ENABLED:
        tp1 = _capped_tp(price, risk_distance, rr_target * TP1_RR_FACTOR, is_buy, resistance_wide, support_wide)
        tp3 = _capped_tp(price, risk_distance, rr_target * TP3_RR_FACTOR, is_buy, resistance_wide, support_wide)

        def _rr_of(level_price):
            return round(abs(level_price - price) / risk_distance, 2) if risk_distance > 0 else None

        tp_levels = [
            {"level": "TP1", "price": round(float(tp1), 6), "volume_pct": TP1_VOL_PCT, "rr": _rr_of(tp1)},
            {"level": "TP2", "price": round(float(tp), 6), "volume_pct": TP2_VOL_PCT, "rr": actual_rr},
            {"level": "TP3", "price": round(float(tp3), 6), "volume_pct": TP3_VOL_PCT, "rr": _rr_of(tp3)},
        ]

    # ------------------------------------------------------------------
    # DCA: đặt 1 lệnh vào thêm ở giữa quãng đường entry -> SL. SL/TP GIỮ NGUYÊN (mức cấu trúc),
    # chỉ giá vốn trung bình và R:R thực tế đổi nếu lệnh DCA khớp.
    # ------------------------------------------------------------------
    dca_fields = {"dca_enabled": False}
    if DCA_ENABLED:
        if "BUY" in signal_type:
            dca_entry = price - (price - sl) * DCA_LEVEL_PCT
        else:
            dca_entry = price + (sl - price) * DCA_LEVEL_PCT

        avg_entry = round(price * (DCA_ENTRY1_VOL_PCT / 100) + dca_entry * (DCA_ENTRY2_VOL_PCT / 100), 6)
        risk_after_dca = abs(avg_entry - sl)
        reward_after_dca = abs(tp - avg_entry)
        rr_after_dca = round(reward_after_dca / risk_after_dca, 2) if risk_after_dca > 0 else None

        dca_fields = {
            "dca_enabled": True,
            "dca_entry": round(float(dca_entry), 6),
            "entry_volume_pct": DCA_ENTRY1_VOL_PCT,
            "dca_volume_pct": DCA_ENTRY2_VOL_PCT,
            "avg_entry_if_filled": avg_entry,
            "rr_after_dca": rr_after_dca,
        }

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
        "rr_ratio": actual_rr,
        "tp_levels": tp_levels,
        **dca_fields,
        "atr": round(float(atr), 6),
        "reason": " + ".join(reasons),
        "rsi_entry_tf": round(float(entry["rsi"]), 2),
        "confluence_pct": confluence_pct,
        "support": round(entry["support"], 6),
        "resistance": round(entry["resistance"], 6),
    }

def generate_all_signals(tf_results, btc_context=None):
    signals = {}
    for key in TRADE_PROFILES:
        sig = generate_signal_for_profile(tf_results, key, btc_context=btc_context)
        if sig:
            signals[key] = sig
    return signals

# ------------------------------------------------------------------
# QUẢN LÝ VỐN: RISK% CỐ ĐỊNH (theo lựa chọn của bạn) + MARGIN & ĐÒN BẨY ĐỀ XUẤT
# ------------------------------------------------------------------
# Khác với bản trước (tự giảm risk khi tín hiệu yếu), giờ risk_percent CỐ ĐỊNH theo
# đúng mức bạn chấp nhận (mặc định 1.5%, giữa khoảng 1-2% bạn nói) cho MỌI tín hiệu,
# QUẢN LÝ VỐN: RISK% LINH HOẠT THEO ĐỘ TIN CẬY TÍN HIỆU + MARGIN & ĐÒN BẨY ĐỀ XUẤT
# ------------------------------------------------------------------
# Risk% giờ THAY ĐỔI theo độ hội tụ đa khung (confluence_pct) — tín hiệu càng nhiều khung
# đồng thuận (đáng tin hơn) thì được risk cao hơn (gần RISK_PERCENT_MAX); tín hiệu yếu hơn
# thì risk thấp hơn (gần RISK_PERCENT_MIN), giống hệt cách R:R đã linh hoạt trước đó.
#
# LƯU Ý: vì risk% giờ thay đổi theo từng lệnh, khoảng cách entry→SL (do ATR quyết định) cũng
# khác nhau mỗi lệnh, nên ĐÒN BẨY CẦN DÙNG sẽ dao động theo cả 2 yếu tố: độ tin cậy tín hiệu
# VÀ khung giao dịch. Đòn bẩy càng cao, biên độ "wick" chịu được trước khi bị thanh lý càng
# nhỏ — đây là rủi ro thật ngoài con số % risk trên lý thuyết, không phải rủi ro loại bỏ được bằng công thức.
RISK_PERCENT_MIN = float(os.environ.get("RISK_PERCENT_MIN", "0.5"))   # tín hiệu yếu nhất
RISK_PERCENT_MAX = float(os.environ.get("RISK_PERCENT_MAX", "2.0"))   # tín hiệu mạnh nhất
MARGIN_PCT_TARGET_DEFAULT = float(os.environ.get("MARGIN_PCT_TARGET", "8.0"))  # điểm neo ước tính ban đầu

def dynamic_risk_percent(confluence_pct):
    """Nội suy risk% theo độ hội tụ đa khung — cùng công thức chuẩn hoá với dynamic_rr_ratio."""
    lo, hi = 30.0, 100.0
    t = max(0.0, min(1.0, (confluence_pct - lo) / (hi - lo)))
    return round(RISK_PERCENT_MIN + (RISK_PERCENT_MAX - RISK_PERCENT_MIN) * t, 3)

# Khung đòn bẩy riêng theo từng khung giao dịch (timeframe) — khung nhỏ (M15) có SL
# co giãn theo ATR hẹp hơn nên tự nhiên cần đòn bẩy cao hơn mới đạt đúng risk_percent;
# khung lớn (H4) có SL rộng hơn nên cần đòn bẩy thấp hơn dù risk% giữ nguyên.
# CRYPTO: trần theo đúng mức BingX Perpetual Futures thực tế cho phép (~150-200x).
LEVERAGE_RANGE_BY_PROFILE = {
    # Floor hạ mạnh (so với bản trước 50/30/20) để bot có thể chọn đòn bẩy thấp hơn khi
    # khoảng cách SL đủ rộng để không cần đòn bẩy cao mới đạt đúng risk_percent — tránh
    # ép buộc "ăn phí oan" (phí giao dịch tỷ lệ THUẬN với đòn bẩy, xem calc_position_sizing).
    "SCALP":    (10, 200),   # M15 — biến động ngắn hạn, SL hẹp
    "SWING":    (10, 125),   # H1
    "POSITION": (5, 75),     # H4 — biến động rộng hơn, SL xa hơn
}
# HÀNG HOÁ (Vàng/Dầu qua BingX "Standard Futures"/Forex Perpetual): sàn cho phép trần cao
# hơn crypto (tới 500x theo công bố của BingX), nhưng vẫn kẹp theo từng khung như trên.
COMMODITY_LEVERAGE_RANGE_BY_PROFILE = {
    "SCALP":    (10, 500),
    "SWING":    (10, 300),
    "POSITION": (5, 150),
}
DEFAULT_LEVERAGE_RANGE = (5, 100)

# Số dư tài khoản THỰC (USDT) — khai báo để bot tính ra số tiền ký quỹ cụ thể (USDT) và
# tự nâng đòn bẩy khi cần để đạt khối lượng lệnh tối thiểu sàn yêu cầu với vốn nhỏ.
# Để 0 nếu chỉ muốn tính theo %, không cần số tiền cụ thể.
ACCOUNT_BALANCE_USDT = float(os.environ.get("ACCOUNT_BALANCE_USDT", "0"))
# Khối lượng lệnh tối thiểu (USDT) sàn yêu cầu — BingX thường ~2-5 USDT tùy cặp,
# để giá trị an toàn hơn (5) làm mặc định, bạn có thể chỉnh theo cặp mình hay đánh.
MIN_NOTIONAL_USDT = float(os.environ.get("MIN_NOTIONAL_USDT", "5.0"))

# Lưu ý: KHÔNG có mức đòn bẩy 1000x trên bất kỳ sàn lớn nào (kể cả BingX) tại thời điểm
# viết code này — trần thực tế cao nhất là 500x (BingX Standard Futures/Forex/hàng hoá).
# Nếu để lộ giá trị vượt xa thực tế sàn hỗ trợ, bot sẽ đưa ra con số không dùng được thật.
LEVERAGE_STEPS = [1, 2, 3, 5, 10, 15, 20, 25, 30, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500]

# ------------------------------------------------------------------
# PHÍ GIAO DỊCH + FUNDING + GIÁ THANH LÝ ƯỚC TÍNH
# ------------------------------------------------------------------
# Phí % mỗi CHIỀU (vào hoặc ra) tính trên NOTIONAL — BingX taker fee phổ biến ~0.05%.
TRADING_FEE_PCT_PER_SIDE = float(os.environ.get("TRADING_FEE_PCT_PER_SIDE", "0.05"))
# Funding rate trung bình mỗi 8 tiếng (dao động quanh 0-0.01%, dùng ước tính trung bình).
FUNDING_RATE_PCT_PER_8H = float(os.environ.get("FUNDING_RATE_PCT_PER_8H", "0.01"))
# Thời gian giữ lệnh trung bình ƯỚC TÍNH theo từng khung — dùng để ước tính số lần bị
# trừ funding, KHÔNG phải cam kết chính xác (không thể biết trước lệnh sẽ đóng khi nào).
AVG_HOLD_HOURS_BY_PROFILE = {"SCALP": 4, "SWING": 24, "POSITION": 96}
# Maintenance margin rate ƯỚC TÍNH dùng để tính giá thanh lý — mức thực tế do SÀN quyết định,
# thay đổi theo từng cặp/khối lượng lệnh, con số này chỉ là xấp xỉ hợp lý cho tier retail phổ biến.
MAINTENANCE_MARGIN_RATE = float(os.environ.get("MAINTENANCE_MARGIN_RATE", "0.005"))

def estimate_liquidation_price(entry, leverage, is_buy):
    """Ước tính giá thanh lý (isolated margin, đơn giản hoá) — KHÔNG chính xác 100% vì mỗi
    sàn/tier có công thức maintenance margin riêng, chỉ dùng để CẢNH BÁO tương đối."""
    if leverage <= 0:
        return None
    if is_buy:
        return entry * (1 - 1 / leverage + MAINTENANCE_MARGIN_RATE)
    return entry * (1 + 1 / leverage - MAINTENANCE_MARGIN_RATE)

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
                          risk_percent=None, margin_pct_anchor=None, account_balance=None,
                          asset_class="crypto", rr_ratio=None, is_buy=True):
    """
    Trả về dict:
    - confidence_level: nhãn độ tin cậy tín hiệu
    - risk_percent: % tài khoản chấp nhận mất nếu dính SL (GIÁ THUẦN, chưa trừ phí)
    - leverage: đòn bẩy đề xuất, đã kẹp trong khung profile VÀ đã kiểm tra an toàn thanh lý
    - margin_pct: % tài khoản dùng làm ký quỹ — tính lại theo leverage cuối cùng
    - leverage_capped: True nếu đòn bẩy CẦN vượt trần profile (risk thực tế cao hơn hiển thị)
    - liquidation_price_est: giá thanh lý ƯỚC TÍNH (không chính xác 100%, xem docstring hàm
      estimate_liquidation_price) — dùng để nhận biết nếu SL có nguy cơ không kịp khớp trước
      khi bị sàn thanh lý
    - leverage_reduced_for_liquidation_safety: True nếu bot đã TỰ HẠ đòn bẩy so với mức tính
      ban đầu để đảm bảo giá thanh lý nằm SAU (không sớm hơn) mức SL của bạn
    - fee_pct_of_margin: % tài khoản mất vào phí giao dịch (cả 2 chiều vào/ra) — CÀNG CAO khi
      đòn bẩy càng lớn (phí tính trên notional, không phải trên margin)
    - est_funding_pct_of_margin: % tài khoản ước tính mất vào phí funding nếu giữ lệnh tới khi
      chạm TP (ước tính theo thời gian giữ lệnh trung bình của profile, KHÔNG chính xác)
    - net_loss_pct_if_sl: risk_percent CỘNG phí — số % thực tế mất nếu dính SL
    - net_profit_pct_if_tp: lợi nhuận thực tế SAU phí + funding nếu chạm TP chính (TP2)
    - margin_usdt, notional_usdt: số tiền cụ thể (USDT) NẾU khai báo ACCOUNT_BALANCE_USDT
    - min_notional_adjusted: True nếu đòn bẩy được nâng để đạt khối lượng lệnh tối thiểu sàn
    """
    risk_percent = risk_percent if risk_percent is not None else dynamic_risk_percent(confluence_pct)
    margin_anchor = margin_pct_anchor if margin_pct_anchor is not None else MARGIN_PCT_TARGET_DEFAULT
    account_balance = account_balance if account_balance is not None else ACCOUNT_BALANCE_USDT
    confidence_label = classify_confidence(confluence_pct)
    leverage_table = COMMODITY_LEVERAGE_RANGE_BY_PROFILE if asset_class == "commodity" else LEVERAGE_RANGE_BY_PROFILE
    min_lev, max_lev = leverage_table.get(profile_key, DEFAULT_LEVERAGE_RANGE)

    sl_distance_pct = abs(entry - stop_loss) / entry * 100
    if sl_distance_pct <= 0:
        return {
            "confidence_level": confidence_label, "risk_percent": risk_percent,
            "margin_pct": margin_anchor, "leverage": min_lev, "leverage_capped": False,
            "margin_usdt": None, "notional_usdt": None, "min_notional_adjusted": False,
            "liquidation_price_est": None, "leverage_reduced_for_liquidation_safety": False,
            "fee_pct_of_margin": None, "est_funding_pct_of_margin": None,
            "net_loss_pct_if_sl": risk_percent, "net_profit_pct_if_tp": None,
        }

    # % tài khoản cần "phơi nhiễm" (notional) để đúng risk_percent, bất kể dùng đòn bẩy nào —
    # đây là con số CỐ ĐỊNH theo risk_percent và khoảng cách SL, không đổi theo profile.
    notional_pct = risk_percent / sl_distance_pct * 100

    # Ước tính đòn bẩy khởi điểm dựa trên margin neo (anchor), rồi kẹp vào khung riêng
    # của profile (VD SCALP 50-200x, POSITION 20-75x) — đây là bước quyết định leverage cuối cùng.
    raw_leverage = notional_pct / margin_anchor if margin_anchor > 0 else min_lev
    leverage = snap_leverage(raw_leverage)
    leverage_capped = raw_leverage > max_lev
    leverage = max(min_lev, min(leverage, max_lev))

    margin_pct = notional_pct / leverage if leverage > 0 else margin_anchor
    margin_pct = min(margin_pct, 100.0)  # không đề xuất vượt quá 100% tài khoản

    margin_usdt = None
    notional_usdt = None
    min_notional_adjusted = False

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
                margin_pct = notional_pct / leverage if leverage > 0 else margin_pct
                margin_usdt = round(account_balance * margin_pct / 100, 2)
            notional_usdt = round(margin_usdt * leverage, 2)

    # ----------------------------------------------------------------
    # AN TOÀN THANH LÝ: nếu giá thanh lý ước tính nằm TRƯỚC (gần entry hơn) SL, nghĩa là
    # bạn có nguy cơ bị sàn thanh lý TRƯỚC KHI SL kịp khớp — tự động hạ đòn bẩy xuống mức
    # thấp hơn cho tới khi giá thanh lý nằm SAU SL, hoặc chạm mức đòn bẩy thấp nhất có thể.
    # ----------------------------------------------------------------
    liquidation_price = estimate_liquidation_price(entry, leverage, is_buy)
    leverage_reduced_for_safety = False

    def _is_safe(liq_price):
        if liq_price is None:
            return True
        return (liq_price <= stop_loss) if is_buy else (liq_price >= stop_loss)

    if not _is_safe(liquidation_price):
        for step in sorted([s for s in LEVERAGE_STEPS if s <= leverage], reverse=True):
            candidate_liq = estimate_liquidation_price(entry, step, is_buy)
            if _is_safe(candidate_liq):
                leverage = step
                liquidation_price = candidate_liq
                leverage_reduced_for_safety = True
                break
        else:
            leverage = LEVERAGE_STEPS[0]  # ngay cả 1x cũng có thể không đủ an toàn với SL quá hẹp -> dùng mức thấp nhất, vẫn cảnh báo
            liquidation_price = estimate_liquidation_price(entry, leverage, is_buy)
            leverage_reduced_for_safety = True

        # Leverage đổi -> margin phải tính lại theo giá trị mới để vẫn đúng risk_percent mục tiêu
        margin_pct = min(notional_pct / leverage, 100.0) if leverage > 0 else margin_pct
        if account_balance and account_balance > 0:
            margin_usdt = round(account_balance * margin_pct / 100, 2)
            notional_usdt = round(margin_usdt * leverage, 2)

    # ----------------------------------------------------------------
    # PHÍ GIAO DỊCH + FUNDING — quy đổi ra % TÀI KHOẢN (margin), không phải % giá.
    # Phí/funding tính trên NOTIONAL, nên quy ra % margin phải NHÂN VỚI ĐÒN BẨY — đây là lý do
    # đòn bẩy cao khiến phí "ăn" vào tài khoản nhiều hơn hẳn so với giao dịch không đòn bẩy.
    # ----------------------------------------------------------------
    fee_pct_of_margin = round(leverage * TRADING_FEE_PCT_PER_SIDE * 2, 3)  # 2 chiều: vào + ra
    avg_hold_hours = AVG_HOLD_HOURS_BY_PROFILE.get(profile_key, 24)
    funding_periods = avg_hold_hours / 8
    est_funding_pct_of_margin = round(leverage * funding_periods * FUNDING_RATE_PCT_PER_8H, 3)

    net_loss_pct_if_sl = round(risk_percent + fee_pct_of_margin, 3)
    net_profit_pct_if_tp = None
    if rr_ratio is not None:
        gross_profit_pct = risk_percent * rr_ratio
        net_profit_pct_if_tp = round(gross_profit_pct - fee_pct_of_margin - est_funding_pct_of_margin, 3)

    return {
        "confidence_level": confidence_label,
        "risk_percent": risk_percent,
        "margin_pct": round(margin_pct, 2),
        "leverage": leverage,
        "leverage_capped": leverage_capped,
        "margin_usdt": margin_usdt,
        "notional_usdt": notional_usdt,
        "min_notional_adjusted": min_notional_adjusted,
        "liquidation_price_est": round(liquidation_price, 6) if liquidation_price else None,
        "leverage_reduced_for_liquidation_safety": leverage_reduced_for_safety,
        "fee_pct_of_margin": fee_pct_of_margin,
        "est_funding_pct_of_margin": est_funding_pct_of_margin,
        "net_loss_pct_if_sl": net_loss_pct_if_sl,
        "net_profit_pct_if_tp": net_profit_pct_if_tp,
    }
