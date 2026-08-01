"""
backtest.py
-----------
Kiểm tra độ chính xác (win rate) của thuật toán trên dữ liệu lịch sử Binance.
Dùng LẠI đúng logic phân tích từ indicators.py — kết quả phản ánh trung thực
những gì bot live sẽ làm, không phải một thuật toán "riêng cho đẹp báo cáo".

CÁCH DÙNG:
    python backtest.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --days 30

    --symbols   danh sách coin cách nhau bằng dấu phẩy (mặc định: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT)
    --days      số ngày lịch sử để test (mặc định: 30, tối đa khuyến nghị ~60 vì giới hạn dữ liệu M1)
    --lookahead số nến M15 tối đa để chờ giá chạm TP/SL trước khi tính là "hết hạn không rõ kết quả" (mặc định: 96 ~ 1 ngày)

LƯU Ý QUAN TRỌNG:
- Đây là backtest đơn giản theo giá đóng cửa nến, CHƯA tính phí giao dịch, slippage,
  hay khả năng giá "wick" chạm SL/TP trong tích tắc rồi quay lại (dùng high/low nên
  đã phần nào phản ánh việc này, nhưng vẫn là ước lượng).
- Kết quả quá khứ KHÔNG đảm bảo hiệu suất tương lai. Đây là công cụ tham khảo để
  đánh giá tương đối, không phải căn cứ để quyết định vốn thật.
"""

import argparse
import time
import requests
import pandas as pd

from indicators import TIMEFRAMES, analyze_timeframe, generate_signal

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
session = requests.Session()


def fetch_full_history(symbol, interval, days):
    """Lấy toàn bộ nến lịch sử trong N ngày qua, tự động phân trang (Binance giới hạn 1000 nến/lần gọi)."""
    end_time = int(time.time() * 1000)
    start_time = end_time - days * 24 * 60 * 60 * 1000

    all_rows = []
    cursor = start_time
    while cursor < end_time:
        params = {
            "symbol": symbol, "interval": interval,
            "startTime": cursor, "limit": 1000
        }
        res = session.get(BINANCE_KLINES_URL, params=params, timeout=10)
        rows = res.json()
        if not isinstance(rows, list) or len(rows) == 0:
            break
        all_rows.extend(rows)
        cursor = rows[-1][0] + 1  # tiếp tục từ sau nến cuối cùng vừa lấy
        if len(rows) < 1000:
            break
        time.sleep(0.1)  # tránh spam Binance khi phân trang

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


def simulate_outcome(m15_df, entry_index, signal_type, entry, sl, tp, lookahead):
    """
    Từ thời điểm phát tín hiệu (entry_index trên khung M15), lần lượt xem các nến
    M15 tiếp theo (tối đa `lookahead` nến) xem giá chạm TP trước hay SL trước.
    """
    is_buy = "BUY" in signal_type
    end_index = min(entry_index + lookahead, len(m15_df) - 1)

    for i in range(entry_index + 1, end_index + 1):
        high = m15_df['high'].iloc[i]
        low = m15_df['low'].iloc[i]

        if is_buy:
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp

        # Nếu cả 2 cùng chạm trong 1 nến (nến biến động mạnh), giả định thận trọng: SL chạm trước
        if hit_sl and hit_tp:
            return "SL"
        if hit_sl:
            return "SL"
        if hit_tp:
            return "TP"

    return "EXPIRED"  # hết thời gian chờ mà chưa chạm TP/SL nào


