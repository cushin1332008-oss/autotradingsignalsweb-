import os
import json
import time
import threading
import requests
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from indicators import (
    TIMEFRAMES, TRADE_PROFILES, analyze_timeframe, generate_all_signals, calc_position_sizing
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def now_vn_str():
    return datetime.now(VN_TZ).strftime('%H:%M:%S %d/%m/%Y')

# ------------------------------------------------------------------
# 1. CẤU HÌNH FIREBASE ADMIN
# ------------------------------------------------------------------
secret_path = "/etc/secrets/firebase.json"
env_cred = os.environ.get("FIREBASE_CREDENTIALS")
local_path = "serviceAccountKey.json"

if os.path.exists(secret_path):
    print(f"[🔑 AUTH] Dùng Render Secret File: {secret_path}")
    cred = credentials.Certificate(secret_path)
elif env_cred:
    print("[🔑 AUTH] Dùng biến môi trường FIREBASE_CREDENTIALS")
    cred = credentials.Certificate(json.loads(env_cred))
elif os.path.exists(local_path):
    print(f"[🔑 AUTH] Dùng file local: {local_path}")
    cred = credentials.Certificate(local_path)
else:
    raise RuntimeError(
        "Không tìm thấy Firebase credentials. Xem hướng dẫn Secret File / "
        "biến môi trường FIREBASE_CREDENTIALS / file serviceAccountKey.json."
    )

firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://webtrade-85ca8-default-rtdb.asia-southeast1.firebasedatabase.app'
})

ref = db.reference('signals')
ref_history = db.reference('signal_history')     # lưu từng tín hiệu đã bắn ra để theo dõi kết quả thật
ref_stats = db.reference('performance_stats')     # thống kê win rate tổng hợp, cập nhật mỗi chu kỳ quét
session = requests.Session()

# ------------------------------------------------------------------
# 2. THEO DÕI TÍN HIỆU MỚI → GHI LỊCH SỬ ĐỂ ĐO WIN RATE THẬT
# ------------------------------------------------------------------
_last_alerted = {}  # key: "SYMBOL_PROFILE" -> loại tín hiệu lần quét trước (dùng để phát hiện tín hiệu MỚI)

def record_new_trade(key, item):
    """Lưu 1 tín hiệu mới vào signal_history để theo dõi xem thực tế có chạm TP hay SL trước."""
    trade_id = f"{key}_{int(time.time())}"
    try:
        ref_history.child(trade_id).set({
            "symbol": item["symbol"],
            "profile": item["profile"],
            "signal": item["signal"],
            "entry": item["entry"],
            "stop_loss": item["stop_loss"],
            "take_profit": item["take_profit"],
            "confluence_pct": item["confluence_pct"],
            "opened_ts": time.time(),
            "opened_time_str": now_vn_str(),
            "status": "OPEN",
        })
    except Exception as e:
        print(f"[⚠️ HISTORY] Lỗi ghi lịch sử tín hiệu {key}: {e}")

def notify_new_signals(signals_to_upload):
    """Phát hiện tín hiệu MỚI hoặc ĐỔI CHIỀU so với lần quét trước, ghi vào signal_history."""
    global _last_alerted
    for key, item in signals_to_upload.items():
        prev_signal = _last_alerted.get(key)
        if prev_signal != item["signal"]:
            record_new_trade(key, item)
    _last_alerted = {key: item["signal"] for key, item in signals_to_upload.items()}

# ------------------------------------------------------------------
# 3. WATCHLIST TOP COIN THEO VOLUME 24H (100% dữ liệu Binance, không phụ thuộc CoinGecko)
# ------------------------------------------------------------------
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"

