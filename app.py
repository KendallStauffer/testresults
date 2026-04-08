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

# ←←← CHANGE THIS TO YOUR ACTUAL RENDER URL
BASE_URL = "https://YOUR-APP-NAME.onrender.com"

os.makedirs(BACKUP_DIR, exist_ok=True)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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

def plivo_response(resp: plivoxml.ResponseElement):
    return Response(resp.to_string(), mimetype="application/xml")

def log_call(event: str, extra=None):
    if extra is None: extra = {}
    call_uuid = request.values.get('CallUUID', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

# ====================== ADMIN (simple) ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    return render_template_string('''
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Last Upload: {{ last_upload_time }}</p>
        <p><a href="/upload">Upload CSV</a></p>
    ''', record_count=record_count, last_upload_time=last_upload_time)

@app.route("/upload", methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        if request.form.get('password', '').strip() != UPLOAD_PASSWORD:
            return "<h2>❌ Wrong Password</h2><p><a href='/upload'>Try again</a></p>", 401
        file = request.files.get('file')
        if not file or not file.filename.lower().endswith('.csv'):
            return "<h2>❌ Upload valid CSV</h2>", 400
        if os.path.exists(CSV_PATH):
            shutil.copy(CSV_PATH, f"{BACKUP_DIR}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        file.save(CSV_PATH)
        load_data()
        return f"<h2>✅ Success! Loaded {len(df)} records.</h2><p><a href='/upload'>Upload again</a> | <a href='/status'>Status</a></p>"
    return '''
        <h2>MMA Upload</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password" required><br><br>
            CSV: <input type="file" name="file" accept=".csv" required><br><br>
            <button type="submit">Upload</button>
        </form>
        <p><a href="/status">Status</a></p>
    '''

# ====================== SIMPLE VOICE - KEYPAD ONLY ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    response = plivoxml.ResponseElement()

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/gather_pin",
        method="GET",
        input_type="dtmf",
        num_digits=6,
        digit_end_timeout=10,      # Increased time
        finish_on_key="#",
        timeout=15                 # Overall timeout
    )

    get_input.add(plivoxml.SpeakElement(
        "Thank you for calling. Please enter your 6 digit PIN, then press the pound key.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)

    response.add(plivoxml.SpeakElement(
        "No input received. Goodbye.",
        voice="Polly.Joanna", language="en-US"
    ))

    return plivo_response(response)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    call_uuid = request.values.get('CallUUID')

    logger.info(f"<<< GATHER_PIN CALLED >>> Digits received: '{digits}'")

    log_call("PIN_ATTEMPT", {"digits": digits})

    response = plivoxml.ResponseElement()

    if len(digits) != 6:
        response.add(plivoxml.SpeakElement(
            "Sorry, we need exactly 6 digits. Please try again.",
            voice="Polly.Joanna", language="en-US"
        ))
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf",
            num_digits=6,
            digit_end_timeout=10,
            finish_on_key="#"
        )
        get_input.add(plivoxml.SpeakElement("Enter your 6 digit PIN followed by pound.", voice="Polly.Joanna", language="en-US"))
        response.add(get_input)
        return plivo_response(response)

    # Success - PIN received
    logger.info(f"PIN ACCEPTED: {digits}")
    log_call("PIN_ACCEPTED", {"pin": digits})

    response.add(plivoxml.SpeakElement(
        f"Thank you. You entered { ' '.join(digits) }.",
        voice="Polly.Joanna", language="en-US"
    ))
    response.add(plivoxml.SpeakElement("Goodbye for now.", voice="Polly.Joanna", language="en-US"))
    response.add(plivoxml.HangupElement())

    return plivo_response(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)