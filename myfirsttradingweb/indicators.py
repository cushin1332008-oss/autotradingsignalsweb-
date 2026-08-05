import pandas as pd
import numpy as np


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(df, period=14):

    high_low = df["high"] - df["low"]

    high_close = (df["high"] - df["close"].shift()).abs()

    low_close = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    ).max(axis=1)

    return tr.rolling(period).mean()


def macd(series):

    ema12 = ema(series, 12)

    ema26 = ema(series, 26)

    macd_line = ema12 - ema26

    signal = ema(macd_line, 9)

    hist = macd_line - signal

    return macd_line, signal, hist


def volume_ma(volume, period=20):
    return volume.rolling(period).mean()


def adx(df, period=14):

    up = df["high"].diff()

    down = -df["low"].diff()

    plus_dm = np.where((up > down) & (up > 0), up, 0)

    minus_dm = np.where((down > up) & (down > 0), down, 0)

    tr = atr(df, period)

    plus_di = 100 * pd.Series(plus_dm).rolling(period).sum() / tr

    minus_di = 100 * pd.Series(minus_dm).rolling(period).sum() / tr

    dx = (
        (plus_di - minus_di).abs()
        / (plus_di + minus_di)
    ) * 100

    return dx.rolling(period).mean()


def apply_all_indicators(df):

    if df is None:
        return None

    if len(df) < 220:
        return None

    close = df["close"]

    df["ema20"] = ema(close, 20)

    df["ema50"] = ema(close, 50)

    df["ema100"] = ema(close, 100)

    df["ema200"] = ema(close, 200)

    df["rsi"] = rsi(close)

    df["atr"] = atr(df)

    df["vol_ma20"] = volume_ma(df["volume"])

    df["adx"] = adx(df)

    macd_line, signal, hist = macd(close)

    df["macd"] = macd_line

    df["macd_signal"] = signal

    df["macd_hist"] = hist

    return df
