from flask import Flask, request, Response, render_template_string, send_file
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime

app = Flask(__name__)

# ====================== CONFIG ======================
UPLOAD_PASSWORD = "ForUSDA!2026"
CSV_PATH = "test_results_long.csv"
LOG_PATH = "call_logs.csv"
BACKUP_DIR = "backups"

BASE_URL = "https://testresults-1aja.onrender.com"

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

def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=['Timestamp', 'CallerID', 'CallUUID', 'EnteredPIN', 'Success', 'Notes']).to_csv(LOG_PATH, index=False)
        logger.info("✅ Created call_logs.csv")

init_call_log()

def log_call_to_csv(caller_id, call_uuid, entered_pin="", success=False, notes=""):
    try:
        new_row = pd.DataFrame([{
            'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'CallerID': caller_id,
            'CallUUID': call_uuid,
            'EnteredPIN': entered_pin,
            'Success': success,
            'Notes': notes
        }])
        new_row.to_csv(LOG_PATH, mode='a', header=False, index=False)
        logger.info(f"✅ Logged call: PIN={entered_pin}, Success={success}")
    except Exception as e:
        logger.error(f"❌ Failed to log call: {e}")

def speak_pin_digits(pin: str):
    return " ".join(list(pin))

def plivo_response(xml_string: str):
    return Response(xml_string, mimetype="application/xml")

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
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return render_template_string('''
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Call Logs: {{ log_count }}</p>
        <p>Last Upload: {{ last_upload_time }}</p>
        <p><a href="/upload">Upload CSV</a></p>
        <p><a href="/logs">View Call Logs</a></p>
        <p><a href="/download_logs">Download Call Logs</a></p>
    ''', record_count=record_count, log_count=log_count, last_upload_time=last_upload_time)

@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"
    logs_df = pd.read_csv(LOG_PATH).sort_values('Timestamp', ascending=False).head(200)
    html_table = logs_df.to_html(classes="table table-striped", index=False, escape=False)
    return render_template_string('''
        <h2>Recent Call Logs (Newest First)</h2>
        <p><a href="/status">← Back</a> | <a href="/download_logs">Download CSV</a></p>
        {{ table|safe }}
        <style>table {border-collapse: collapse; width:100%;} th, td {border:1px solid #ddd; padding:8px;}</style>
    ''', table=html_table)

@app.route("/download_logs")
def download_logs():
    if not os.path.exists(LOG_PATH):
        return "No logs yet.", 404
    return send_file(LOG_PATH, as_attachment=True, download_name="call_logs.csv")

@app.route("/upload", methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        if request.form.get('password', '').strip() != UPLOAD_PASSWORD:
            return "<h2>❌ Incorrect Password</h2><p><a href='/upload'>Try again</a></p>", 401
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

# ====================== VOICE ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    xml = f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" digitEndTimeout="8" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Thank you for calling the Milk Market Administrator Test Results Center. Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We didn't receive any input. Goodbye.</Speak>
</Response>'''
    return plivo_response(xml)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip() or request.values.get('Speech', '').strip()
    raw = digits if digits else speech
    pin = re.sub(r'\D', '', raw)

    log_call("PIN_ATTEMPT", {"raw": raw, "cleaned_pin": pin})
    log_call_to_csv(request.values.get('From', 'unknown'), request.values.get('CallUUID', 'unknown'), pin, len(pin)==6)

    if len(pin) != 6:
        xml = f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" digitEndTimeout="8" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Sorry, I didn't get 6 digits. Please say or enter your 6 digit PIN again.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    active_pins[request.values.get('CallUUID', 'unknown')] = {"pin": pin}

    spoken = speak_pin_digits(pin)
    xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">You said {spoken}. Am I right?</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="GET" inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1 for yes. Say no or press 2 for no.</Speak>
  </GetInput>
</Response>'''
    return plivo_response(xml)


@app.route("/confirm_pin", methods=['GET'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower() or request.values.get('Speech', '').strip().lower()
    call_uuid = request.values.get('CallUUID')

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])

    if not is_yes:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Okay, let's try again.</Speak>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" digitEndTimeout="8" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    pin = active_pins.get(call_uuid, {}).get("pin")
    if not pin:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Sorry, something went wrong. Please start over.</Speak>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" digitEndTimeout="8" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    log_call_to_csv(request.values.get('From', 'unknown'), call_uuid, pin, True, "Results delivered")

    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Sorry, no results were found for that PIN.</Speak>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" digitEndTimeout="8" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    # Build raw XML with proper SSML
    xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Here are your milk test results.</Speak>'''

    for _, row in results_df.iterrows():
        day = int(row.get('day', 1))
        fat = row.get('fat', 0)
        protein = row.get('protein', 0)
        scc = int(row.get('scc', 0))
        mun = int(row.get('mun', 0))

        xml += f'''
  <Speak voice="Polly.Joanna" language="en-US">
    <prosody rate="medium">
Sample from the {day}th.
<break time="600ms"/>
Butterfat {fat} percent.
<break time="600ms"/>
Protein {protein} percent.
<break time="600ms"/>
Somatic cell count {scc:,}.
<break time="600ms"/>
    </prosody>
  </Speak>'''

        if mun > 0:
            xml += f'''
  <Speak voice="Polly.Joanna" language="en-US">
    <prosody rate="medium">
Munn {mun}.
<break time="600ms"/>
    </prosody>
  </Speak>'''

    xml += f'''
  <GetInput action="{BASE_URL}/handle_action" method="GET" inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.</Speak>
  </GetInput>
</Response>'''

    return plivo_response(xml)


@app.route("/handle_action", methods=['GET'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower() or request.values.get('Speech', '').strip().lower()
    log_call("FINAL_ACTION", {"choice": speech or digits})

    if digits == "1" or "repeat" in speech:
        # For repeat, we can redirect back to confirm_pin or duplicate the results XML
        # Here we redirect to confirm_pin for simplicity (it will re-read results)
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Repeating the results.</Speak>
  <Redirect method="GET">{BASE_URL}/confirm_pin</Redirect>
</Response>'''
        return plivo_response(xml)

    else:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
  <Hangup/>
</Response>'''
        return plivo_response(xml)


@app.route("/hangup", methods=['POST'])
def hangup():
    log_call("CALL_HANGUP")
    log_call_to_csv(request.values.get('From', 'unknown'), request.values.get('CallUUID', 'unknown'), "", False, "Caller hung up")
    return Response("<Response></Response>", mimetype="application/xml")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)