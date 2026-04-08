from flask import Flask, request, Response, render_template_string
import plivo
from plivo import plivoxml
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
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Last Upload: {{ last_upload_time }}</p>
        <p><a href="/upload">Upload CSV</a></p>
    ''', record_count=record_count, last_upload_time=last_upload_time)

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
    response = plivoxml.ResponseElement()

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/gather_pin",
        method="GET",
        input_type="dtmf speech",
        num_digits=6,
        digit_end_timeout=8,
        speech_end_timeout=2,
        language="en-US"
    )

    get_input.add(plivoxml.SpeakElement(
        "Thank you for calling the Milk Market Administrator Test Results Center. Please say or enter your 6 digit PIN.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)

    response.add(plivoxml.SpeakElement("We didn't receive any input. Goodbye.", voice="Polly.Joanna", language="en-US"))

    return plivo_response(response)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip() or request.values.get('Speech', '').strip()

    raw = digits if digits else speech
    logger.info(f"GATHER_PIN | raw = '{raw}'")

    pin = re.sub(r'\D', '', raw)

    log_call("PIN_ATTEMPT", {"raw": raw, "cleaned_pin": pin, "length": len(pin)})

    response = plivoxml.ResponseElement()

    if len(pin) != 6:
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf speech",
            num_digits=6,
            digit_end_timeout=8,
            speech_end_timeout=2,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "Sorry, I didn't get 6 digits. Please say or enter your 6 digit PIN again.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)
        return plivo_response(response)

    active_pins[request.values.get('CallUUID', 'unknown')] = {"pin": pin}
    log_call("PIN_ACCEPTED", {"pin": pin})

    spoken = speak_pin_digits(pin)
    response.add(plivoxml.SpeakElement(f"You said {spoken}. Am I right?", voice="Polly.Joanna", language="en-US"))

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/confirm_pin",
        method="GET",
        input_type="dtmf speech",
        num_digits=1,
        digit_end_timeout=10,
        speech_end_timeout=2,
        language="en-US"
    )
    get_input.add(plivoxml.SpeakElement(
        "Say yes or press 1 for yes. Say no or press 2 for no.",
        voice="Polly.Joanna", language="en-US"
    ))
    response.add(get_input)

    return plivo_response(response)


@app.route("/confirm_pin", methods=['GET'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower() or request.values.get('Speech', '').strip().lower()
    call_uuid = request.values.get('CallUUID')

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])

    response = plivoxml.ResponseElement()

    if not is_yes:
        response.add(plivoxml.SpeakElement("Okay, let's try again.", voice="Polly.Joanna", language="en-US"))
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf speech",
            num_digits=6,
            digit_end_timeout=8,
            speech_end_timeout=2,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "Please say or enter your 6 digit PIN.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)
        return plivo_response(response)

    pin = active_pins.get(call_uuid, {}).get("pin")
    if not pin:
        response.add(plivoxml.SpeakElement("Sorry, something went wrong. Please start over.", voice="Polly.Joanna", language="en-US"))
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf speech",
            num_digits=6,
            digit_end_timeout=8,
            speech_end_timeout=2,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "Please say or enter your 6 digit PIN.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)
        return plivo_response(response)

    # === RESULTS READING with prosody + break ===
    log_call("RESULTS_LOOKUP", {"pin": pin})
    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        response.add(plivoxml.SpeakElement("Sorry, no results were found for that PIN.", voice="Polly.Joanna", language="en-US"))
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf speech",
            num_digits=6,
            digit_end_timeout=8,
            speech_end_timeout=2,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "Please say or enter your 6 digit PIN.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)
        return plivo_response(response)

    response.add(plivoxml.SpeakElement("Here are your milk test results.", voice="Polly.Joanna", language="en-US"))

    for _, row in results_df.iterrows():
        day = int(row.get('day', 1))
        text = f"""
            Sample from the {day}th. 
            <break time="500ms"/>
            Butterfat {row.get('fat', 0)} percent. 
            <break time="500ms"/>
            Protein {row.get('protein', 0)} percent. 
            <break time="500ms"/>
            Somatic cell count {int(row.get('scc', 0)):,}. 
            <break time="500ms"/>
        """
        if int(row.get('mun', 0)) > 0:
            text += f" Munn {int(row.get('mun', 0))}."

        # Proper SSML with prosody + break
        speak = plivoxml.SpeakElement(f'<prosody rate="medium">{text.strip()}</prosody>', 
                                      voice="Polly.Joanna", language="en-US")
        response.add(speak)

    # Final menu
    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/handle_action",
        method="GET",
        input_type="dtmf speech",
        num_digits=1,
        digit_end_timeout=10,
        speech_end_timeout=2,
        language="en-US"
    )
    get_input.add(plivoxml.SpeakElement(
        "To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.",
        voice="Polly.Joanna", language="en-US"
    ))
    response.add(get_input)

    return plivo_response(response)


@app.route("/handle_action", methods=['GET'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower() or request.values.get('Speech', '').strip().lower()
    log_call("FINAL_ACTION", {"choice": speech or digits})

    response = plivoxml.ResponseElement()

    if digits == "1" or "repeat" in speech:
        response.add(plivoxml.SpeakElement("Repeating the results.", voice="Polly.Joanna", language="en-US"))
        
        call_uuid = request.values.get('CallUUID')
        pin = active_pins.get(call_uuid, {}).get("pin")
        if pin:
            results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')
            if not results_df.empty:
                for _, row in results_df.iterrows():
                    day = int(row.get('day', 1))
                    text = f"""
                        Sample from the {day}th. 
                        <break time="500ms"/>
                        Butterfat {row.get('fat', 0)} percent. 
                        <break time="500ms"/>
                        Protein {row.get('protein', 0)} percent. 
                        <break time="500ms"/>
                        Somatic cell count {int(row.get('scc', 0)):,}. 
                        <break time="500ms"/>
                    """
                    if int(row.get('mun', 0)) > 0:
                        text += f" Munn {int(row.get('mun', 0))}."

                    speak = plivoxml.SpeakElement(f'<prosody rate="medium">{text.strip()}</prosody>', 
                                                  voice="Polly.Joanna", language="en-US")
                    response.add(speak)

        # Menu after repeat
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/handle_action",
            method="GET",
            input_type="dtmf speech",
            num_digits=1,
            digit_end_timeout=10,
            speech_end_timeout=2,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)

    else:
        response.add(plivoxml.SpeakElement("Thank you for calling. Goodbye.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.HangupElement())

    return plivo_response(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)