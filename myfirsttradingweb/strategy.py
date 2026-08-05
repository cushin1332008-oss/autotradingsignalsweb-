if (
    score >= 85
    and btc_trend == "bullish"
    and adx > 25
    and ema50 > ema200
    and volume_spike
):
    return LongSignal(...)
