import pandas as pd
import pandas_ta as ta

TIMEFRAMES = {
    "M15": "15m",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1d"
}

def calculate_technical_indicators(df):
    """Tính toán toàn bộ bộ chỉ báo kỹ thuật chuyên sâu"""
    if df.empty or len(df) < 50:
        return df

    # 1. Chỉ báo RSI
    df['RSI'] = ta.rsi(df['close'], length=14)

    # 2. Các đường trung bình động EMA
    df['EMA_20'] = ta.ema(df['close'], length=20)
    df['EMA_50'] = ta.ema(df['close'], length=50)
    df['EMA_200'] = ta.ema(df['close'], length=200)

    # 3. Bollinger Bands
    bbands = ta.bbands(df['close'], length=20, std=2)
    if bbands is not None and not bbands.empty:
        df['BB_LOWER'] = bbands.iloc[:, 0]
        df['BB_MIDDLE'] = bbands.iloc[:, 1]
        df['BB_UPPER'] = bbands.iloc[:, 2]

    # 4. Average True Range (ATR) tính SL/TP động
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    # 5. ADX - Đo độ mạnh của xu hướng
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None and not adx_df.empty:
        df['ADX'] = adx_df.iloc[:, 0]

    return df

def get_market_trend(df):
    """Xác định xu hướng chính dựa trên EMA 20/50/200"""
    if df.empty or len(df) < 200:
        return "NEUTRAL"
    
    last_row = df.iloc[-1]
    close = last_row['close']
    ema20 = last_row['EMA_20']
    ema50 = last_row['EMA_50']
    ema200 = last_row['EMA_200']

    if close > ema20 > ema50 > ema200:
        return "BULLISH"
    elif close < ema20 < ema50 < ema200:
        return "BEARISH"
    return "SIDEWAYS"

def check_candlestick_patterns(df):
    """Nhận diện các mô hình nến đảo chiều chính xác"""
    if len(df) < 3:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    c_open, c_close = curr['open'], curr['close']
    c_high, c_low = curr['high'], curr['low']
    p_open, p_close = prev['open'], prev['close']

    body = abs(c_close - c_open)
    upper_wick = c_high - max(c_open, c_close)
    lower_wick = min(c_open, c_close) - c_low

    # Bullish Engulfing
    if p_close < p_open and c_close > c_open and c_close >= p_open and c_open <= p_close:
        return "BULLISH_ENGULFING"

    # Bearish Engulfing
    if p_close > p_open and c_close < c_open and c_close <= p_open and c_open >= p_close:
        return "BEARISH_ENGULFING"

    # Hammer (Nến búa tăng giá)
    if lower_wick >= 2 * body and upper_wick <= body * 0.5 and body > 0:
        return "HAMMER"

    # Shooting Star (Nến bắn sao giảm giá)
    if upper_wick >= 2 * body and lower_wick <= body * 0.5 and body > 0:
        return "SHOOTING_STAR"

    return None
