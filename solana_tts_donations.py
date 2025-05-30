import os
import time
import re
import json
import datetime
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
from gtts import gTTS
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from threading import Thread

app = Flask(__name__)
CORS(app)

SOUNDS_DIR = os.path.join("static", "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
LATEST_JSON = os.path.join(SOUNDS_DIR, "latest.json")
GOAL_JSON = os.path.join("static", "goal.json")

WALLET_ADDRESS = Pubkey.from_string("C4DxRkRkFYrNRrM7v1gySrFNonBhKjHM4Cp7YYNtruYo")
client = Client("https://mainnet.helius-rpc.com/?api-key=e47fb6f4-d046-4ef2-af41-85617d529986")
seen_signatures = set()

def monitor_wallet():
    while True:
        try:
            print("🔍 Checking for new transactions...")
            txs = client.get_signatures_for_address(WALLET_ADDRESS, limit=5).value
            for tx in txs:
                sig = tx.signature
                if sig in seen_signatures:
                    continue

                seen_signatures.add(sig)
                tx_data = client.get_transaction(sig, encoding="jsonParsed").value
                if not tx_data:
                    continue

                transaction = tx_data.transaction
                message = transaction.transaction.message
                instructions = message.instructions

                memo = None
                amount = 0

                for ix in instructions:
                    if hasattr(ix, "program") and ix.program == "spl-memo":
                        if hasattr(ix, "parsed") and isinstance(ix.parsed, str):
                            memo = ix.parsed
                    if hasattr(ix, "program") and ix.program == "system":
                        if hasattr(ix, "parsed") and isinstance(ix.parsed, dict):
                            if ix.parsed.get("type") == "transfer":
                                info = ix.parsed.get("info", {})
                                try:
                                    amount = int(info.get("lamports", 0))
                                except:
                                    amount = 0

                if memo and amount >= 1000000:
                    cleaned_memo = memo.strip()

                    # Extract username and message after first "says", skip SOL amount and dots.
                    match = re.split(r"\s*says\s*\.{0,}", cleaned_memo, maxsplit=1, flags=re.IGNORECASE)
                    if len(match) == 2:
                        user = match[0].strip(" .")
                        message_text = match[1].strip(" .")
                        user = re.sub(r"^[\d\.,\s]*SOL[\s\.,]*", "", user, flags=re.IGNORECASE)
                        user = user.strip(" .")
                    else:
                        user = "anonymous"
                        message_text = cleaned_memo

                    sol_amount = round(amount / 1e9, 4)
                    tts_text = f"{sol_amount} SOL {user} says {message_text}"
                    safe_user = re.sub(r'[^a-zA-Z0-9._-]', '_', user)
                    safe_msg = re.sub(r'[^a-zA-Z0-9._-]', '_', message_text)
                    filename = f"{sol_amount}_SOL_{safe_user}_says_{safe_msg}_{int(time.time())}.mp3"
                    path = os.path.join(SOUNDS_DIR, filename)

                    try:
                        tts = gTTS(text=tts_text, lang='en')
                        tts.save(path)
                        print(f"💾 Saved TTS: {filename}")
                    except Exception as e:
                        print("❌ Failed to save TTS:", e)
                        continue

                    with open(LATEST_JSON, "w", encoding="utf-8") as f:
                        json.dump({"filename": filename, "text": tts_text}, f, ensure_ascii=False)

            time.sleep(5)
        except Exception as e:
            print("⚠️ Error:", repr(e))
            time.sleep(5)

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory('static', filename)

@app.route("/sounds/<filename>")
def serve_sound(filename):
    return send_from_directory(SOUNDS_DIR, filename)

@app.route("/latest_donation")
def latest_donation():
    if os.path.exists(LATEST_JSON):
        with open(LATEST_JSON, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route("/")
def home():
    return send_from_directory("static", "donation_player.html")

# ---- IMPROVED /donations ENDPOINT ----
@app.route('/donations')
def donations():
    donations = []
    if os.path.isdir(SOUNDS_DIR):
        for filename in sorted(os.listdir(SOUNDS_DIR), reverse=True):
            if not filename.endswith('.mp3'):
                continue
            name = filename[:-4]
            match = re.match(r"^([0-9.]+)_SOL_(.+)_says_(.+)_(\d+)$", name)
            if not match:
                continue
            sol_amount = match.group(1)
            user = match.group(2).replace('_', ' ')
            message = match.group(3).replace('_', ' ')
            timestamp = int(match.group(4))
            date_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

            donations.append({
                "filename": filename,
                "amount": sol_amount,
                "user": user,
                "text": message,
                "timestamp": timestamp,
                "date": date_str,
            })
    return jsonify(donations)
# ---- END IMPROVED ENDPOINT ----

# ---- ENDPOINT TO DELETE ALL MP3s ----
@app.route('/delete_all_mp3')
def delete_all_mp3():
    import glob
    files = glob.glob(os.path.join(SOUNDS_DIR, '*.mp3'))
    for f in files:
        os.remove(f)
    return jsonify({"status": "deleted", "count": len(files)})
# ---- END DELETE ENDPOINT ----

# ---- DONATION GOAL ENDPOINT (NEW) ----
@app.route('/donation_goal', methods=['GET', 'POST'])
def donation_goal():
    if request.method == 'POST':
        data = request.json
        try:
            goal_amount = float(data.get("amount", 0))
            goal_desc = data.get("desc", "")
        except Exception:
            return jsonify({"status": "error", "msg": "Invalid input"}), 400
        with open(GOAL_JSON, "w", encoding="utf-8") as f:
            json.dump({"amount": goal_amount, "desc": goal_desc}, f, ensure_ascii=False)
        return jsonify({"status": "ok"})
    else:
        if os.path.exists(GOAL_JSON):
            with open(GOAL_JSON, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify({"amount": 0, "desc": ""})
# ---- END DONATION GOAL ENDPOINT ----

# ---- RESET DONATION PROGRESS ENDPOINT ----
@app.route('/reset_donation_goal', methods=['POST'])
def reset_donation_goal():
    if os.path.exists(GOAL_JSON):
        try:
            with open(GOAL_JSON, "r", encoding="utf-8") as f:
                goal = json.load(f)
        except:
            goal = {"amount": 0, "desc": ""}
    else:
        goal = {"amount": 0, "desc": ""}
    goal['progress'] = 0
    with open(GOAL_JSON, "w", encoding="utf-8") as f:
        json.dump(goal, f, ensure_ascii=False)
    return jsonify({"status": "reset", "goal": goal})
# ---- END RESET DONATION PROGRESS ENDPOINT ----

if __name__ == "__main__":
    Thread(target=monitor_wallet, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)