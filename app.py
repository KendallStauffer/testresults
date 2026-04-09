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

os.makedirs(BACKUP_DIR, exist_ok=True)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

active_pins = {}
df = pd.DataFrame()

# ====================== HELPERS ======================

NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "won": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "tree": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
}

YES_WORDS = {"yes", "yeah", "yep", "correct", "right", "affirmative"}
NO_WORDS = {"no", "nope", "wrong", "incorrect", "negative"}

REPEAT_WORDS = {"repeat", "again", "replay"}
GOODBYE_WORDS = {"goodbye", "bye", "end", "done", "stop", "hang up"}

def plivo_response(xml: str):
    return Response(xml, mimetype="application/xml")

def speak_pin_digits(pin: str):
    return " ".join(list(pin))

def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def normalize_columns(columns):
    return [str(c).strip().lower().replace(" ", "_") for c in columns]

def safe_int(val, default=0):
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default

def safe_float(val, default=0.0):
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default

def extract_digits_from_text(text: str) -> str:
    """
    Converts speech like:
    - 'one two three four five six'
    - '1 2 three 4 oh 6'
    - 'zero one two three four five'
    into '123456' / etc.
    """
    if not text:
        return ""

    text = text.lower().strip()

    # Normalize separators
    text = text.replace("-", " ").replace(",", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text)

    # First collect direct digits already present
    direct_digits = re.findall(r"\d", text)

    # Then parse spoken tokens
    tokens = re.findall(r"[a-zA-Z0-9]+", text)
    spoken_digits = []

    for token in tokens:
        if token.isdigit():
            spoken_digits.extend(list(token))
        elif token in NUMBER_WORDS:
            spoken_digits.append(NUMBER_WORDS[token])

    # Prefer parsed token stream because it preserves order better in mixed input
    if spoken_digits:
        return "".join(spoken_digits)

    if direct_digits:
        return "".join(direct_digits)

    return ""

def interpret_yes_no(digits: str, speech: str):
    speech = (speech or "").lower().strip()

    if digits == "1":
        return True
    if digits == "2":
        return False

    for word in YES_WORDS:
        if word in speech:
            return True
    for word in NO_WORDS:
        if word in speech:
            return False

    return None

def interpret_action(digits: str, speech: str):
    speech = (speech or "").lower().strip()

    if digits == "1":
        return "repeat"
    if digits == "2":
        return "goodbye"

    for word in REPEAT_WORDS:
        if word in speech:
            return "repeat"
    for word in GOODBYE_WORDS:
        if word in speech:
            return "goodbye"

    return None

def init_call_state(call_uuid):
    if call_uuid not in active_pins:
        active_pins[call_uuid] = {
            "pin": "",
            "results_reads": 0,
        }

def clear_call_state(call_uuid):
    if call_uuid in active_pins:
        del active_pins[call_uuid]

def log_call(event: str, extra: dict = None):
    if extra is None:
        extra = {}
    call_uuid = request.values.get("CallUUID", "unknown")
    from_number = request.values.get("From", "unknown")
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(
            columns=["Timestamp", "CallerID", "CallUUID", "EnteredPIN", "Status", "Notes"]
        ).to_csv(LOG_PATH, index=False)
        logger.info("✅ Created new call_logs.csv - will append from now on")
    else:
        logger.info("call_logs.csv already exists - will append only (no overwrite ever)")

