from flask import Flask, request, Response, render_template_string
import plivo
from plivo import plivoxml
import pandas as pd
import os
import logging
import shutil
from datetime import datetime

app = Flask(__name__)

# ====================== CONFIG ======================
UPLOAD_PASSWORD = "ForUSDA!2026"
CSV_PATH = "test_results_long.csv"
BACKUP_DIR = "backups"

os.makedirs(BACKUP_DIR, exist_ok=True)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

active_pins = {}
df = pd.DataFrame()
last_upload_time = "Never"

def load_data():
    global df, last_upload_time
    try:
        if os.path.exists(CSV_PATH):
            df = pd.read_csv(CSV_PATH)
            df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
            last_upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"✅ Loaded {len(df)} records")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        return False

load_data()

def speak_pin_digits(pin: str):
    return " ".join(list(pin))

def plivo_response(resp: plivoxml.ResponseElement):
    return Response(resp.to_string(), mimetype="application/xml")

def log_call(event: str, extra: dict = None):
    if extra is None: extra = {}
    call_uuid = request.values.get('CallUUID', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

# ====================== ADMIN PAGES ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    return render_template_string('''
        <!DOCTYPE html>
        <html><head><title>MMA System Status</title></head>
        <body style="font-family: Arial; margin: 40px;">
            <h2>Milk Market Administrator - System Status</h2>
            <p><strong>Current Records:</strong> {{ record_count }}</p>
            <p><strong>Last Data Upload:</strong> {{ last_upload_time }}</p>
            <hr><p><a href="/upload">Upload New Data File</a></p>
        </body></html>
    ''', record_count=record_count, last_upload_time=last_upload_time)

@app.route("/upload", methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        if request.form.get('password', '').strip() != UPLOAD_PASSWORD:
            return "<h2>❌ Incorrect Password</h2><p><a href='/upload'>Try again</a></p>", 401

        file = request.files.get('file')
        if not file or file.filename == '' or not file.filename.lower().endswith('.csv'):
            return "<h2>❌ Please upload a valid .csv file</h2>", 400

        if os.path.exists(CSV_PATH):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(CSV_PATH, f"{BACKUP_DIR}/test_results_long_{timestamp}.csv")

        file.save(CSV_PATH)
        logger.info("New CSV uploaded")
        load_data()
        return f"<h2>✅ Upload Successful! Loaded {len(df)} records.</h2><p><a href='/upload'>Upload another</a> | <a href='/status'>Status</a></p>"

    record_count = len(df) if not df.empty else 0
    return render_template_string('''
        <!DOCTYPE html>
        <html><head><title>MMA Data Upload</title></head>
        <body style="font-family: Arial; max-width: 600px; margin: 40px auto;">
            <h2>Milk Market Administrator - Data Upload</h2>
            <p><strong>Password:</strong> ForUSDA!2026</p>
            <form method="post" enctype="multipart/form-data">
                <p>Password: <input type="password" name="password" required></p>
                <p>File: <input type="file" name="file" accept=".csv" required></p>
                <button type="submit">Upload CSV</button>
            </form>
            <p>Current records: <strong>{{ record_count }}</strong></p>
            <p><a href="/status">View Status</a></p>
        </body></html>
    ''', record_count=record_count)

# ====================== VOICE ROUTES - SIMPLIFIED & FIXED ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    response = plivoxml.ResponseElement()

    # Simple welcome + GetInput
    get_input = plivoxml.GetInputElement(
        action="/gather_pin",
        method="POST",
        input_type="dtmf speech",
        num_digits=6,
        digit_end_timeout=5,
        speech_end_timeout=2,
        redirect=True,
        language="en-US"
    )

    get_input.add(plivoxml.SpeakElement(
        "Thank you for calling the Milk Market Administrator Test Results Center. Please enter your 6 digit PIN.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)

    # Fallback
    response.add(plivoxml.SpeakElement(
        "We didn't receive any input. Goodbye.",
        voice="Polly.Joanna", language="en-US"
    ))

    return plivo_response(response)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    # ... (I'll keep this part minimal for now — add back your full logic after we confirm the call connects)
    log_call("GATHER_PIN")
    digits = request.values.get('Digits', '')
    speech = request.values.get('SpeechResult', '')

    response = plivoxml.ResponseElement()
    response.add(plivoxml.SpeakElement("Thank you. Processing your PIN.", voice="Polly.Joanna", language="en-US"))
    response.add(plivoxml.HangupElement())

    return plivo_response(response)


# Keep your other routes (/confirm_pin, /handle_action, admin) if you want, but first test with this minimal version.

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)