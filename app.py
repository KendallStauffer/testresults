from flask import Flask, request, Response, render_template_string
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os
import logging
import shutil
from datetime import datetime

app = Flask(__name__)

# ====================== CONFIG ======================
UPLOAD_USERNAME = "MMAadmin"
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
    return " ".join(pin)

def twiml_response(resp: VoiceResponse):
    return Response(str(resp), mimetype="text/xml")

def log_call(event: str, extra: dict = None):
    if extra is None: extra = {}
    call_sid = request.values.get('CallSid', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallSid={call_sid} | From={from_number} {details}")

# ====================== ADMIN PAGES ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head><title>MMA System Status</title></head>
        <body style="font-family: Arial; margin: 40px;">
            <h2>Milk Market Administrator - System Status</h2>
            <p><strong>Current Records:</strong> {{ record_count }}</p>
            <p><strong>Last Data Upload:</strong> {{ last_upload_time }}</p>
            <hr>
            <p><a href="/upload">Upload New Data File</a></p>
        </body>
        </html>
    ''', record_count=record_count, last_upload_time=last_upload_time)

@app.route("/upload", methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        if password != UPLOAD_PASSWORD:
            return "<h2>❌ Incorrect Password</h2><p><a href='/upload'>Try again</a></p>", 401

        if 'file' not in request.files:
            return "<h2>❌ No file uploaded</h2>", 400

        file = request.files['file']
        if file.filename == '' or not file.filename.lower().endswith('.csv'):
            return "<h2>❌ Please upload a valid .csv file</h2>", 400

        if os.path.exists(CSV_PATH):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(CSV_PATH, f"{BACKUP_DIR}/test_results_long_{timestamp}.csv")

        file.save(CSV_PATH)
        logger.info("New CSV uploaded")

        if load_data():
            return f"""
            <h2>✅ Upload Successful!</h2>
            <p>New data loaded with <strong>{len(df)}</strong> records.</p>
            <p><a href="/upload">Upload another file</a> | <a href="/status">View Status</a></p>
            """
        else:
            return "<h2>⚠️ File uploaded but failed to load.</h2>", 400

    record_count = len(df) if not df.empty else 0
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head><title>MMA Data Upload</title></head>
        <body style="font-family: Arial; max-width: 600px; margin: 40px auto;">
            <h2>Milk Market Administrator - Data Upload</h2>
            <p><strong>Username:</strong> MMAadmin</p>
            <p><strong>Password:</strong> ForUSDA!2026</p>
            
            <form method="post" enctype="multipart/form-data">
                <p><strong>Enter Password:</strong><br>
                <input type="password" name="password" required style="width:100%; padding:8px;"></p>
                
                <p><strong>Select New CSV File:</strong><br>
                <input type="file" name="file" accept=".csv" required></p>
                
                <p><button type="submit" style="padding:10px 20px; font-size:16px;">Upload CSV File</button></p>
            </form>
            
            <p>Current records: <strong>{{ record_count }}</strong></p>
            <p><a href="/status">View System Status</a></p>
        </body>
        </html>
    ''', record_count=record_count)

