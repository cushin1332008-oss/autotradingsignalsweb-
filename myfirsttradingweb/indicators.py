import pandas as pd

def calculate_rsi(df, period=14):
    """Tính chỉ báo RSI"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(df, period=200):
    """Tính đường trung bình động EMA 200 xác định xu hướng lớn"""
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_volume_ma(df, period=20):
    """Tính trung bình khối lượng giao dịch Volume MA"""
    return df['volume'].rolling(window=period).mean()

def apply_all_indicators(df):
    """Hàm tổng hợp áp dụng tất cả chỉ báo vào DataFrame nến"""
    if df is None or len(df) < 200:
        return None
    
    df['rsi'] = calculate_rsi(df, period=14)
    df['ema200'] = calculate_ema(df, period=200)
    df['vol_ma20'] = calculate_volume_ma(df, period=20)
    
    return df