def log_call_to_csv(caller_id, call_uuid, entered_pin="", status="PIN Rejected", notes=""):
    try:
        new_row = pd.DataFrame([{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "CallerID": caller_id,
            "CallUUID": call_uuid,
            "EnteredPIN": entered_pin,
            "Status": status,
            "Notes": notes
        }])
        new_row.to_csv(LOG_PATH, mode="a", header=False, index=False)
        logger.info(f"✅ APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"❌ Failed to append to call_logs.csv: {e}")

def load_data():
    global df
    try:
        if os.path.exists(CSV_PATH):
            temp_df = pd.read_csv(CSV_PATH)
            temp_df.columns = normalize_columns(temp_df.columns)

            # Ensure required columns exist
            required_defaults = {
                "pin_number": "",
                "sequence_number": 1,
                "day": 1,
                "fat": 0,
                "protein": 0,
                "scc": 0,
                "mun": 0,
            }
            for col, default in required_defaults.items():
                if col not in temp_df.columns:
                    temp_df[col] = default

            # Normalize pin numbers
            temp_df["pin_number"] = (
                temp_df["pin_number"]
                .astype(str)
                .str.strip()
                .str.extract(r"(\d+)", expand=False)
                .fillna("")
                .str.zfill(6)
            )

            # Numeric cleanup
            temp_df["sequence_number"] = pd.to_numeric(temp_df["sequence_number"], errors="coerce").fillna(1)
            temp_df["day"] = pd.to_numeric(temp_df["day"], errors="coerce").fillna(1)
            temp_df["fat"] = pd.to_numeric(temp_df["fat"], errors="coerce").fillna(0)
            temp_df["protein"] = pd.to_numeric(temp_df["protein"], errors="coerce").fillna(0)
            temp_df["scc"] = pd.to_numeric(temp_df["scc"], errors="coerce").fillna(0)
            temp_df["mun"] = pd.to_numeric(temp_df["mun"], errors="coerce").fillna(0)

            df = temp_df
            logger.info(f"✅ Loaded {len(df)} records from CSV")
            return True

        logger.info("No CSV found yet")
        df = pd.DataFrame()
        return False
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        df = pd.DataFrame()
        return False

def pin_retry_xml(message=None):
    prompt = message or (
        "I'm sorry, I didn't get that. Please say your six digit PIN one number at a time. "
        "For example: one, two, three, four, five, six."
    )
    return f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="POST" inputType="dtmf speech" numDigits="6"
            digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">{prompt}</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We still didn't receive a valid PIN. Goodbye.</Speak>
  <Hangup/>
</Response>"""

def no_results_xml(pin):
    spoken = speak_pin_digits(pin)
    return f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">
    We found no milk test results for PIN {spoken}.
  </Speak>
  <GetInput action="{BASE_URL}/gather_pin" method="POST" inputType="dtmf speech" numDigits="6"
            digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Please try another six digit PIN now.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We did not receive another PIN. Goodbye.</Speak>
  <Hangup/>
</Response>"""

def build_results_xml(pin, intro="Here are your milk test results."):
    results_df = df[df["pin_number"] == pin].copy()

    if results_df.empty:
        return no_results_xml(pin)

    results_df["sequence_number"] = pd.to_numeric(results_df["sequence_number"], errors="coerce").fillna(1)
    results_df = results_df.sort_values(["sequence_number", "day"])

    xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">{intro}</Speak>"""

    for _, row in results_df.iterrows():
        day = safe_int(row.get("day", 1), 1)
        fat = safe_float(row.get("fat", 0), 0)
        protein = safe_float(row.get("protein", 0), 0)
        scc = safe_int(row.get("scc", 0), 0)
        mun = safe_int(row.get("mun", 0), 0)

        xml += f"""
  <Speak voice="Polly.Joanna" language="en-US">
    <prosody rate="medium">
      Sample from the {ordinal(day)}.
      <break time="500ms"/>
      Butterfat {fat:.2f} percent.
      <break time="500ms"/>
      Protein {protein:.2f} percent.
      <break time="500ms"/>
      Somatic cell count {scc:,}.
      <break time="500ms"/>
    </prosody>
  </Speak>"""

        if mun > 0:
            xml += f"""
  <Speak voice="Polly.Joanna" language="en-US">
    <prosody rate="medium">
      M U N {mun}.
    </prosody>
  </Speak>"""

    xml += f"""
  <GetInput action="{BASE_URL}/handle_action" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      To hear these results again, say repeat or press 1.
      To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Goodbye.</Speak>
  <Hangup/>
</Response>"""

    return xml

# ====================== STARTUP ======================

load_data()
init_call_log()

# ====================== ADMIN ======================

@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return render_template_string("""
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Call Logs: {{ log_count }}</p>
        <p><a href="/upload">Upload CSV</a> | <a href="/logs">View Logs</a> | <a href="/download_logs">Download Logs</a></p>
    """, record_count=record_count, log_count=log_count)

@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"
    logs_df = pd.read_csv(LOG_PATH).sort_values("Timestamp", ascending=False).head(200)
    return render_template_string("""
        <h2>Recent Call Logs (200 newest)</h2>
        <a href="/status">← Back</a> | <a href="/download_logs">Download Full CSV</a><br><br>
        {{ html|safe }}
        <style>table, th, td {border:1px solid black; padding:8px;}</style>
    """, html=logs_df.to_html(index=False))

@app.route("/download_logs")
def download_logs():
    if not os.path.exists(LOG_PATH):
        return "No logs yet.", 404
    return send_file(LOG_PATH, as_attachment=True, download_name="call_logs.csv")

@app.route("/upload", methods=["GET", "POST"])
def upload_csv():
    if request.method == "POST":
        if request.form.get("password") != UPLOAD_PASSWORD:
            return "<h2>Wrong password</h2><a href='/upload'>Try again</a>", 401

        file = request.files.get("file")
        if file and file.filename.endswith(".csv"):
            if os.path.exists(CSV_PATH):
                shutil.copy(
                    CSV_PATH,
                    f"{BACKUP_DIR}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
            file.save(CSV_PATH)
            load_data()
            return f"<h2>✅ Uploaded! {len(df)} records loaded.</h2><a href='/status'>Status</a>"

        return "<h2>Please upload a valid CSV</h2>", 400

    return """
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">← Status</a>
    """

# ====================== VOICE FLOW ======================

@app.route("/voice", methods=["GET", "POST"])
def voice():
    log_call("INCOMING_CALL")
    call_uuid = request.values.get("CallUUID", "unknown")
    init_call_state(call_uuid)

    xml = f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="POST" inputType="dtmf speech" numDigits="6"
            digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Thank you for calling the Milk Market Administrator Test Results Center.
      Please say or enter your 6 digit PIN.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We didn't receive any input. Goodbye.</Speak>
  <Hangup/>
</Response>"""
    return plivo_response(xml)

@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    digits = request.values.get("Digits", "").strip()
    speech = request.values.get("SpeechResult", "").strip() or request.values.get("Speech", "").strip()
    raw = digits if digits else speech

    caller = request.values.get("From", "unknown")
    call_uuid = request.values.get("CallUUID", "unknown")
    init_call_state(call_uuid)

    logger.info(f"RAW INPUT: '{raw}'")

    pin = extract_digits_from_text(raw)
    logger.info(f"PARSED PIN: '{pin}'")

    if len(pin) != 6:
        note = "Failed pin attempt"
        if raw and any(word in raw.lower() for word in ["zero", "oh", "o"]):
            note = "Failed pin attempt - possible zero confusion"

        log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", note)
        return plivo_response(pin_retry_xml())

    logger.info(f"SUCCESSFUL PIN: {pin}")
    active_pins[call_uuid]["pin"] = pin

    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Successful pin attempt")

    spoken = speak_pin_digits(pin)
    xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">You said {spoken}. Am I right?</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Let's try again.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>"""
    return plivo_response(xml)

@app.route("/confirm_pin", methods=["GET", "POST"])
def confirm_pin():
    digits = request.values.get("Digits", "").strip()
    speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()

    call_uuid = request.values.get("CallUUID", "unknown")
    caller = request.values.get("From", "unknown")
    init_call_state(call_uuid)

    decision = interpret_yes_no(digits, speech)

    if decision is False:
        xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">Okay, let's try again.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>"""
        return plivo_response(xml)

    if decision is None:
        xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">Sorry, I didn't catch that.</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Let's start over.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>"""
        return plivo_response(xml)

    pin = active_pins.get(call_uuid, {}).get("pin", "")
    if not pin:
        return plivo_response(pin_retry_xml("We lost your PIN entry. Please enter your six digit PIN again."))

    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results read")
    active_pins[call_uuid]["results_reads"] += 1

    return plivo_response(build_results_xml(pin))

@app.route("/handle_action", methods=["GET", "POST"])
def handle_action():
    digits = request.values.get("Digits", "").strip()
    speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()

    call_uuid = request.values.get("CallUUID", "unknown")
    caller = request.values.get("From", "unknown")
    init_call_state(call_uuid)

    pin = active_pins.get(call_uuid, {}).get("pin", "")
    action = interpret_action(digits, speech)

    if action == "repeat":
        if pin:
            log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results repeated")
            active_pins[call_uuid]["results_reads"] += 1
            return plivo_response(build_results_xml(pin, intro="Repeating your milk test results."))
        return plivo_response(pin_retry_xml("We lost your PIN entry. Please enter your six digit PIN again."))

    if action == "goodbye":
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Call ended")
        clear_call_state(call_uuid)
        xml = """<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
  <Hangup/>
</Response>"""
        return plivo_response(xml)

    xml = f"""<Response>
  <GetInput action="{BASE_URL}/handle_action" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Sorry, I didn't catch that.
      To hear the results again, say repeat or press 1.
      To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Goodbye.</Speak>
  <Hangup/>
</Response>"""
    return plivo_response(xml)

@app.route("/hangup", methods=["GET", "POST"])
def hangup():
    call_uuid = request.values.get("CallUUID", "unknown")
    caller = request.values.get("From", "unknown")
    pin = active_pins.get(call_uuid, {}).get("pin", "")

    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")
    clear_call_state(call_uuid)

    return Response("<Response></Response>", mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)