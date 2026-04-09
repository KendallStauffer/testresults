from flask import Flask, request, Response, render_template_string, send_file
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime

app = Flask(__name__)

UPLOAD_PASSWORD = "ForUSDA!2026"
CSV_PATH = "/mnt/data/test_results_long.csv"
LOG_PATH = "/mnt/data/call_logs.csv"
BACKUP_DIR = "/mnt/data/backups"
BASE_URL = "https://testresults-1aja.onrender.com"

os.makedirs(BACKUP_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

active_calls = {}
df = pd.DataFrame()

REQUIRED_DEFAULTS = {
    "pin_number": "",
    "sequence_number": 1,
    "day": 1,
    "fat": 0,
    "protein": 0,
    "mun": 0,
    "scc": 0,
    "latest_test_date": "",
}

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
GOODBYE_WORDS = {"goodbye", "bye", "end", "done", "stop"}

def plivo_response(xml: str):
    return Response(xml, mimetype="application/xml")

def normalize_columns(columns):
    return [str(c).strip().lower().replace(" ", "_") for c in columns]

def ensure_required_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe is None:
        dataframe = pd.DataFrame()

    dataframe = dataframe.copy()
    dataframe.columns = normalize_columns(dataframe.columns)

    for col, default in REQUIRED_DEFAULTS.items():
        if col not in dataframe.columns:
            dataframe[col] = default

    return dataframe

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

def ordinal(n):
    n = safe_int(n, 1)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def speak_pin_digits(pin: str):
    return " ".join(list(str(pin)))

def extract_digits_from_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower().strip()
    text = text.replace("-", " ").replace(",", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text)

    tokens = re.findall(r"[a-zA-Z0-9]+", text)
    parsed = []

    for token in tokens:
        if token.isdigit():
            parsed.extend(list(token))
        elif token in NUMBER_WORDS:
            parsed.append(NUMBER_WORDS[token])

    return "".join(parsed)

def interpret_yes_no(digits: str, speech: str):
    speech = (speech or "").lower().strip()

    if digits == "1":
        return True
    if digits == "2":
        return False

    if any(word in speech for word in YES_WORDS):
        return True
    if any(word in speech for word in NO_WORDS):
        return False

    return None

def interpret_action(digits: str, speech: str):
    speech = (speech or "").lower().strip()

    if digits == "1":
        return "repeat"
    if digits == "2":
        return "goodbye"

    if any(word in speech for word in REPEAT_WORDS):
        return "repeat"
    if any(word in speech for word in GOODBYE_WORDS):
        return "goodbye"

    return None

def get_call_uuid():
    return request.values.get("CallUUID", "unknown")

def get_caller():
    return request.values.get("From", "unknown")

def init_call_state(call_uuid):
    if call_uuid not in active_calls:
        active_calls[call_uuid] = {"pin": "", "results_reads": 0}

def clear_call_state(call_uuid):
    if call_uuid in active_calls:
        del active_calls[call_uuid]

def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(
            columns=["Timestamp", "CallerID", "CallUUID", "EnteredPIN", "Status", "Notes"]
        ).to_csv(LOG_PATH, index=False)
        logger.info("Created new call_logs.csv")
    else:
        logger.info("call_logs.csv already exists - append only mode")

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

        header_needed = not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0
        new_row.to_csv(LOG_PATH, mode="a", header=header_needed, index=False)
        logger.info(f"APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"Failed to append to call_logs.csv: {e}")

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
  <Speak voice="Polly.Joanna" language="en-US">We still did not receive a valid PIN. Goodbye.</Speak>
  <Hangup/>
</Response>"""

def goodbye_xml():
    return """<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
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
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine,goodbye,bye" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Please try another six digit PIN now, or say goodbye to end the call.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No new PIN was received. Goodbye.</Speak>
  <Hangup/>
</Response>"""

def load_data():
    global df
    try:
        if not os.path.exists(CSV_PATH):
            logger.warning(f"CSV file not found at {CSV_PATH}")
            df = ensure_required_columns(pd.DataFrame())
            return False

        # Read EVERYTHING as string so pandas does not reinterpret PINs
        temp_df = pd.read_csv(CSV_PATH, dtype=str)
        logger.info(f"CSV file loaded from {CSV_PATH}")
        logger.info(f"Raw CSV columns before normalization: {list(temp_df.columns)}")
        logger.info(f"Raw row count before normalization: {len(temp_df)}")

        temp_df = ensure_required_columns(temp_df)
        logger.info(f"Normalized CSV columns: {list(temp_df.columns)}")

        # Keep exact digits only. Do NOT pad, do NOT guess, do NOT insert zeros.
        temp_df["pin_number"] = (
            temp_df["pin_number"]
            .astype(str)
            .str.strip()
            .str.replace(".0", "", regex=False)
            .str.replace(r"\D", "", regex=True)
        )

        temp_df["sequence_number"] = pd.to_numeric(temp_df["sequence_number"], errors="coerce").fillna(1)
        temp_df.loc[temp_df["sequence_number"] <= 0, "sequence_number"] = 1

        temp_df["day"] = pd.to_numeric(temp_df["day"], errors="coerce").fillna(1)
        temp_df.loc[temp_df["day"] <= 0, "day"] = 1

        temp_df["fat"] = pd.to_numeric(temp_df["fat"], errors="coerce").fillna(0)
        temp_df["protein"] = pd.to_numeric(temp_df["protein"], errors="coerce").fillna(0)
        temp_df["mun"] = pd.to_numeric(temp_df["mun"], errors="coerce").fillna(0)
        temp_df["scc"] = pd.to_numeric(temp_df["scc"], errors="coerce").fillna(0)

        df = temp_df

        logger.info(f"Loaded {len(df)} records from CSV")
        logger.info(f"Sample loaded PINs: {df['pin_number'].dropna().astype(str).head(20).tolist()}")

        # Helpful diagnostics for dropped-zero problems
        pin_lengths = df["pin_number"].astype(str).str.len().value_counts(dropna=False).to_dict()
        logger.info(f"PIN length counts in CSV: {pin_lengths}")

        short_pins = df[df["pin_number"].astype(str).str.len() != 6]["pin_number"].astype(str).head(20).tolist()
        logger.info(f"Non-6-digit PIN samples in CSV: {short_pins}")

        return True

    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        df = ensure_required_columns(pd.DataFrame())
        return False

def build_results_xml(pin, intro="Here are your milk test results."):
    global df
    df = ensure_required_columns(df)

    if "pin_number" not in df.columns:
        logger.error(f"pin_number missing. Current columns: {list(df.columns)}")
        return no_results_xml(pin)

    pin = str(pin).strip()
    available = df["pin_number"].astype(str).str.strip()
    results_df = df[available == pin].copy()

    logger.info(f"LOOKUP REQUESTED PIN: '{pin}'")
    logger.info(f"LOOKUP MATCH COUNT: {len(results_df)}")

    if results_df.empty:
        nearby = df[df["pin_number"].astype(str).str.contains(pin[:3], na=False)]["pin_number"].astype(str).head(20).tolist()
        logger.info(f"Nearby CSV PIN samples for prefix '{pin[:3]}': {nearby}")
        logger.info(f"No results found for PIN {pin}")
        return no_results_xml(pin)

    logger.info(f"Matched CSV rows for PIN {pin}:")
    try:
        logger.info(results_df[["pin_number", "sequence_number", "day", "fat", "protein", "mun", "scc"]].to_string(index=False))
    except Exception as e:
        logger.error(f"Could not log matched rows cleanly: {e}")

    results_df = results_df.sort_values(["sequence_number", "day"])

    xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">{intro}</Speak>"""

    for _, row in results_df.iterrows():
        day = safe_int(row.get("day", 1), 1)
        fat = safe_float(row.get("fat", 0), 0.0)
        protein = safe_float(row.get("protein", 0), 0.0)
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
    <prosody rate="medium">Munn {mun}.</prosody>
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

load_data()
init_call_log()

@app.route("/status")
def status():
    global df
    df = ensure_required_columns(df)
    record_count = len(df) if not df.empty else 0
    sample_pins = df["pin_number"].dropna().astype(str).head(20).tolist() if "pin_number" in df.columns else []
    pin_lengths = df["pin_number"].astype(str).str.len().value_counts(dropna=False).to_dict() if "pin_number" in df.columns else {}

    return render_template_string("""
        <h2>MMA Status</h2>
        <p>Records: {{ record_count }}</p>
        <p>CSV Path: {{ csv_path }}</p>
        <p>Columns: {{ columns }}</p>
        <p>Sample PINs: {{ sample_pins }}</p>
        <p>PIN Length Counts: {{ pin_lengths }}</p>
        <p><a href="/upload">Upload CSV</a> | <a href="/logs">View Logs</a> | <a href="/download_logs">Download Logs</a></p>
    """,
        record_count=record_count,
        csv_path=CSV_PATH,
        columns=list(df.columns),
        sample_pins=sample_pins,
        pin_lengths=pin_lengths
    )

@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"

    try:
        logs_df = pd.read_csv(LOG_PATH).sort_values("Timestamp", ascending=False).head(200)
        html = logs_df.to_html(index=False)
    except Exception as e:
        html = f"<p>Could not read logs: {e}</p>"

    return render_template_string("""
        <h2>Recent Call Logs (200 newest)</h2>
        <a href="/status">← Back</a> | <a href="/download_logs">Download Full CSV</a><br><br>
        {{ html|safe }}
        <style>table, th, td {border:1px solid black; padding:8px;}</style>
    """, html=html)

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
        if not file or not file.filename.endswith(".csv"):
            return "<h2>Please upload a valid CSV</h2>", 400

        try:
            if os.path.exists(CSV_PATH):
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                shutil.copy(CSV_PATH, os.path.join(BACKUP_DIR, backup_name))

            file.save(CSV_PATH)
            ok = load_data()

            if ok:
                return f"<h2>Uploaded. {len(df)} records loaded.</h2><a href='/status'>Status</a>"
            return "<h2>CSV uploaded, but loading failed. Check /status and logs.</h2><a href='/status'>Status</a>"
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return f"<h2>Upload failed: {e}</h2><a href='/upload'>Try again</a>", 500

    return """
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">← Status</a>
    """

@app.route("/voice", methods=["GET", "POST"])
def voice():
    call_uuid = get_call_uuid()
    init_call_state(call_uuid)
    logger.info(f"INCOMING_CALL | CallUUID={call_uuid} | From={get_caller()}")

    xml = f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="POST" inputType="dtmf speech" numDigits="6"
            digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Thank you for calling the Milk Market Administrator Test Results Center.
      Please say or enter your 6 digit PIN.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We did not receive any input. Goodbye.</Speak>
  <Hangup/>
</Response>"""
    return plivo_response(xml)

@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    digits = request.values.get("Digits", "").strip()
    speech = request.values.get("SpeechResult", "").strip() or request.values.get("Speech", "").strip()
    raw = digits if digits else speech
    input_mode = "dtmf" if digits else "speech"

    caller = get_caller()
    call_uuid = get_call_uuid()
    init_call_state(call_uuid)

    logger.info(f"RAW INPUT: '{raw}'")
    logger.info(f"INPUT MODE: {input_mode}")
    logger.info(f"DIGITS FIELD: '{digits}'")
    logger.info(f"SPEECH FIELD: '{speech}'")

    lower_raw = (raw or "").lower().strip()
    if lower_raw in {"goodbye", "bye", "end", "stop"}:
        log_call_to_csv(caller, call_uuid, "", "PIN Accepted", "Caller said goodbye at PIN prompt")
        clear_call_state(call_uuid)
        return plivo_response(goodbye_xml())

    pin = extract_digits_from_text(raw)
    logger.info(f"PARSED PIN: '{pin}'")
    logger.info(f"PARSED PIN LENGTH: {len(pin)}")

    if len(pin) != 6:
        log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", f"Failed pin attempt via {input_mode}")
        return plivo_response(pin_retry_xml())

    active_calls[call_uuid]["pin"] = pin
    logger.info(f"SUCCESSFUL PIN: {pin}")
    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", f"Successful pin attempt via {input_mode}")

    spoken = speak_pin_digits(pin)
    xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">You said {spoken}. Am I right?</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Let's start over.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>"""
    return plivo_response(xml)

@app.route("/confirm_pin", methods=["GET", "POST"])
def confirm_pin():
    digits = request.values.get("Digits", "").strip()
    speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()

    call_uuid = get_call_uuid()
    caller = get_caller()
    init_call_state(call_uuid)

    logger.info(f"CONFIRM INPUT | digits='{digits}' | speech='{speech}'")

    decision = interpret_yes_no(digits, speech)

    if decision is False:
        return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">Okay, let's try again.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>""")

    if decision is None:
        return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">Sorry, I didn't catch that.</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="POST" inputType="dtmf speech" numDigits="1"
            digitEndTimeout="10" speechEndTimeout="2" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">No response received. Let's start over.</Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>""")

    pin = active_calls.get(call_uuid, {}).get("pin", "")
    if not pin:
        logger.error("PIN missing from call state during confirm_pin")
        return plivo_response(pin_retry_xml("We lost your PIN entry. Please enter your six digit PIN again."))

    logger.info(f"CONFIRMED PIN FOR LOOKUP: '{pin}'")
    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results read")
    active_calls[call_uuid]["results_reads"] += 1

    return plivo_response(build_results_xml(pin))

@app.route("/handle_action", methods=["GET", "POST"])
def handle_action():
    digits = request.values.get("Digits", "").strip()
    speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()

    call_uuid = get_call_uuid()
    caller = get_caller()
    init_call_state(call_uuid)

    pin = active_calls.get(call_uuid, {}).get("pin", "")
    action = interpret_action(digits, speech)

    logger.info(f"HANDLE ACTION | digits='{digits}' | speech='{speech}' | resolved_action='{action}' | pin='{pin}'")

    if action == "repeat":
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results repeated")
        return plivo_response(build_results_xml(pin, intro="Repeating your milk test results."))

    log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Call ended")
    clear_call_state(call_uuid)
    return plivo_response(goodbye_xml())

@app.route("/hangup", methods=["GET", "POST"])
def hangup():
    call_uuid = get_call_uuid()
    caller = get_caller()
    pin = active_calls.get(call_uuid, {}).get("pin", "")

    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    logger.info(f"HANGUP | CallUUID={call_uuid} | Caller={caller} | PIN='{pin}' | Status={status}")
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")
    clear_call_state(call_uuid)

    return Response("<Response></Response>", mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)