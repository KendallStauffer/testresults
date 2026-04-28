from flask import Flask, request, Response, render_template_string, send_file
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime

app = Flask(__name__)

# ====================== CONFIG ======================
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "CHANGE_ME")
CSV_PATH = os.environ.get("CSV_PATH", "/mnt/data/test_results_long.csv")
LOG_PATH = os.environ.get("LOG_PATH", "/mnt/data/call_logs.csv")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/mnt/data/backups")
BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")

# Telnyx TeXML voice / recognition settings.
TTS_VOICE = os.environ.get("TTS_VOICE", "AWS.Polly.Joanna")
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")
ASR_ENGINE = os.environ.get("ASR_ENGINE", "Telnyx")

# The long timeout was important in testing.
PIN_GATHER_TIMEOUT = os.environ.get("PIN_GATHER_TIMEOUT", os.environ.get("GATHER_TIMEOUT", "12"))
PIN_SPEECH_TIMEOUT = os.environ.get("PIN_SPEECH_TIMEOUT", os.environ.get("SPEECH_TIMEOUT", "3"))
MENU_GATHER_TIMEOUT = os.environ.get("MENU_GATHER_TIMEOUT", "8")
MENU_SPEECH_TIMEOUT = os.environ.get("MENU_SPEECH_TIMEOUT", "3")

PIN_HINTS = os.environ.get(
    "PIN_HINTS",
    "zero, oh, o, q, one, won, two, too, to, three, tree, four, for, five, six, seven, eight, ate, nine, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9"
)

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


# ====================== XML HELPERS ======================
def xml_response(xml):
    return Response(xml, mimetype="application/xml")


def escape_xml(value):
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def say(text):
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{escape_xml(text)}</Say>'


def say_ssml(inner_ssml):
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{inner_ssml}</Say>'


def pin_gather_attrs():
    return (
        f'action="{BASE_URL}/gather_pin" '
        f'method="POST" '
        f'input="dtmf speech" '
        f'timeout="{PIN_GATHER_TIMEOUT}" '
        f'numDigits="6" '
        f'speechTimeout="{PIN_SPEECH_TIMEOUT}" '
        f'language="{TTS_LANGUAGE}" '
        f'hints="{escape_xml(PIN_HINTS)}" '
        f'transcriptionEngine="{ASR_ENGINE}"'
    )


def menu_gather_attrs(action_path, hints):
    return (
        f'action="{BASE_URL}{action_path}" '
        f'method="POST" '
        f'input="dtmf speech" '
        f'timeout="{MENU_GATHER_TIMEOUT}" '
        f'numDigits="1" '
        f'speechTimeout="{MENU_SPEECH_TIMEOUT}" '
        f'language="{TTS_LANGUAGE}" '
        f'hints="{escape_xml(hints)}" '
        f'transcriptionEngine="{ASR_ENGINE}"'
    )


# ====================== REQUEST HELPERS ======================
def get_call_id():
    return (
        request.values.get("CallSid")
        or request.values.get("CallSidLegacy")
        or request.values.get("CallUUID")
        or request.values.get("call_control_id")
        or request.values.get("CallControlId")
        or request.values.get("call_session_id")
        or "unknown"
    )


def get_from_number():
    return (
        request.values.get("From")
        or request.values.get("from")
        or request.values.get("Caller")
        or request.values.get("CallerId")
        or "unknown"
    )


def get_digits():
    return (
        request.values.get("Digits")
        or request.values.get("digits")
        or request.values.get("dtmf")
        or ""
    ).strip()


def get_speech():
    return (
        request.values.get("SpeechResult")
        or request.values.get("speech_result")
        or request.values.get("Speech")
        or request.values.get("speech")
        or request.values.get("transcription")
        or request.values.get("TranscriptionText")
        or ""
    ).strip()


def speak_digits(value):
    return " ".join(list(str(value)))


