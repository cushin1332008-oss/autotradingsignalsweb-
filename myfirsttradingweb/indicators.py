import pandas as pd

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(df, period=200):
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_volume_ma(df, period=20):
    return df['volume'].rolling(window=period).mean()

def apply_all_indicators(df):
    if df is None or len(df) < 200:
        return None
    df['rsi'] = calculate_rsi(df, period=14)
    df['ema200'] = calculate_ema(df, period=200)
    df['vol_ma20'] = calculate_volume_ma(df, period=20)
    return df