STABLECOIN_BASES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "PYUSD"}
MIN_VOLUME_USDT = float(os.environ.get("MIN_VOLUME_USDT", "5000000"))
# Free tier Render CPU yếu — có thể giảm số này (vd: 30-50) qua biến môi trường MAX_COINS
# nếu quét vẫn chậm, thay vì phải sửa code.
MAX_COINS = int(os.environ.get("MAX_COINS", "100"))
# Số coin quét song song cùng lúc — tăng lên nếu Render còn dư tài nguyên, giảm nếu bị lỗi rate-limit.
SCAN_WORKERS = int(os.environ.get("SCAN_WORKERS", "8"))

# Risk% cố định mỗi lệnh (bạn chọn theo khẩu vị — mặc định 1.5%, giữa khoảng 1-2% bạn muốn)
# và % tài khoản dùng làm ký quỹ mỗi lệnh. Đổi qua Environment trên Render, không cần sửa code.
# Risk% giờ TỰ ĐỘNG thay đổi theo độ tin cậy tín hiệu (xem indicators.py dynamic_risk_percent).
# 2 biến này chỉ set qua Render nếu muốn đổi biên độ min/max, không cần đụng code.
RISK_PERCENT_MIN_INFO = os.environ.get("RISK_PERCENT_MIN", "0.5")
RISK_PERCENT_MAX_INFO = os.environ.get("RISK_PERCENT_MAX", "2.0")
MARGIN_PCT_ANCHOR = float(os.environ.get("MARGIN_PCT_ANCHOR", "8.0"))  # điểm neo ước tính ban đầu, KHÔNG phải margin cố định
# Khai báo vốn thực (USDT) để bot tính margin/notional ra số tiền cụ thể và tự nâng đòn bẩy
# khi vốn nhỏ không đủ đạt khối lượng lệnh tối thiểu sàn yêu cầu. Để 0 nếu chỉ cần tính theo %.
ACCOUNT_BALANCE_USDT = float(os.environ.get("ACCOUNT_BALANCE_USDT", "0"))

FALLBACK_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "NEARUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"
]

_watchlist_cache = {"list": [], "ts": 0}
_volume_cache = {"map": {}, "ts": 0}
WATCHLIST_TTL = 3600

def get_binance_usdt_bases():
    print("[⏳ STEP] Đang lấy danh sách cặp USDT trên Binance...")
    res = session.get(BINANCE_EXCHANGE_INFO_URL, timeout=10)
    data = res.json()
    bases = {
        s["baseAsset"].upper()
        for s in data.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }
    print(f"[✅ STEP] Có {len(bases)} coin base khớp USDT trên Binance.")
    return bases

def get_binance_24h_volumes():
    now = time.time()
    if _volume_cache["map"] and now - _volume_cache["ts"] < WATCHLIST_TTL:
        return _volume_cache["map"]
    try:
        print("[⏳ STEP] Đang tải volume 24h toàn bộ cặp Binance (có thể mất vài giây)...")
        res = session.get(BINANCE_TICKER_24H_URL, timeout=20)
        data = res.json()
        volumes = {d["symbol"]: float(d["quoteVolume"]) for d in data if d["symbol"].endswith("USDT")}
        _volume_cache["map"] = volumes
        _volume_cache["ts"] = now
        print(f"[✅ STEP] Đã lấy volume của {len(volumes)} cặp USDT.")
        return volumes
    except Exception as e:
        print(f"[⚠️ VOLUME] Lỗi lấy volume 24h: {e}")
        return _volume_cache["map"]