def normalize_pin(raw):
    raw = (raw or "").lower().strip()

    word_map = {
        "zero": "0",
        "oh": "0",
        "o": "0",
        "q": "0",
        "queue": "0",
        "cue": "0",
        "one": "1",
        "won": "1",
        "two": "2",
        "too": "2",
        "to": "2",
        "three": "3",
        "tree": "3",
        "four": "4",
        "for": "4",
        "fore": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "ate": "8",
        "nine": "9",
    }

    tokens = re.findall(r"[a-z]+|\d", raw)

    digits = []
    for token in tokens:
        if token.isdigit():
            digits.append(token)
        elif token in word_map:
            digits.append(word_map[token])

    normalized = "".join(digits)

    # If the recognizer includes junk before the PIN, prefer the last 6 digits.
    if len(normalized) > 6:
        normalized = normalized[-6:]

    return normalized


def normalize_menu_choice(raw):
    raw = (raw or "").lower().strip()
    if not raw:
        return ""

    # Prefer explicit digits if present.
    digits = re.findall(r"\d", raw)
    if digits:
        return digits[0]

    yes_words = ["yes", "yeah", "yep", "correct", "right", "affirmative"]
    no_words = ["no", "nope", "wrong", "incorrect"]
    repeat_words = ["repeat", "again", "replay"]

    if any(w in raw for w in yes_words):
        return "1"
    if any(w in raw for w in no_words):
        return "2"
    if any(w in raw for w in repeat_words):
        return "1"
    if "goodbye" in raw or "bye" in raw or "end" in raw or "hang up" in raw:
        return "2"

    return ""


def safe_int(value, default=0):
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def format_decimal(value):
    try:
        value = float(value)
        return f"{value:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def ordinal(n):
    try:
        n = int(n)
    except Exception:
        return str(n)

    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ====================== DATA ======================
def load_data():
    global df
    try:
        if os.path.exists(CSV_PATH):
            df = pd.read_csv(CSV_PATH)
            df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]

            if "pin_number" not in df.columns:
                df["pin_number"] = ""
            if "sequence_number" not in df.columns:
                df["sequence_number"] = 1

            df["pin_number"] = df["pin_number"].astype(str).str.strip().str.zfill(6)
            logger.info(f"Loaded {len(df)} records from CSV")
            return True

        logger.info("No CSV found yet")
        return False
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        return False


def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(
            columns=["Timestamp", "CallerID", "CallID", "EnteredPIN", "Status", "Notes"]
        ).to_csv(LOG_PATH, index=False)
        logger.info("Created new call_logs.csv")