def run_backtest(symbols, days, lookahead):
    print(f"📊 Backtest {len(symbols)} coin trong {days} ngày gần nhất (lookahead {lookahead} nến M15)...\n")

    all_trades = []

    for symbol in symbols:
        print(f"[⏳] Đang tải dữ liệu lịch sử: {symbol}...")

        # Tải đủ dữ liệu lịch sử cho từng khung thời gian cần dùng
        history = {}
        for tf_label, interval in TIMEFRAMES.items():
            df = fetch_full_history(symbol, interval, days)
            if df is None or len(df) < 260:
                print(f"   ⚠️ Không đủ dữ liệu {tf_label} cho {symbol}, bỏ qua coin này.")
                history = None
                break
            history[tf_label] = df

        if not history:
            continue

        m15_df = history["M15"]
        trades_for_symbol = 0

        # Duyệt qua từng nến M15 lịch sử, giả lập như bot đang quét realtime tại thời điểm đó
        # Bắt đầu từ nến 210 (đủ dữ liệu để tính EMA50/RSI) tới cuối, chừa lại lookahead nến để có thể simulate
        for i in range(210, len(m15_df) - lookahead):
            current_time = m15_df['open_time'].iloc[i]

            tf_results = {}
            for tf_label, tf_df in history.items():
                # Lấy các nến ĐÃ ĐÓNG CỬA tính đến thời điểm current_time (mô phỏng đúng những gì bot live thấy)
                sub_df = tf_df[tf_df['open_time'] <= current_time].tail(210)
                if len(sub_df) < 60:
                    continue
                result = analyze_timeframe(sub_df)
                if result:
                    tf_results[tf_label] = result

            signal = generate_signal(tf_results)
            if not signal:
                continue

            outcome = simulate_outcome(
                m15_df, entry_index=i,
                signal_type=signal["signal"],
                entry=signal["entry"], sl=signal["stop_loss"], tp=signal["take_profit"],
                lookahead=lookahead
            )

            all_trades.append({
                "symbol": symbol,
                "signal": signal["signal"],
                "confluence_pct": signal["confluence_pct"],
                "outcome": outcome,
            })
            trades_for_symbol += 1

        print(f"   ✅ {symbol}: {trades_for_symbol} tín hiệu tìm thấy trong giai đoạn backtest.")

    print_report(all_trades)


def print_report(trades):
    print("\n" + "=" * 60)
    print("KẾT QUẢ BACKTEST")
    print("=" * 60)

    if not trades:
        print("Không có tín hiệu nào được sinh ra trong giai đoạn backtest.")
        return

    df = pd.DataFrame(trades)
    total = len(df)
    tp_count = (df["outcome"] == "TP").sum()
    sl_count = (df["outcome"] == "SL").sum()
    expired_count = (df["outcome"] == "EXPIRED").sum()
    decided = tp_count + sl_count  # chỉ tính win rate trên các lệnh đã có kết quả rõ ràng

    win_rate = (tp_count / decided * 100) if decided > 0 else 0

    print(f"Tổng số tín hiệu:        {total}")
    print(f"  ├─ Chạm Take Profit:   {tp_count}")
    print(f"  ├─ Chạm Stop Loss:     {sl_count}")
    print(f"  └─ Hết hạn chưa rõ:    {expired_count}")
    print(f"\nWin rate (trên {decided} lệnh có kết quả rõ ràng): {win_rate:.1f}%")
    print(f"R:R mỗi lệnh cố định 1:2 → hoà vốn cần win rate ≥ 33.3%")

    print("\n--- Theo từng coin ---")
    for symbol, group in df.groupby("symbol"):
        g_decided = group[group["outcome"].isin(["TP", "SL"])]
        g_tp = (g_decided["outcome"] == "TP").sum()
        g_total_decided = len(g_decided)
        g_wr = (g_tp / g_total_decided * 100) if g_total_decided > 0 else 0
        print(f"  {symbol}: {len(group)} tín hiệu | win rate {g_wr:.1f}% ({g_tp}/{g_total_decided})")

    print("\n⚠️  Backtest chưa tính phí giao dịch/slippage. Kết quả quá khứ không đảm bảo tương lai.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest thuật toán Signal Screener trên dữ liệu lịch sử Binance.")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT",
                         help="Danh sách coin cách nhau bằng dấu phẩy")
    parser.add_argument("--days", type=int, default=30, help="Số ngày lịch sử để test")
    parser.add_argument("--lookahead", type=int, default=96, help="Số nến M15 tối đa chờ TP/SL")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    run_backtest(symbols, args.days, args.lookahead)