def get_top_watchlist():
    """
    Xây watchlist HOÀN TOÀN từ Binance (không phụ thuộc CoinGecko) — xếp hạng theo volume
    giao dịch 24h (quoteVolume), lấy MAX_COINS cặp thanh khoản cao nhất đạt ngưỡng tối thiểu.
    Volume giao dịch là chỉ báo thực tế hơn vốn hóa cho việc chọn coin để SCAN TÍN HIỆU
    (vốn hóa nói lên quy mô dự án, còn volume mới nói lên coin đó có đang được giao dịch
    sôi động — tức có cơ hội xuất hiện setup kỹ thuật rõ ràng — hay không).
    """
    now = time.time()
    if _watchlist_cache["list"] and now - _watchlist_cache["ts"] < WATCHLIST_TTL:
        return _watchlist_cache["list"]
    try:
        binance_bases = get_binance_usdt_bases()
        volumes = get_binance_24h_volumes()

        candidates = []
        for pair, vol in volumes.items():
            base = pair[:-4]  # bỏ đuôi "USDT"
            if base in STABLECOIN_BASES or base not in binance_bases:
                continue
            if vol < MIN_VOLUME_USDT:
                continue
            candidates.append((pair, vol))

        candidates.sort(key=lambda x: x[1], reverse=True)
        symbols = [pair for pair, _ in candidates[:MAX_COINS]]

        if symbols:
            _watchlist_cache["list"] = symbols
            _watchlist_cache["ts"] = now
            print(f"[📋 WATCHLIST] {len(symbols)} coin đạt chuẩn volume ≥ {MIN_VOLUME_USDT:,.0f} USDT/24h "
                  f"(trong tổng {len(candidates)} cặp đủ điều kiện)")
            return symbols
    except Exception as e:
        print(f"[⚠️ WATCHLIST] Lỗi lấy danh sách watchlist: {e}")

    print("[⚠️ WATCHLIST] Dùng danh sách dự phòng do không lấy được dữ liệu Binance.")
    return _watchlist_cache["list"] or FALLBACK_WATCHLIST

def format_volume(vol):
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(round(vol))

# ------------------------------------------------------------------
# 4. LẤY DỮ LIỆU NẾN TỪ BINANCE
# ------------------------------------------------------------------
def get_klines(symbol: str, interval: str, limit: int = 210):
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        res = session.get(BINANCE_KLINES_URL, params=params, timeout=8)
        raw = res.json()
        if not isinstance(raw, list) or len(raw) < 60:
            return None
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

# ------------------------------------------------------------------
# 5. QUÉT 1 COIN → SINH TÍN HIỆU CHO CẢ 3 PROFILE (SCALP/SWING/POSITION)
# ------------------------------------------------------------------
def scan_symbol(symbol, volumes_map, btc_context=None):
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval)
        result = analyze_timeframe(df)
        if result:
            tf_results[tf_label] = result

    # Không lọc BTC theo chính nó — chỉ áp dụng bộ lọc macro cho các altcoin khác
    ctx = None if symbol == "BTCUSDT" else btc_context
    all_signals = generate_all_signals(tf_results, btc_context=ctx)
    if not all_signals:
        return {}

    volume_24h = volumes_map.get(symbol, 0)
    output = {}

    for profile_key, signal in all_signals.items():
        sizing = calc_position_sizing(
            entry=signal["entry"], stop_loss=signal["stop_loss"], confluence_pct=signal["confluence_pct"],
            profile_key=profile_key, margin_pct_anchor=MARGIN_PCT_ANCHOR,
            account_balance=ACCOUNT_BALANCE_USDT
        )
        key = f"{symbol}_{profile_key}"
        output[key] = {
            "symbol": symbol,
            **signal,
            **sizing,
            "volume_24h": round(volume_24h, 0),
            "volume_24h_fmt": format_volume(volume_24h),
            "time_str": now_vn_str()
        }

    return output

