"""
backtest.py
-----------
Kiểm tra độ chính xác (win rate) của thuật toán trên dữ liệu lịch sử Binance —
CHO TỪNG KHUNG GIAO DỊCH RIÊNG (SCALP / SWING / POSITION), dùng đúng logic
từ indicators.py mà bot live đang chạy. Tự động tương thích với chuẩn SL/TP bằng ATR mới nhất.
"""

import argparse
import time
import requests
import pandas as pd

from indicators import TRADE_PROFILES, analyze_timeframe, generate_signal_for_profile

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
session = requests.Session()

DEFAULT_LOOKAHEAD = {"M15": 96, "H1": 168, "H4": 90}

def fetch_full_history(symbol, interval, days):
    end_time = int(time.time() * 1000)
    start_time = end_time - days * 24 * 60 * 60 * 1000

    all_rows = []
    cursor = start_time
    while cursor < end_time:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1000}
        res = session.get(BINANCE_KLINES_URL, params=params, timeout=10)
        rows = res.json()
        if not isinstance(rows, list) or len(rows) == 0:
            break
        all_rows.extend(rows)
        cursor = rows[-1][0] + 1
        if len(rows) < 1000:
            break
        time.sleep(0.1)

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def simulate_outcome(entry_df, entry_index, signal_type, sl, tp, lookahead):
    is_buy = "BUY" in signal_type
    end_index = min(entry_index + lookahead, len(entry_df) - 1)

    for i in range(entry_index + 1, end_index + 1):
        high = entry_df['high'].iloc[i]
        low = entry_df['low'].iloc[i]
        if is_buy:
            hit_sl, hit_tp = low <= sl, high >= tp
        else:
            hit_sl, hit_tp = high >= sl, low <= tp

        if hit_sl:
            return "SL"
        if hit_tp:
            return "TP"

    return "EXPIRED"


def backtest_profile(profile_key, symbols, days):
    profile = TRADE_PROFILES[profile_key]
    entry_tf = profile["entry_tf"]
    needed_tfs = [entry_tf] + profile["bias_tfs"]
    lookahead = DEFAULT_LOOKAHEAD.get(entry_tf, 100)

    print(f"\n{'='*60}\nPROFILE: {profile['label']}  (entry={entry_tf}, bias={'+'.join(profile['bias_tfs'])})\n{'='*60}")

    all_trades = []

    for symbol in symbols:
        print(f"[⏳] Đang tải dữ liệu lịch sử: {symbol} ({', '.join(needed_tfs)})...")

        history = {}
        ok = True
        for tf_label in needed_tfs:
            interval = {"M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d"}[tf_label]
            df = fetch_full_history(symbol, interval, days)
            if df is None or len(df) < 260:
                print(f"   ⚠️ Không đủ dữ liệu {tf_label} cho {symbol}, bỏ qua coin này.")
                ok = False
                break
            history[tf_label] = df
        if not ok:
            continue

        entry_df = history[entry_tf]
        trades_for_symbol = 0

        for i in range(210, len(entry_df) - lookahead):
            current_time = entry_df['open_time'].iloc[i]

            tf_results = {}
            for tf_label, tf_df in history.items():
                sub_df = tf_df[tf_df['open_time'] <= current_time].tail(210)
                if len(sub_df) < 60:
                    continue
                result = analyze_timeframe(sub_df)
                if result:
                    tf_results[tf_label] = result

            signal = generate_signal_for_profile(tf_results, profile_key)
            if not signal:
                continue

            outcome = simulate_outcome(
                entry_df, entry_index=i, signal_type=signal["signal"],
                sl=signal["stop_loss"], tp=signal["take_profit"], lookahead=lookahead
            )

            all_trades.append({"symbol": symbol, "outcome": outcome})
            trades_for_symbol += 1

        print(f"   ✅ {symbol}: {trades_for_symbol} tín hiệu tìm thấy.")

    print_report(all_trades, profile["label"])


def print_report(trades, profile_label):
    print(f"\n--- KẾT QUẢ: {profile_label} ---")
    if not trades:
        print("Không có tín hiệu nào được sinh ra trong giai đoạn backtest.")
        return

    df = pd.DataFrame(trades)
    total = len(df)
    tp_count = (df["outcome"] == "TP").sum()
    sl_count = (df["outcome"] == "SL").sum()
    expired_count = (df["outcome"] == "EXPIRED").sum()
    decided = tp_count + sl_count
    win_rate = (tp_count / decided * 100) if decided > 0 else 0

    print(f"Tổng số tín hiệu: {total}  |  TP: {tp_count}  |  SL: {sl_count}  |  Hết hạn: {expired_count}")
    print(f"Win rate (trên {decided} lệnh có kết quả rõ ràng): {win_rate:.1f}%  (hoà vốn cần ≥33.3% với R:R 1:2)")

    for symbol, group in df.groupby("symbol"):
        g_decided = group[group["outcome"].isin(["TP", "SL"])]
        g_tp = (g_decided["outcome"] == "TP").sum()
        g_total = len(g_decided)
        g_wr = (g_tp / g_total * 100) if g_total > 0 else 0
        print(f"  {symbol}: {len(group)} tín hiệu | win rate {g_wr:.1f}% ({g_tp}/{g_total})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest theo từng khung giao dịch.")
    parser.add_argument("--profile", type=str, default="ALL", choices=["SCALP", "SWING", "POSITION", "ALL"])
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    profiles_to_run = list(TRADE_PROFILES.keys()) if args.profile == "ALL" else [args.profile]

    print(f"📊 Backtest {len(symbols)} coin trong {args.days} ngày gần nhất — profile: {', '.join(profiles_to_run)}")

    for profile_key in profiles_to_run:
        backtest_profile(profile_key, symbols, args.days)

    print("\n⚠️  Backtest chưa tính phí giao dịch/slippage. Kết quả quá khứ không đảm bảo tương lai.")
