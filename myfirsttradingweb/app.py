import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# File lưu trữ dữ liệu bền vững (JSON Database)
DATA_FILE = 'signals_history.json'
MAX_SIGNALS = 100

def load_signals():
    """Đọc dữ liệu từ file lưu trữ"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_signals(signals):
    """Ghi dữ liệu vào file lưu trữ"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi file DB: {e}")

# Load tín hiệu khi khởi động server
STORED_SIGNALS = load_signals()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/signals', methods=['GET'])
def fetch_signals():
    """API lấy danh sách tín hiệu realtime cho Frontend"""
    return jsonify({
        "status": "success",
        "total": len(STORED_SIGNALS),
        "data": STORED_SIGNALS
    })

@app.route('/api/webhook', methods=['POST'])
def receive_webhook():
    """API tiếp nhận tín hiệu chuyên sâu từ autoscreener.py"""
    global STORED_SIGNALS
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload rỗng"}), 400

        # Chuẩn hóa dữ liệu đầu vào với đầy đủ thông số
        signal_entry = {
            "id": data.get("id", int(datetime.now().timestamp())),
            "symbol": data.get("symbol", "UNKNOWN").replace('#', ''),
            "tf": data.get("tf", "M15"),
            "position": data.get("position", "LONG"),
            "entry1": data.get("entry1", "--"),
            "entry2": data.get("entry2", "--"),
            "tp": data.get("tp", "--"),
            "sl": data.get("sl", "--"),
            "leverage": data.get("leverage", "10x"),
            "risk": data.get("risk", "1.5%"),
            "status": data.get("status", "ACTIVE"),  # ACTIVE | TP1 | TP2 | SL
            "time": data.get("time", datetime.now().strftime("%H:%M:%S"))
        }

        # Đẩy tín hiệu mới lên đầu danh sách
        STORED_SIGNALS.insert(0, signal_entry)
        if len(STORED_SIGNALS) > MAX_SIGNALS:
            STORED_SIGNALS = STORED_SIGNALS[:MAX_SIGNALS]

        # Lưu lại vào file Database
        save_signals(STORED_SIGNALS)

        return jsonify({"status": "success", "message": "Đã ghi nhận tín hiệu mới"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/clear', methods=['DELETE'])
def clear_signals():
    """API xóa sạch dữ liệu cũ (Dùng khi cần Reset)"""
    global STORED_SIGNALS
    STORED_SIGNALS = []
    save_signals(STORED_SIGNALS)
    return jsonify({"status": "success", "message": "Đã xóa lịch sử tín hiệu"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
