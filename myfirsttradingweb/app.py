import os
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Bộ nhớ đệm lưu trữ tối đa 100 tín hiệu mới nhất
MAX_SIGNALS = 100
STORED_SIGNALS = []

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/signals', methods=['GET'])
def fetch_signals():
    """API cho Frontend lấy danh sách tín hiệu"""
    return jsonify({
        "status": "success",
        "total": len(STORED_SIGNALS),
        "data": STORED_SIGNALS
    })

@app.route('/api/webhook', methods=['POST'])
def receive_webhook():
    """API tiếp nhận tín hiệu từ autoscreener.py"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload rỗng"}), 400

        # Đẩy tín hiệu mới lên đầu danh sách
        STORED_SIGNALS.insert(0, data)
        if len(STORED_SIGNALS) > MAX_SIGNALS:
            STORED_SIGNALS.pop()

        return jsonify({"status": "success", "message": "Đã ghi nhận tín hiệu"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
