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

# AWS Polly through Telnyx TeXML. No audio reuse/caching.
TTS_VOICE = os.environ.get("TTS_VOICE", "AWS.Polly.Joanna")
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")

# Speech recognition tuning for Telnyx <Gather>.
# Valid examples: Google, Telnyx, Deepgram, Azure.
ASR_ENGINE = os.environ.get("ASR_ENGINE", "Google")
ASR_USE_ENHANCED = os.environ.get("ASR_USE_ENHANCED", "true").lower() in {"1", "true", "yes", "y"}
PIN_SPEECH_TIMEOUT = os.environ.get("PIN_SPEECH_TIMEOUT", "auto")
MENU_SPEECH_TIMEOUT = os.environ.get("MENU_SPEECH_TIMEOUT", "1")
PIN_HINTS = os.environ.get(
    "PIN_HINTS",
    "zero, oh, o, one, two, three, four, for, five, six, seven, eight, ate, nine"
)
MENU_HINTS = os.environ.get(
    "MENU_HINTS",
    "yes, no, correct, right, wrong, repeat, again, goodbye, one, two"
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


# ====================== XML / REQUEST HELPERS ======================
def xml_response(xml: str):
    return Response(xml, mimetype="application/xml")


def escape_xml(value) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def say(text: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{escape_xml(text)}</Say>'


def say_ssml(inner_ssml: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{inner_ssml}</Say>'


def gather_attrs(*, action: str, input_type: str = "speech", timeout: str = "6", speech_timeout: str = "auto", hints: str = "") -> str:
    """Build Telnyx TeXML Gather attributes.

    PIN capture is speech-only on purpose: no finishOnKey, no numDigits,
    no min/max digit constraints. The Python layer normalizes spoken words
    into a 6-digit PIN after Telnyx returns speech text.
    """
    attrs = [
        f'action="{action}"',
        'method="POST"',
        f'input="{input_type}"',
        f'timeout="{timeout}"',
        f'speechTimeout="{speech_timeout}"',
        f'language="{TTS_LANGUAGE}"',
    ]
    if ASR_ENGINE:
        attrs.append(f'transcriptionEngine="{escape_xml(ASR_ENGINE)}"')
    if ASR_USE_ENHANCED:
        attrs.append('useEnhanced="true"')
    if hints:
        attrs.append(f'hints="{escape_xml(hints)}"')
    return " ".join(attrs)


def get_call_id() -> str:
    return (
        request.values.get("CallSid")
        or request.values.get("CallUUID")
        or request.values.get("call_control_id")
        or request.values.get("CallControlId")
        or request.values.get("call_session_id")
        or "unknown"
    )


def get_from_number() -> str:
    return (
        request.values.get("From")
        or request.values.get("from")
        or request.values.get("Caller")
        or "unknown"
    )


def get_digits() -> str:
    return (
        request.values.get("Digits")
        or request.values.get("digits")
        or request.values.get("dtmf")
        or ""
    ).strip()


def get_speech() -> str:
    return (
        request.values.get("SpeechResult")
        or request.values.get("Speech")
        or request.values.get("speech")
        or request.values.get("speech_result")
        or ""
    ).strip()


def log_call(event: str, extra: dict = None):
    if extra is None:
        extra = {}
    call_id = get_call_id()
    from_number = get_from_number()
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallID={call_id} | From={from_number} {details}")


def speak_pin_digits(pin: str):
    return " ".join(list(str(pin)))


def normalize_pin(raw: str) -> str:
    if not raw:
        return ""

    text = str(raw).lower().strip()
    word_map = {
        "zero": "0", "oh": "0", "o": "0",
        "one": "1", "won": "1",
        "two": "2", "to": "2", "too": "2",
        "three": "3", "tree": "3",
        "four": "4", "for": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8", "ate": "8",
        "nine": "9",
    }

    tokens = re.findall(r"[a-z]+|\d", text)
    converted = []
    for token in tokens:
        if token.isdigit():
            converted.append(token)
        elif token in word_map:
            converted.append(word_map[token])

    if converted:
        return "".join(converted)

    return re.sub(r"\D", "", raw)


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
    else:
        logger.info("call_logs.csv already exists")


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


# ====================== ADMIN ======================
@app.route("/")
def home():
    return '<h2>MMA Test Results IVR</h2><p><a href="/status">Status</a></p>'


@app.route("/health")
def health():
    return {"ok": True, "records": int(len(df))}


@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return render_template_string(
        """
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>Call Logs: {{ log_count }}</p>
        <p>Voice: {{ voice }}</p>
        <p>ASR Engine: {{ asr_engine }}</p>
        <p>PIN Speech Timeout: {{ pin_speech_timeout }}</p>
        <p><a href="/upload">Upload CSV</a> | <a href="/logs">View Logs</a> | <a href="/download_logs">Download Logs</a></p>
    """,
        record_count=record_count,
        log_count=log_count,
        voice=TTS_VOICE,
        asr_engine=ASR_ENGINE,
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


# ====================== TELNYX TEXML VOICE FLOW ======================
@app.route("/voice", methods=["GET", "POST"])
@app.route("/telnyx/voice", methods=["GET", "POST"])
def voice():
    log_call("INCOMING_CALL")
    pin_gather = gather_attrs(
        action=f"{BASE_URL}/gather_pin",
        input_type="speech",
        timeout="6",
        speech_timeout=PIN_SPEECH_TIMEOUT,
        hints=PIN_HINTS,
    )
    xml = f'''<Response>
  <Gather {pin_gather}>
    {say("Thank you for calling the Milk Market Administrator Test Results Center. Please say your six digit PIN, one number at a time.")}
  </Gather>
  {say("We didn't receive any input. Goodbye.")}
</Response>'''
    return xml_response(xml)


def pin_retry_xml():
    pin_gather = gather_attrs(
        action=f"{BASE_URL}/gather_pin",
        input_type="speech",
        timeout="6",
        speech_timeout=PIN_SPEECH_TIMEOUT,
        hints=PIN_HINTS,
    )
    return f'''<Response>
  <Gather {pin_gather}>
    {say("I'm sorry, I didn't get that. Please say your six digit PIN one number at a time. For example: one, two, three, four, five, six.")}
  </Gather>
</Response>'''


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    pin = normalize_pin(raw)

    logger.info(f"RAW INPUT: '{raw}'")
    logger.info(f"PIN: '{pin}'")

    caller = get_from_number()
    call_id = get_call_id()

    if len(pin) > 6 and "0" in pin:
        log_call_to_csv(caller, call_id, pin, "PIN Rejected", "Failed pin attempt - zero heavy")
        pin_gather = gather_attrs(
            action=f"{BASE_URL}/gather_pin",
            input_type="speech",
            timeout="6",
            speech_timeout=PIN_SPEECH_TIMEOUT,
            hints=PIN_HINTS,
        )
        xml = f'''<Response>
  <Gather {pin_gather}>
    {say("Sorry, I didn't get exactly 6 digits. Try again. If your PIN contains zeros, you can say oh instead of zero.")}
  </Gather>
</Response>'''
        return xml_response(xml)

    if len(pin) != 6:
        log_call_to_csv(caller, call_id, pin, "PIN Rejected", "Failed pin attempt")
        return xml_response(pin_retry_xml())

    active_pins[call_id] = {"pin": pin}
    log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Successful pin attempt")

    spoken = speak_pin_digits(pin)
    menu_gather = gather_attrs(
        action=f"{BASE_URL}/confirm_pin",
        input_type="dtmf speech",
        timeout="7",
        speech_timeout=MENU_SPEECH_TIMEOUT,
        hints=MENU_HINTS,
    )
    xml = f'''<Response>
  {say(f"You said {spoken}. Am I right?")}
  <Gather {menu_gather}>
    {say("Say yes or press 1. Say no or press 2.")}
  </Gather>
</Response>'''
    return xml_response(xml)


@app.route("/confirm_pin", methods=["GET", "POST"])
def confirm_pin():
    digits = get_digits()
    speech = get_speech().lower()
    call_id = get_call_id()
    caller = get_from_number()

    is_yes = digits == "1" or any(
        w in speech for w in ["yes", "yeah", "yep", "correct", "right"]
    )

    if not is_yes:
        retry_inner = pin_retry_xml().replace("<Response>", "").replace("</Response>", "")
        xml = f'''<Response>
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
        xml = f'''<Response>
  {say("I found your PIN, but I do not have results for that PIN. Please check the number and try again.")}
  {pin_retry_xml().replace("<Response>", "").replace("</Response>", "")}
</Response>'''
        return xml_response(xml)

    log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Results read")

    xml = f'''<Response>
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

    menu_gather = gather_attrs(
        action=f"{BASE_URL}/handle_action",
        input_type="dtmf speech",
        timeout="7",
        speech_timeout=MENU_SPEECH_TIMEOUT,
        hints=MENU_HINTS,
    )
    xml += f'''
  <Gather {menu_gather}>
    {say("To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.")}
  </Gather>
  {say("We did not receive any input. Goodbye.")}
  <Hangup/>
</Response>'''

    return xml_response(xml)


@app.route("/handle_action", methods=["GET", "POST"])
def handle_action():
    digits = get_digits()
    speech = get_speech().lower()
    call_id = get_call_id()
    caller = get_from_number()
    pin = active_pins.get(call_id, {}).get("pin", "")

    if digits == "1" or "repeat" in speech or "again" in speech:
        log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Results repeated")
        xml = f'''<Response>
  {say("Repeating the results.")}
  <Redirect method="POST">{BASE_URL}/confirm_pin</Redirect>
</Response>'''
        return xml_response(xml)

    log_call_to_csv(caller, call_id, pin, "PIN Accepted", "Call ended")
    xml = f'''<Response>
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
    return xml_response("<Response></Response>")


# ====================== FORMAT HELPERS ======================
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
