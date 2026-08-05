import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = 'database.db'

def init_db():
    """Khởi tạo SQLite Database với Index để tối ưu tốc độ truy vấn"""
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Tối ưu hóa: Tạo Index giúp load 100 tín hiệu mới nhất cực nhanh (0ms)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_id ON signals(id DESC)')
    conn.commit()
    conn.close()

# Khởi tạo DB khi chạy app
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
    """API Lấy danh sách 100 tín hiệu mới nhất"""
    try:
        conn = get_db_connection()
        signals = conn.execute('SELECT * FROM signals ORDER BY id DESC LIMIT 100').fetchall()
        conn.close()
        
        signal_list = []
        for s in signals:
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
                "time": s['created_at'].split(' ')[1] if ' ' in str(s['created_at']) else datetime.now().strftime("%H:%M:%S")
            })
            
        return jsonify({"status": "success", "total": len(signal_list), "data": signal_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/webhook', methods=['POST'])
def receive_webhook():
    """API tiếp nhận tín hiệu từ Bot Screener"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload empty"}), 400

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO signals (symbol, tf, position, entry1, entry2, tp, sl, leverage, risk, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get("symbol", "BTCUSDT").replace('#', '').upper(),
            data.get("tf", "M15"),
            data.get("position", "LONG"),
            data.get("entry1", "--"),
            data.get("entry2", "--"),
            data.get("tp", "--"),
            data.get("sl", "--"),
            data.get("leverage", "20x - 100x+"),
            data.get("risk", "Tùy chỉnh Vol"),
            data.get("status", "ACTIVE")
        ))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": "Đã lưu tín hiệu vào Database"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/calculate-risk', methods=['POST'])
def calculate_risk():
    """API Tính toán Margin và Position Size theo vốn"""
    try:
        data = request.get_json()
        account_balance = float(data.get('account_balance', 1000))
        risk_percent = float(data.get('risk_percent', 2.0))
        entry_price = float(data.get('entry_price', 0))
        sl_price = float(data.get('sl_price', 0))
        leverage = float(data.get('leverage', 20))

        if entry_price <= 0 or sl_price <= 0 or entry_price == sl_price:
            return jsonify({"status": "error", "message": "Giá không hợp lệ"}), 400

        price_diff_ratio = abs(entry_price - sl_price) / entry_price
        max_risk_amount = account_balance * (risk_percent / 100.0)
        total_position_size = max_risk_amount / price_diff_ratio
        required_margin = total_position_size / leverage

        return jsonify({
            "status": "success",
            "data": {
                "max_risk_amount": round(max_risk_amount, 2),
                "total_position_size": round(total_position_size, 2),
                "required_margin": round(required_margin, 2)
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
