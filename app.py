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
CSV_PATH = "/mnt/data/test_results_long.csv"
LOG_PATH = "/mnt/data/call_logs.csv"
BACKUP_DIR = "/mnt/data/backups"
BASE_URL = "https://testresults-1aja.onrender.com"

os.makedirs("/mnt/data", exist_ok=True)
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

def load_data():
    global df
    try:
        if os.path.exists(CSV_PATH):
            df = pd.read_csv(CSV_PATH)
            df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
            logger.info(f"✅ Loaded {len(df)} records from CSV")
            return True
        logger.info("No test_results_long.csv found yet")
        return False
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        return False

load_data()

def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=['Timestamp', 'CallerID', 'CallUUID', 'EnteredPIN', 'Status', 'Notes']).to_csv(LOG_PATH, index=False)
        logger.info("✅ Created new call_logs.csv")
    else:
        logger.info("call_logs.csv already exists - will append only")

init_call_log()

def log_call_to_csv(caller_id, call_uuid, entered_pin="", status="PIN Rejected", notes=""):
    try:
        new_row = pd.DataFrame([{
            'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'CallerID': caller_id,
            'CallUUID': call_uuid,
            'EnteredPIN': entered_pin,
            'Status': status,
            'Notes': notes
        }])
        new_row.to_csv(LOG_PATH, mode='a', header=False, index=False)
        logger.info(f"✅ APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"❌ Failed to append to call_logs.csv: {e}")

def speak_pin_digits(pin: str):
    return " ".join(list(pin))

def plivo_response(xml: str):
    return Response(xml, mimetype="application/xml")

def log_call(event: str, extra: dict = None):
    if extra is None: extra = {}
    call_uuid = request.values.get('CallUUID', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

# ====================== ADMIN ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return render_template_string('''
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Call Logs: {{ log_count }}</p>
        <p><a href="/upload">Upload CSV</a> | <a href="/logs">View Logs</a> | <a href="/download_logs">Download Logs</a></p>
    ''', record_count=record_count, log_count=log_count)

@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"
    logs_df = pd.read_csv(LOG_PATH).sort_values('Timestamp', ascending=False).head(200)
    return render_template_string('''
        <h2>Recent Call Logs (200 newest)</h2>
        <a href="/status">← Back</a> | <a href="/download_logs">Download Full CSV</a><br><br>
        {{ html|safe }}
        <style>table, th, td {border:1px solid black; padding:8px;}</style>
    ''', html=logs_df.to_html(index=False))

@app.route("/download_logs")
def download_logs():
    if not os.path.exists(LOG_PATH):
        return "No logs yet.", 404
    return send_file(LOG_PATH, as_attachment=True, download_name="call_logs.csv")

@app.route("/upload", methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        if request.form.get('password') != UPLOAD_PASSWORD:
            return "<h2>Wrong password</h2><a href='/upload'>Try again</a>", 401
        file = request.files.get('file')
        if file and file.filename.endswith('.csv'):
            if os.path.exists(CSV_PATH):
                shutil.copy(CSV_PATH, f"{BACKUP_DIR}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            file.save(CSV_PATH)
            load_data()
            return f"<h2>✅ Uploaded! {len(df)} records loaded.</h2><a href='/status'>Status</a>"
        return "<h2>Please upload a valid CSV</h2>", 400
    return '''
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">← Status</a>
    '''

# ====================== VOICE FLOW ======================
@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    xml = f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6" 
            digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search" 
            hints="0,1,2,3,4,5,6,7,8,9,zero,oh" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Thank you for calling the Milk Market Administrator Test Results Center. Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We didn't receive any input. Goodbye.</Speak>
</Response>'''
    return plivo_response(xml)

# ====================== PIN GATHER ======================
@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    try:
        digits = request.values.get('Digits', '').strip()
        speech = (request.values.get('SpeechResult', '') or request.values.get('Speech', '')).strip()
        raw = digits if digits else speech
        raw = raw.lower().replace("zero", "0").replace("oh", "0").replace("o", "0")
        pin = re.sub(r'\D', '', raw)
        caller = request.values.get('From', 'unknown')
        call_uuid = request.values.get('CallUUID', 'unknown')

        logger.info(f"RAW INPUT: '{raw}' | PIN: '{pin}'")

        # Accept 5-digit PINs always, else must be 6 digits
        if len(pin) == 5 or len(pin) == 6:
            active_pins[call_uuid] = {"pin": pin}
            log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Successful pin attempt")
            spoken = speak_pin_digits(pin)
            xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">You said {spoken}. Am I right?</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="GET"
            inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2"
            hints="1,2,yes,no">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
</Response>'''
            return plivo_response(xml)

        # Invalid PIN: show slow-digit retry
        logger.info("Invalid PIN detected, sending slow-digit retry prompt")
        xml = f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET"
            inputType="dtmf speech" numDigits="6" digitEndTimeout="5" speechEndTimeout="3"
            speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that.
      Please say your six digit PIN one number at a time.
      For example: one… two… three… four… five… six.
    </Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /gather_pin: {e}")
        return plivo_response(f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET"
            inputType="dtmf speech" numDigits="6" digitEndTimeout="5" speechEndTimeout="3"
            speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that.
      Please say your six digit PIN one number at a time.
      For example: one… two… three… four… five… six.
    </Speak>
  </GetInput>
</Response>''')

# ====================== CONFIRM PIN ======================
@app.route("/confirm_pin", methods=['GET'])
def confirm_pin():
    try:
        digits = request.values.get('Digits', '').strip()
        speech = (request.values.get('SpeechResult', '') or request.values.get('Speech', '')).lower()
        call_uuid = request.values.get('CallUUID')
        caller = request.values.get('From', 'unknown')

        pin = active_pins.get(call_uuid, {}).get("pin", "")
        is_yes = digits == "1" or any(w in speech for w in ["yes", "yeah", "yep", "correct", "right"])

        if not is_yes or not pin:
            logger.info("User said NO to PIN confirmation or PIN missing")
            xml = f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET"
            inputType="dtmf speech" numDigits="6" digitEndTimeout="5" speechEndTimeout="3"
            speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that.
      Please say your six digit PIN one number at a time.
      For example: one… two… three… four… five… six.
    </Speak>
  </GetInput>
</Response>'''
            return plivo_response(xml)

        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results read")
        results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')
        if results_df.empty:
            return plivo_response(f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET"
            inputType="dtmf speech" numDigits="6" digitEndTimeout="5" speechEndTimeout="3"
            speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that.
      Please say your six digit PIN one number at a time.
      For example: one… two… three… four… five… six.
    </Speak>
  </GetInput>
</Response>''')

        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Here are your milk test results.</Speak>'''
        for _, row in results_df.iterrows():
            day = int(row.get('day', 1))
            fat = float(row.get('fat', 0))
            protein = float(row.get('protein', 0))
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
    <prosody rate="medium">Munn {mun}.</prosody>
  </Speak>'''

        xml += f'''
  <GetInput action="{BASE_URL}/handle_action" method="GET"
            inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2"
            hints="1,2,repeat,yes,no,goodbye,end">
    <Speak voice="Polly.Joanna" language="en-US">
      To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /confirm_pin: {e}")
        return plivo_response(f'''<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET"
            inputType="dtmf speech" numDigits="6" digitEndTimeout="5" speechEndTimeout="3"
            speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that.
      Please say your six digit PIN one number at a time.
      For example: one… two… three… four… five… six.
    </Speak>
  </GetInput>
