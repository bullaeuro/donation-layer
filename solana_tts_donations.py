import os
import time
import re
import json
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from gtts import gTTS
from solana.rpc.api import Client
from solders.pubkey import Pubkey

app = Flask(__name__)
CORS(app)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

SOUNDS_DIR = os.path.join("static", "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
LATEST_JSON = os.path.join(SOUNDS_DIR, "latest.json")

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
                    print("📦 INSTRUCTION DUMP:", ix)
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

                print(f"📓 Signature: {sig}")
                print(f"📜 Memo: {memo}")
                print(f"💰 Amount: {amount}")

                if memo and amount >= 1000000:
                    readable = memo
                    safe_memo = re.sub(r'[^a-zA-Z0-9._-]', '_', readable.replace(" ", "_"))
                    filename = f"tts_{int(time.time())}__{safe_memo}.mp3"
                    path = os.path.join(SOUNDS_DIR, filename)
                    print(f"🔊 New donation with memo: {readable}")

                    try:
                        tts = gTTS(text=readable, lang='en')
                        tts.save(path)

                        with open(LATEST_JSON, "w", encoding="utf-8") as f:
                            json.dump({"filename": filename, "text": readable}, f, ensure_ascii=False)

                        print(f"💾 Saved latest.json with: {readable}")
                    except Exception as e:
                        print("❌ Failed to save TTS or latest.json:", e)
                        continue

            time.sleep(5)
        except Exception as e:
            print("⚠️ Error:", repr(e))
            time.sleep(5)

@app.route("/sounds")
def list_sounds():
    files = sorted(f for f in os.listdir(SOUNDS_DIR) if f.endswith(".mp3"))
    return jsonify(files)

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

if __name__ == "__main__":
    from threading import Thread
    Thread(target=monitor_wallet, daemon=True).start()
    app.run(debug=True, port=5000)