def log_call_to_csv(caller_id, call_id, entered_pin="", status="PIN Rejected", notes=""):
    try:
        new_row = pd.DataFrame(
            [{
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "CallerID": caller_id,
                "CallID": call_id,
                "EnteredPIN": entered_pin,
                "Status": status,
                "Notes": notes,
            }]
        )
        new_row.to_csv(LOG_PATH, mode="a", header=False, index=False)
        logger.info(f"APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"Failed to append to call_logs.csv: {e}")


load_data()
init_call_log()


# ====================== ADMIN ROUTES ======================
@app.route("/")
def home():
    return '<h2>MMA Test Results IVR</h2><p><a href="/status">Status</a></p>'


@app.route("/health")
def health():
    return {
        "ok": True,
        "records": int(len(df)),
        "tts_voice": TTS_VOICE,
        "tts_language": TTS_LANGUAGE,
        "asr_engine": ASR_ENGINE,
        "pin_gather_timeout": PIN_GATHER_TIMEOUT,
        "pin_speech_timeout": PIN_SPEECH_TIMEOUT,
        "menu_gather_timeout": MENU_GATHER_TIMEOUT,
        "menu_speech_timeout": MENU_SPEECH_TIMEOUT,
    }


@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return render_template_string(
        """
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Call Logs: {{ log_count }}</p>
        <p>TTS Voice: {{ tts_voice }}</p>
        <p>TTS Language: {{ tts_language }}</p>
        <p>ASR Engine: {{ asr_engine }}</p>
        <p>PIN Timeout: {{ pin_timeout }}</p>
        <p>PIN Speech Timeout: {{ pin_speech_timeout }}</p>
        <p>
          <a href="/upload">Upload CSV</a> |
          <a href="/logs">View Logs</a> |
          <a href="/download_logs">Download Logs</a>
        </p>
    """,
        record_count=record_count,
        log_count=log_count,
        tts_voice=TTS_VOICE,
        tts_language=TTS_LANGUAGE,
        asr_engine=ASR_ENGINE,
        pin_timeout=PIN_GATHER_TIMEOUT,
        pin_speech_timeout=PIN_SPEECH_TIMEOUT,
    )


@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"
    logs_df = pd.read_csv(LOG_PATH).sort_values("Timestamp", ascending=False).head(200)
    return render_template_string(
        """
        <h2>Recent Call Logs (200 newest)</h2>
        <a href="/status">Back</a> | <a href="/download_logs">Download Full CSV</a><br><br>
        {{ html|safe }}
        <style>table, th, td {border:1px solid black; padding:8px;}</style>
    """,
        html=logs_df.to_html(index=False),
    )


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
        if file and file.filename.lower().endswith(".csv"):
            if os.path.exists(CSV_PATH):
                backup_path = os.path.join(
                    BACKUP_DIR, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                shutil.copy(CSV_PATH, backup_path)

            temp_path = CSV_PATH + ".tmp"
            file.save(temp_path)

            try:
                test_df = pd.read_csv(temp_path)
                test_df.columns = [c.strip().replace(" ", "_").lower() for c in test_df.columns]
                required = {"pin_number", "sequence_number"}
                missing = required - set(test_df.columns)
                if missing:
                    os.remove(temp_path)
                    return f"<h2>CSV missing required columns: {', '.join(sorted(missing))}</h2>", 400
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return f"<h2>Invalid CSV: {escape_xml(e)}</h2>", 400

            os.replace(temp_path, CSV_PATH)
            load_data()
            return f"<h2>Uploaded. {len(df)} records loaded.</h2><a href='/status'>Status</a>"

        return "<h2>Please upload a valid CSV</h2>", 400

    return """
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">Status</a>
    """


# ====================== TELNYX TEXML VOICE ROUTES ======================
@app.route("/voice", methods=["GET", "POST"])
@app.route("/telnyx/voice", methods=["GET", "POST"])
def voice():
    logger.info("=== Call started ===")
    logger.info(f"Voice form data: {dict(request.form)}")
    logger.info(f"Voice values: {dict(request.values)}")

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather {pin_gather_attrs()}>
    {say("Please say or enter your 6 digit pin.")}
  </Gather>
  {say("We did not receive any input. Goodbye.")}
  <Hangup/>
</Response>'''
    return xml_response(xml)


def pin_retry_xml():
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Pause length="1"/>
  <Gather {pin_gather_attrs()}>
    {say("Sorry, I did not get a complete 6 digit pin. Please say or enter your 6 digit pin again.")}
  </Gather>
  {say("We still did not receive your PIN. Goodbye.")}
  <Hangup/>
</Response>'''


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    logger.info("=== Gather received ===")
    logger.info(f"Form data: {dict(request.form)}")
    logger.info(f"All values: {dict(request.values)}")

    speech = get_speech()
    digits = get_digits()
    confidence = request.values.get("Confidence", "").strip()

    raw = digits if digits else speech
    pin = normalize_pin(raw)

    logger.info(f"Digits field: '{digits}'")
    logger.info(f"SpeechResult field: '{speech}'")
    logger.info(f"Confidence field: '{confidence}'")
    logger.info(f"Raw input used: '{raw}'")
    logger.info(f"Normalized PIN: '{pin}'")

    caller = get_from_number()
    call_id = get_call_id()

    if len(pin) != 6:
        log_call_to_csv(caller, call_id, pin, "PIN Rejected", f"Failed pin attempt | raw={raw}")
        return xml_response(pin_retry_xml())

    active_pins[call_id] = {"pin": pin}
    log_call_to_csv(caller, call_id, pin, "PIN Accepted", f"Successful pin attempt | raw={raw}")

    spoken = speak_digits(pin)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say(f"You said {spoken}. Is that correct?")}
  <Gather {menu_gather_attrs("/confirm_pin", "yes, yeah, yep, correct, right, one, no, nope, wrong, incorrect, two")}>
    {say("Say yes or press 1. Say no or press 2.")}
  </Gather>
  {say("I did not receive a confirmation. Let's try the PIN again.")}
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>'''
    return xml_response(xml)


@app.route("/confirm_pin", methods=["GET", "POST"])
def confirm_pin():
    logger.info("=== Confirm received ===")
    logger.info(f"Form data: {dict(request.form)}")
    logger.info(f"All values: {dict(request.values)}")

    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    choice = normalize_menu_choice(raw)

    call_id = get_call_id()
    caller = get_from_number()

    logger.info(f"Confirmation raw='{raw}' choice='{choice}'")

    if choice != "1":
        if choice == "2":
            log_call_to_csv(caller, call_id, "", "PIN Rejected", "Caller rejected confirmation")
        retry_inner = pin_retry_xml().replace('<?xml version="1.0" encoding="UTF-8"?>', "").replace("<Response>", "").replace("</Response>", "")
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("Okay, let's try again.")}
  {retry_inner}
</Response>'''
        return xml_response(xml)

    pin = active_pins.get(call_id, {}).get("pin")
    if not pin:
        return xml_response(pin_retry_xml())

    results_df = df[df["pin_number"] == pin].sort_values("sequence_number")
    if results_df.empty:
        log_call_to_csv(caller, call_id, pin, "PIN Accepted", "No results found")
        retry_inner = pin_retry_xml().replace('<?xml version="1.0" encoding="UTF-8"?>', "").replace("<Response>", "").replace("</Response>", "")
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("I found your PIN, but I do not have results for that PIN. Please check the number and try again.")}
  {retry_inner}
