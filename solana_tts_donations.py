import os
import time
import re
import json
from flask import Flask, send_from_directory, jsonify, make_response
from flask_cors import CORS
from gtts import gTTS
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from threading import Thread

app = Flask(__name__)
CORS(app)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

SOUNDS_DIR = os.path.join("static", "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
QUEUE_FILE = os.path.join(SOUNDS_DIR, "queue.json")
LAST_SIG_FILE = os.path.join(SOUNDS_DIR, "last_signature.txt")

WALLET_ADDRESS = Pubkey.from_string("C4DxRkRkFYrNRrM7v1gySrFNonBhKjHM4Cp7YYNtruYo")
client = Client("https://mainnet.helius-rpc.com/?api-key=e47fb6f4-d046-4ef2-af41-85617d529986")
seen_signatures = set()

def monitor_wallet():
    # Wczytaj ostatni podpis, jeśli istnieje, by nie czytać starych donejtów po restarcie
    last_signature = None
    if os.path.exists(LAST_SIG_FILE):
        with open(LAST_SIG_FILE, "r") as f:
            last_signature = f.read().strip()

    while True:
        try:
            txs = client.get_signatures_for_address(WALLET_ADDRESS, limit=10).value
            new_txs = []
            for tx in txs:
                sig = tx.signature
                if sig in seen_signatures:
                    continue
                if last_signature and sig == last_signature:
                    break
                new_txs.append(tx)
            if new_txs:
                # najstarszy najpierw
                new_txs = list(reversed(new_txs))
            donation_entries = []
            for tx in new_txs:
                sig = tx.signature
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
                    # Memo w formacie: "user message"
                    parts = memo.split(" ", 1)
                    if len(parts) == 2:
                        user, message_text = parts
                    else:
                        user = "anonymous"
                        message_text = memo

                    sol_amount = round(amount / 1e9, 4)
                    tts_text = f"{sol_amount} SOL {user} says {message_text}"
                    timestamp = int(time.time())
                    # Ustal nazwę pliku: [kwota]_SOL_[user]_says_[message]_[timestamp].mp3
                    safe_user = re.sub(r'[^a-zA-Z0-9._-]', '_', user)
                    safe_msg = re.sub(r'[^a-zA-Z0-9._-]', '_', message_text)
                    filename = f"{sol_amount}_SOL_{safe_user}_says_{safe_msg}_{timestamp}.mp3"
                    path = os.path.join(SOUNDS_DIR, filename)

                    try:
                        tts = gTTS(text=tts_text, lang='en')
                        tts.save(path)
                        print(f"💾 Saved TTS: {filename}")
                    except Exception as e:
                        print("❌ Failed to save TTS:", e)
                        continue

                    donation_entry = {
                        "text": tts_text,
                        "audio": filename
                    }
                    donation_entries.append(donation_entry)
                # Zapisujemy ostatni przetworzony podpis
                last_signature = sig
                with open(LAST_SIG_FILE, "w") as f:
                    f.write(last_signature)

            # Wczytaj dotychczasową kolejkę i dodaj nowe donejty
            if donation_entries:
                queue = []
                if os.path.exists(QUEUE_FILE):
                    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                        try:
                            queue = json.load(f)
                        except Exception:
                            queue = []
                queue.extend(donation_entries)
                with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                    json.dump(queue, f, ensure_ascii=False)

            time.sleep(5)
        except Exception as e:
            print("⚠️ Error:", repr(e))
            time.sleep(5)

@app.route("/queue.json")
def queue_json():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = f.read()
    else:
        data = "[]"
    resp = make_response(data)
    resp.mimetype = "application/json"
    return resp

@app.route("/sounds/<filename>")
def serve_sound(filename):
    return send_from_directory(SOUNDS_DIR, filename)

@app.route("/")
def home():
    return send_from_directory("static", "donation_player.html")

if __name__ == "__main__":
    Thread(target=monitor_wallet, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
