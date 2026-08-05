import os
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = 'database.db'

# Định nghĩa Múi Giờ Việt Nam (GMT+7)
VN_TZ = timezone(timedelta(hours=7))

def get_vn_now_str():
    """Hàm lấy thời gian hiện tại theo Giờ Việt Nam (YYYY-MM-DD HH:MM:SS)"""
    return datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    """Khởi tạo Database SQLite"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            tf TEXT NOT NULL,
            position TEXT NOT NULL,
            entry1 TEXT NOT NULL,
            entry2 TEXT NOT NULL,
            tp TEXT NOT NULL,
            sl TEXT NOT NULL,
            leverage TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_id ON signals(id DESC)')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/signals', methods=['GET'])
def fetch_signals():
    """API Truy xuất 100 tín hiệu mới nhất kèm thời gian Giờ Việt Nam"""
    try:
        conn = get_db_connection()
        signals = conn.execute('SELECT * FROM signals ORDER BY id DESC LIMIT 100').fetchall()
        conn.close()
        
        signal_list = []
        for s in signals:
            created_str = str(s['created_at'])
            # Tách riêng phần Giờ:Phút:Giây (Ví dụ: 17:45:12)
            time_display = created_str.split(' ')[1] if ' ' in created_str else created_str
            
            signal_list.append({
                "id": s['id'],
                "symbol": s['symbol'],
                "tf": s['tf'],
                "position": s['position'],
                "entry1": s['entry1'],
                "entry2": s['entry2'],
                "tp": s['tp'],
                "sl": s['sl'],
                "leverage": s['leverage'],
                "risk": s['risk'],
                "status": s['status'],
                "time": time_display,
                "full_date": created_str
            })
            
        return jsonify({"status": "success", "total": len(signal_list), "data": signal_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/webhook', methods=['POST'])
def receive_webhook():
    """API Nhận tín hiệu từ Bot - Đóng dấu chính xác Giờ Việt Nam"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload empty"}), 400

        # Lấy thời gian chuẩn Việt Nam
        vn_time_now = get_vn_now_str()

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO signals (symbol, tf, position, entry1, entry2, tp, sl, leverage, risk, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get("symbol", "BTCUSDT").replace('#', '').upper(),
            data.get("tf", "M15"),
            data.get("position", "LONG"),
            data.get("entry1", "--"),
            data.get("entry2", "--"),
            data.get("tp", "--"),
            data.get("sl", "--"),
            data.get("leverage", "50x - 200x"),
            data.get("risk", "Chia Vol 40/60"),
            data.get("status", "ACTIVE"),
            vn_time_now
        ))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": f"Đã lưu tín hiệu lúc {vn_time_now} (GMT+7)"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