# ------------------------------------------------------------------
# 6. MINI WEB SERVER (giữ service "sống" trên Render)
# ------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def health_check():
    return {
        "status": "ok",
        "watchlist_size": len(_watchlist_cache["list"]) or len(FALLBACK_WATCHLIST),
        "min_volume_usdt": MIN_VOLUME_USDT,
        "max_coins": MAX_COINS,
        "scan_workers": SCAN_WORKERS,
        "risk_percent_min": RISK_PERCENT_MIN_INFO,
        "risk_percent_max": RISK_PERCENT_MAX_INFO,
        "margin_pct_anchor": MARGIN_PCT_ANCHOR,
        "profiles": list(TRADE_PROFILES.keys()),
    }

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ------------------------------------------------------------------
# 7. QUÉT TOÀN BỘ WATCHLIST SONG SONG (đa luồng) → ĐẨY FIREBASE
# ------------------------------------------------------------------
def get_btc_context():
    """Tính xu hướng BTC 1 lần mỗi chu kỳ quét — dùng làm bộ lọc macro cho toàn bộ altcoin."""
    tf_results = {}
    for tf_label, interval in TIMEFRAMES.items():
        df = get_klines("BTCUSDT", interval)
        result = analyze_timeframe(df)
        if result:
            tf_results[tf_label] = result
    context = {tf: r["trend"] for tf, r in tf_results.items()}
    print(f"[₿ BTC CONTEXT] {context}")
    return context

# ------------------------------------------------------------------
# 8. ĐO LƯỜNG HIỆU SUẤT SỐNG: cập nhật trạng thái lệnh đã bắn ra & tính win rate thật
# ------------------------------------------------------------------
# Thời gian tối đa theo dõi 1 lệnh trước khi coi là "hết hạn không rõ kết quả" — tùy khung
# giao dịch (SCALP kiểm tra nhanh, POSITION cần nhiều thời gian hơn để có thể chạm TP/SL).
MAX_TRACK_DAYS_BY_PROFILE = {"SCALP": 2, "SWING": 10, "POSITION": 30}

def get_current_price(symbol):
    try:
        res = session.get(BINANCE_TICKER_PRICE_URL, params={"symbol": symbol}, timeout=5)
        return float(res.json()["price"])
    except Exception:
        return None

def update_open_trades():
    """Kiểm tra từng lệnh đang OPEN xem giá hiện tại đã chạm TP/SL chưa, cập nhật trạng thái."""
    try:
        all_trades = ref_history.get() or {}
    except Exception as e:
        print(f"[⚠️ HISTORY] Lỗi đọc signal_history: {e}")
        return

    open_trades = {tid: t for tid, t in all_trades.items() if t.get("status") == "OPEN"}
    if not open_trades:
        return

    updated_count = 0
    for trade_id, trade in open_trades.items():
        price = get_current_price(trade["symbol"])
        if price is None:
            continue

        is_buy = "BUY" in trade["signal"]
        hit_tp = price >= trade["take_profit"] if is_buy else price <= trade["take_profit"]
        hit_sl = price <= trade["stop_loss"] if is_buy else price >= trade["stop_loss"]

        max_days = MAX_TRACK_DAYS_BY_PROFILE.get(trade.get("profile"), 7)
        expired = (time.time() - trade.get("opened_ts", time.time())) > max_days * 86400

        new_status = None
        if hit_tp:
            new_status = "TP"
        elif hit_sl:
            new_status = "SL"
        elif expired:
            new_status = "EXPIRED"

        if new_status:
            try:
                ref_history.child(trade_id).update({
                    "status": new_status,
                    "closed_ts": time.time(),
                    "closed_time_str": now_vn_str(),
                    "closed_price": price,
                })
                updated_count += 1
            except Exception as e:
                print(f"[⚠️ HISTORY] Lỗi cập nhật {trade_id}: {e}")

    if updated_count:
        print(f"[📊 PERFORMANCE] Đóng {updated_count} lệnh trong lần kiểm tra này.")