# ====================== VOICE ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    call_sid = request.values.get('CallSid')
    resp = VoiceResponse()

    if call_sid not in active_pins:
        resp.say("Thank you for calling the Milk Market Administrator Test Results Center.", 
                 voice="Polly.Joanna", language="en-US")
        active_pins[call_sid] = {"pin": None}

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=8,
        finish_on_key="#",
        input="dtmf speech",
        speech_timeout=3,
        language="en-US",
        speech_model="numbers_and_commands",
        enhanced="true",
        hints="0 1 2 3 4 5 6 7 8 9",
        barge_in="true"
    )
    gather.say("Please enter your 6 digit PIN.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    resp.say("We didn't receive any input. Goodbye.", voice="Polly.Joanna", language="en-US")
    return twiml_response(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    # Fix: Define call_sid first
    call_sid = request.values.get('CallSid')

    # Correct priority: Digits (keypad) first, then SpeechResult
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    
    raw = digits if digits else speech
    print(f"Raw input received - Digits='{digits}', Speech='{speech}', Using='{raw}'")

    # Strong cleaning
    pin = ''.join(filter(str.isdigit, raw))

    if len(pin) != 6 and speech:
        word_map = {
            "zero": "0", "oh": "0", "o": "0",
            "one": "1", "two": "2", "three": "3",
            "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9"
        }
        words = speech.lower().split()
        converted = [word_map.get(w, '') for w in words]
        pin = ''.join(converted)

    if len(pin) > 6:
        pin = pin[-6:]

    log_call("PIN_ATTEMPT", {"raw": raw, "cleaned": pin, "length": len(pin), "source": "Digits" if digits else "Speech"})

    resp = VoiceResponse()

    if len(pin) != 6:
        log_call("PIN_INVALID")
        resp.say("Let's try again. Please enter your 6 digit PIN.", 
                 voice="Polly.Joanna", language="en-US")
        gather = Gather(
            action="/gather_pin",
            num_digits=6,
            timeout=8,
            finish_on_key="#",
            input="dtmf speech",
            speech_timeout=3,
            language="en-US",
            speech_model="numbers_and_commands",
            enhanced="true",
            hints="0 1 2 3 4 5 6 7 8 9",
            barge_in="true"
        )
        gather.say("Please enter your 6 digit PIN.", 
                   voice="Polly.Joanna", language="en-US")
        resp.append(gather)
        return twiml_response(resp)

    # Success
    active_pins[call_sid] = {"pin": pin}
    log_call("PIN_ACCEPTED", {"pin": pin})

    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")

    gather = Gather(
        action="/confirm_pin",
        num_digits=1,
        timeout=8,
        input="dtmf speech",
        speech_timeout="auto",
        language="en-US",
        barge_in="true"
    )
    gather.say("Say yes or press 1 for yes. Say no or press 2 for no.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return twiml_response(resp)


@app.route("/confirm_pin", methods=['POST'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower()
    call_sid = request.values.get('CallSid')

    resp = VoiceResponse()

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])
    log_call("CONFIRMATION", {"input": speech or digits, "is_yes": is_yes})

    if not is_yes:
        resp.say("Okay, let's try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    pin = active_pins.get(call_sid, {}).get("pin")
    if not pin:
        log_call("ERROR_PIN_LOST")
        resp.say("Sorry, something went wrong. Please start over.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    log_call("RESULTS_LOOKUP", {"pin": pin})
    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        log_call("NO_RESULTS_FOUND", {"pin": pin})
        resp.say("Sorry, no results were found for that PIN. Let's try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    resp.say("Here are your milk test results.", voice="Polly.Joanna", language="en-US")

    for _, row in results_df.iterrows():
        day = int(row.get('day', 1))

        resp.pause(length=1)
        resp.say(f"Sample from the {day}th.", voice="Polly.Joanna", language="en-US")

        resp.say(f"Butterfat {row.get('fat', 0)} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Protein {row.get('protein', 0)} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Somatic cell count {int(row.get('scc', 0)):,}.", voice="Polly.Joanna", language="en-US")
        
        if int(row.get('mun', 0)) > 0:
            resp.say(f"Munn {int(row.get('mun', 0))}.", voice="Polly.Joanna", language="en-US")

        resp.pause(length=1)

    gather = Gather(action="/handle_action", num_digits=1, timeout=10)
    gather.say("To repeat these results, say repeat or press 1. To end the call, say goodbye or press 2.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return twiml_response(resp)


@app.route("/handle_action", methods=['POST'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower()
    log_call("FINAL_ACTION", {"choice": speech or digits})

    resp = VoiceResponse()

    if digits == "1" or "repeat" in speech:
        resp.say("Repeating the results.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.", voice="Polly.Joanna", language="en-US")
    return twiml_response(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)