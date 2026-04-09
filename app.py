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
        pd.DataFrame(columns=['Timestamp', 'CallerID', 'CallUUID', 'EnteredPIN', 'Status', 'Notes']).to_csv(LOG_PATH, index=False)
        logger.info("✅ Created call_logs.csv - will ONLY append")
    else:
        logger.info("call_logs.csv exists - appending only")

init_call_log()

def log_call_to_csv(caller_id, call_uuid, entered_pin="", status="PIN Rejected", notes=""):
    try:
        clean_pin = str(entered_pin).rstrip('0').rstrip('.') if '.' in str(entered_pin) else str(entered_pin)
        new_row = pd.DataFrame([{
            'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'CallerID': caller_id,
            'CallUUID': call_uuid,
            'EnteredPIN': clean_pin,
            'Status': status,
            'Notes': notes
        }])
        new_row.to_csv(LOG_PATH, mode='a', header=False, index=False)
        logger.info(f"✅ APPENDED TO CSV: PIN={clean_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"❌ Failed to append to call_logs.csv: {e}")

def speak_pin_digits(pin: str):
    return " ".join(list(str(pin).rstrip('0').rstrip('.')))

def plivo_response(xml: str):
    return Response(xml, mimetype="application/xml")

def log_call(event: str, extra: dict = None):
    if extra is None: extra = {}
    call_uuid = request.values.get('CallUUID', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

# ====================== VOICE FLOW ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    xml = f'''<Response>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
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
    logger.info(f"RAW SPEECH RECEIVED: '{raw}'")

    pin = re.sub(r'\D', '', raw)
    logger.info(f"After basic clean: '{pin}' (len={len(pin)}, zeros={pin.count('0')})")

    caller = request.values.get('From', 'unknown')
    call_uuid = request.values.get('CallUUID', 'unknown')

    # ZERO CONDITION FIRST
    if len(pin) > 6 and '0' in pin:
        logger.info("ZERO CONDITION MET → playing O vs zero message")
        log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", "Failed pin attempt - zero heavy")
        
        xml = f'''<Response>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">Sorry, I didn't get exactly 6 digits. For some reason I am better at hearing the letter O than the word zero. Please try again using O for zeros.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    # Normal failed PIN
    if len(pin) != 6:
        logger.info(f"Normal failed PIN (length {len(pin)})")
        log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", "Failed pin attempt")
        xml = f'''<Response>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">Sorry, I didn't get 6 digits. Please try again.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    # Successful PIN
    logger.info(f"SUCCESSFUL PIN: {pin}")
    active_pins[call_uuid] = {"pin": pin}
    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Successful pin attempt - results read")

    spoken = speak_pin_digits(pin)
    xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Am I right with {spoken}?</Speak>
  <GetInput action="/confirm_pin" inputType="dtmf speech" numDigits="1" 
             digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
</Response>'''
    return plivo_response(xml)


@app.route("/confirm_pin", methods=['GET'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = (request.values.get('SpeechResult', '') or request.values.get('Speech', '')).lower()
    call_uuid = request.values.get('CallUUID')

    is_yes = digits == "1" or any(w in speech for w in ["yes", "yeah", "yep", "correct", "right"])

    if not is_yes:
        logger.info("User said NO - going straight to PIN prompt")
        xml = f'''<Response>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    pin = active_pins.get(call_uuid, {}).get("pin")
    if not pin:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Sorry, something went wrong. Please start over.</Speak>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

    logger.info(f"User confirmed PIN {pin} - reading results")
    log_call_to_csv(request.values.get('From', 'unknown'), call_uuid, pin, "PIN Accepted", "Results read")

    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')
    if results_df.empty:
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">No results found for that PIN.</Speak>
  <GetInput action="/gather_pin" inputType="dtmf speech" numDigits="6" 
             speechModel="phone_call" hints="0,1,2,3,4,5,6,7,8,9,zero,oh">
    <Speak voice="Polly.Joanna" language="en-US">Please say or enter your 6 digit PIN.</Speak>
  </GetInput>
</Response>'''
        return plivo_response(xml)

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
  <GetInput action="/handle_action" inputType="dtmf speech" numDigits="1" 
             digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.</Speak>
  </GetInput>
</Response>'''
    return plivo_response(xml)


@app.route("/handle_action", methods=['GET'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = (request.values.get('SpeechResult', '') or request.values.get('Speech', '')).lower()
    call_uuid = request.values.get('CallUUID')
    caller = request.values.get('From', 'unknown')
    pin = active_pins.get(call_uuid, {}).get("pin", "")

    if digits == "1" or "repeat" in speech:
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results repeated")
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Repeating the results.</Speak>
  <Redirect method="GET">{BASE_URL}/confirm_pin</Redirect>
</Response>'''
        return plivo_response(xml)
    else:
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Call ended")
        xml = f'''<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
  <Hangup/>
</Response>'''
        return plivo_response(xml)


@app.route("/hangup", methods=['POST'])
def hangup():
    call_uuid = request.values.get('CallUUID')
    pin = active_pins.get(call_uuid, {}).get("pin", "")
    caller = request.values.get('From', 'unknown')
    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")
    return Response("<Response></Response>", mimetype="application/xml")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)