def recompute_stats():
    """Tính lại win rate tổng + theo từng profile, ghi vào performance_stats cho frontend đọc."""
    try:
        all_trades = ref_history.get() or {}
    except Exception as e:
        print(f"[⚠️ HISTORY] Lỗi đọc signal_history để tính thống kê: {e}")
        return

    def empty_bucket():
        return {"total": 0, "tp": 0, "sl": 0, "expired": 0, "open": 0}

    overall = empty_bucket()
    by_profile = {k: empty_bucket() for k in TRADE_PROFILES}

    for trade in all_trades.values():
        status_key = trade.get("status", "OPEN").lower()
        overall["total"] += 1
        overall[status_key] = overall.get(status_key, 0) + 1
        bucket = by_profile.get(trade.get("profile"))
        if bucket is not None:
            bucket["total"] += 1
            bucket[status_key] = bucket.get(status_key, 0) + 1

    def win_rate(bucket):
        decided = bucket["tp"] + bucket["sl"]
        return round(bucket["tp"] / decided * 100, 1) if decided > 0 else None

    overall["win_rate"] = win_rate(overall)
    for bucket in by_profile.values():
        bucket["win_rate"] = win_rate(bucket)

    try:
        ref_stats.set({
            "overall": overall,
            "by_profile": by_profile,
            "updated_at": now_vn_str(),
        })
        wr_display = f"{overall['win_rate']}%" if overall["win_rate"] is not None else "chưa đủ dữ liệu"
        print(f"[📊 PERFORMANCE] Win rate thật hiện tại: {wr_display} "
              f"(tổng {overall['total']} lệnh, {overall['tp']} TP / {overall['sl']} SL / {overall['open']} đang mở)")
    except Exception as e:
        print(f"[⚠️ HISTORY] Lỗi ghi performance_stats: {e}")

def scan_and_push_to_firebase():
    start_ts = time.time()
    print(f"\n[🚀 SCANNING] Bắt đầu quét lúc: {now_vn_str()}...")

    watchlist = get_top_watchlist()
    volumes_map = get_binance_24h_volumes()
    btc_context = get_btc_context()
    signals_to_upload = {}
    done_count = 0

    # Quét song song bằng ThreadPoolExecutor: mỗi coin phần lớn thời gian là CHỜ MẠNG
    # (network I/O), nên chạy song song nhiều coin cùng lúc giúp tận dụng thời gian chờ đó,
    # thay vì xếp hàng tuần tự — đây là thay đổi giúp giảm thời gian quét đáng kể.
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
        futures = {executor.submit(scan_symbol, symbol, volumes_map, btc_context): symbol for symbol in watchlist}
        for future in as_completed(futures):
            symbol = futures[future]
            done_count += 1
            try:
                result = future.result()
                signals_to_upload.update(result)
            except Exception as e:
                print(f"[⚠️ ERROR] {symbol}: {e}")

            if done_count % 20 == 0:
                print(f"[...] Đã quét {done_count}/{len(watchlist)} coin")

    elapsed = round(time.time() - start_ts, 1)

    if signals_to_upload:
        ref.set(signals_to_upload)
        by_profile = {}
        for item in signals_to_upload.values():
            by_profile[item["profile"]] = by_profile.get(item["profile"], 0) + 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in by_profile.items())
        print(f"[🔥 FIREBASE] {len(signals_to_upload)} tín hiệu trên {len(watchlist)} coin "
              f"({breakdown}) — hoàn tất sau {elapsed}s")
    else:
        ref.set({})
        print(f"[ℹ️ FIREBASE] Không có coin nào hội tụ đủ điều kiện trong {len(watchlist)} coin quét "
              f"— hoàn tất sau {elapsed}s")

    notify_new_signals(signals_to_upload)

    # Kiểm tra các lệnh đã bắn ra trước đó xem đã chạm TP/SL chưa, rồi tính lại win rate thật
    update_open_trades()
    recompute_stats()

if __name__ == "__main__":
    print("🔥 Đang bật Bot Quét Nâng Cao (ATR + Đòn bẩy đề xuất, quét song song) — 3 Khung Giao Dịch...")
    print(f"[⚙️ CONFIG] MAX_COINS={MAX_COINS} | SCAN_WORKERS={SCAN_WORKERS} | MIN_VOLUME_USDT={MIN_VOLUME_USDT:,.0f}")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    scan_and_push_to_firebase()

    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_and_push_to_firebase, 'interval', minutes=5, max_instances=1)
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