</Response>''')

# ====================== HANDLE ACTION ======================
@app.route("/handle_action", methods=['GET'])
def handle_action():
    try:
        digits = request.values.get('Digits', '').strip()
        speech = (request.values.get('SpeechResult', '') or request.values.get('Speech', '')).lower()
        call_uuid = request.values.get('CallUUID')
        caller = request.values.get('From', 'unknown')
        pin = active_pins.get(call_uuid, {}).get("pin", "")

        logger.info(f"User action input: Digits='{digits}' | Speech='{speech}' | PIN='{pin}'")

        # Repeat results
        if digits == "1" or any(w in speech for w in ["repeat", "yes"]):
            log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results repeated")
            xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Repeating the results.</Speak>
  <Redirect method="GET">{BASE_URL}/confirm_pin</Redirect>
</Response>'''
            return plivo_response(xml)

        # End call
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Call ended")
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
  <Hangup/>
</Response>'''
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /handle_action: {e}")
        return plivo_response(f'''<Response>
  <GetInput action="{BASE_URL}/handle_action" method="GET"
            inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2"
            hints="1,2,repeat,yes,no,goodbye,end">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that. To hear your results again, say repeat or press 1. To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
</Response>''')

# ====================== HANGUP ======================
@app.route("/hangup", methods=['POST'])
def hangup():
    call_uuid = request.values.get('CallUUID')
    pin = active_pins.get(call_uuid, {}).get("pin", "")
    caller = request.values.get('From', 'unknown')
    status = "PIN Accepted" if pin and len(pin) >= 5 else "PIN Rejected"
    logger.info(f"Call hung up - PIN={pin} Status={status}")
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")
    return Response("<Response></Response>", mimetype="application/xml")

# ====================== RUN APP ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)