</Response>'''
        return xml_response(xml)

    log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Results read")

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("Here are your milk test results.")}'''

    for _, row in results_df.iterrows():
        day = safe_int(row.get("day", 1), 1)
        fat = safe_float(row.get("fat", 0), 0)
        protein = safe_float(row.get("protein", 0), 0)
        scc = safe_int(row.get("scc", 0), 0)
        mun = safe_int(row.get("mun", 0), 0)

        result_ssml = f'''
    <prosody rate="medium">
      Sample from the {escape_xml(ordinal(day))}.
      <break time="600ms"/>
      Butterfat {escape_xml(format_decimal(fat))} percent.
      <break time="600ms"/>
      Protein {escape_xml(format_decimal(protein))} percent.
      <break time="600ms"/>
      Somatic cell count {escape_xml(f"{scc:,}")}.
      <break time="600ms"/>
    </prosody>'''
        xml += "\n  " + say_ssml(result_ssml)

        if mun > 0:
            xml += "\n  " + say_ssml(f'<prosody rate="medium">Mun {escape_xml(mun)}.</prosody>')

    xml += f'''
  <Gather {menu_gather_attrs("/handle_action", "repeat, again, replay, one, goodbye, bye, end, two")}>
    {say("To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.")}
  </Gather>
  {say("We did not receive any input. Goodbye.")}
  <Hangup/>
</Response>'''
    return xml_response(xml)


@app.route("/handle_action", methods=["GET", "POST"])
def handle_action():
    logger.info("=== Action received ===")
    logger.info(f"Form data: {dict(request.form)}")
    logger.info(f"All values: {dict(request.values)}")

    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    choice = normalize_menu_choice(raw)

    call_id = get_call_id()
    caller = get_from_number()
    pin = active_pins.get(call_id, {}).get("pin", "")

    logger.info(f"Action raw='{raw}' choice='{choice}'")

    if choice == "1":
        log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Results repeated")
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("Repeating the results.")}
  <Redirect method="POST">{BASE_URL}/confirm_pin</Redirect>
</Response>'''
        return xml_response(xml)

    log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Call ended")
    active_pins.pop(call_id, None)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("Thank you for calling. Goodbye.")}
  <Hangup/>
</Response>'''
    return xml_response(xml)


@app.route("/hangup", methods=["GET", "POST"])
@app.route("/telnyx/hangup", methods=["GET", "POST"])
def hangup():
    call_id = get_call_id()
    pin = active_pins.get(call_id, {}).get("pin", "")
    caller = get_from_number()
    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    log_call_to_csv(caller, call_id, pin, status, "Caller hung up")
    active_pins.pop(call_id, None)
    return xml_response('<Response></Response>')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
