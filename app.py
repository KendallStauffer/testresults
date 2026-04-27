from flask import Flask, request, Response, render_template_string, send_file, jsonify
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ====================== CONFIG ======================
UPLOAD_PASSWORD = "ForUSDA!2026"
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "change-this-now")

BASE_URL = "https://testresults-1aja.onrender.com"

# Persistent disk paths
DATA_DIR = "/mnt/data"
CSV_PATH = os.path.join(DATA_DIR, "test_results_long.csv")
LOG_PATH = os.path.join(DATA_DIR, "call_logs.csv")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")



os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

active_pins = {}
df = pd.DataFrame()

# ====================== HELPERS ======================
def normalize_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe.columns = [c.strip().lower().replace(" ", "_") for c in dataframe.columns]
    return dataframe


def load_data():
    global df
    try:
        if not os.path.exists(CSV_PATH):
            df = pd.DataFrame()
            logger.info(f"No CSV found at {CSV_PATH}")
            return False

        loaded = pd.read_csv(CSV_PATH)
        loaded = normalize_columns(loaded)

        # Required columns
        if "pin_number" not in loaded.columns:
            raise ValueError("CSV missing Pin_Number / pin_number column")

        if "sequence_number" not in loaded.columns:
            loaded["sequence_number"] = 0

        # Make sure the IVR has the columns it expects
        if "day" not in loaded.columns:
            raise ValueError("CSV missing day column")

        for col in ["fat", "protein", "mun", "scc"]:
            if col not in loaded.columns:
                loaded[col] = 0

        loaded["pin_number"] = loaded["pin_number"].astype(str).str.strip().str.zfill(6)
        loaded["sequence_number"] = pd.to_numeric(loaded["sequence_number"], errors="coerce").fillna(0).astype(int)
        loaded["day"] = pd.to_numeric(loaded["day"], errors="coerce").fillna(0).astype(int)
        loaded["fat"] = pd.to_numeric(loaded["fat"], errors="coerce").fillna(0.0)
        loaded["protein"] = pd.to_numeric(loaded["protein"], errors="coerce").fillna(0.0)
        loaded["mun"] = pd.to_numeric(loaded["mun"], errors="coerce").fillna(0).astype(int)
        loaded["scc"] = pd.to_numeric(loaded["scc"], errors="coerce").fillna(0).astype(int)

        df = loaded
        logger.info(f"✅ Loaded {len(df)} records from {CSV_PATH}")
        return True

    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        df = pd.DataFrame()
        return False

def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=[
            "Timestamp", "CallerID", "CallUUID", "EnteredPIN", "Status", "Notes"
        ]).to_csv(LOG_PATH, index=False)
        logger.info("✅ Created call_logs.csv")
    else:
        logger.info("call_logs.csv already exists - append only")

def log_call_to_csv(caller_id, call_uuid, entered_pin="", status="PIN Rejected", notes=""):
    try:
        file_exists = os.path.exists(LOG_PATH)
        new_row = pd.DataFrame([{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "CallerID": caller_id,
            "CallUUID": call_uuid,
            "EnteredPIN": entered_pin,
            "Status": status,
            "Notes": notes
        }])
        new_row.to_csv(LOG_PATH, mode="a", header=not file_exists, index=False)
        logger.info(f"✅ APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"❌ Failed to append to call_logs.csv: {e}")

def speak_pin_digits(pin: str):
    return " ".join(list(pin))

def plivo_response(xml: str):
    return Response(xml, mimetype="application/xml")

def log_call(event: str, extra: dict = None):
    if extra is None:
        extra = {}
    call_uuid = request.values.get("CallUUID", "unknown")
    from_number = request.values.get("From", "unknown")
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallUUID={call_uuid} | From={from_number} {details}")

def pin_retry_xml():
    return f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6"
             digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
             hints="0,1,2,3,4,5,6,7,8,9,zero,oh,o" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that. Please say your six digit PIN one number at a time.
      For example: one, two, three, four, five, six.
    </Speak>
  </GetInput>
</Response>"""

# ====================== STARTUP ======================

load_data()
init_call_log()

# ====================== ADMIN ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return jsonify({
        "ok": True,
        "records": record_count,
        "call_logs": log_count,
        "csv_path": CSV_PATH,
        "csv_exists": os.path.exists(CSV_PATH),
        "log_path": LOG_PATH,
        "log_exists": os.path.exists(LOG_PATH)
    })

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
def upload_csv_manual():
    """
    Manual browser upload for you.
    """
    if request.method == "POST":
        if request.form.get("password") != UPLOAD_PASSWORD:
            return "<h2>Wrong password</h2><a href='/upload'>Try again</a>", 401

        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".csv"):
            return "<h2>Please upload a valid CSV</h2>", 400

        temp_name = secure_filename(file.filename)
        temp_path = os.path.join(DATA_DIR, f"manual_{temp_name}")
        file.save(temp_path)

        try:
            test_df = pd.read_csv(temp_path)
            test_df = normalize_columns(test_df)

            if "pin_number" not in test_df.columns:
                raise ValueError("CSV missing Pin_Number / pin_number column")
            if "day" not in test_df.columns:
                raise ValueError("CSV missing day column")

            if os.path.exists(CSV_PATH):
                backup_path = os.path.join(
                    BACKUP_DIR,
                    f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                shutil.copy2(CSV_PATH, backup_path)

            shutil.move(temp_path, CSV_PATH)
            load_data()

            return f"<h2>✅ Uploaded! {len(df)} records loaded.</h2><a href='/status'>Status</a>"

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return f"<h2>Upload failed: {e}</h2><a href='/upload'>Try again</a>", 400

    return """
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">← Status</a>
    """

@app.route("/upload-csv", methods=["POST"])
def upload_csv_api():
    """
    Automated upload endpoint for customer script.
    """
    try:
        api_key = request.headers.get("X-API-Key", "")
        if api_key != UPLOAD_API_KEY:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file part"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"ok": False, "error": "No file selected"}), 400

        if not file.filename.lower().endswith(".csv"):
            return jsonify({"ok": False, "error": "Only CSV files are allowed"}), 400

        temp_name = secure_filename(file.filename)
        temp_path = os.path.join(DATA_DIR, f"api_{temp_name}")
        file.save(temp_path)

        test_df = pd.read_csv(temp_path)
        test_df = normalize_columns(test_df)

        if "pin_number" not in test_df.columns:
            raise ValueError("CSV missing Pin_Number / pin_number column")
        if "day" not in test_df.columns:
            raise ValueError("CSV missing day column")

        if os.path.exists(CSV_PATH):
            backup_path = os.path.join(
                BACKUP_DIR,
                f"test_results_long_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            shutil.copy2(CSV_PATH, backup_path)

        shutil.move(temp_path, CSV_PATH)
        load_data()

        return jsonify({
            "ok": True,
            "message": "CSV uploaded and reloaded successfully",
            "rows_loaded": len(df),
            "csv_path": CSV_PATH
        })

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ====================== VOICE FLOW ======================
@app.route("/voice", methods=["GET", "POST"])
def voice():
    log_call("INCOMING_CALL")
    xml = f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6"
             digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
             hints="0,1,2,3,4,5,6,7,8,9,zero,oh,o" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Thank you for calling the Milk Market Administrator Test Results Center.
      Please say or enter your 6 digit PIN.
    </Speak>
  </GetInput>
  <Speak voice="Polly.Joanna" language="en-US">We didn't receive any input. Goodbye.</Speak>
</Response>"""
    return plivo_response(xml)

@app.route("/gather_pin", methods=["GET"])
def gather_pin():
    try:
        digits = request.values.get("Digits", "").strip()
        speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).strip()
        raw = digits if digits else speech

        logger.info(f"RAW INPUT: '{raw}'")

        pin = re.sub(r"\D", "", raw)
        logger.info(f"PIN: '{pin}'")

        caller = request.values.get("From", "unknown")
        call_uuid = request.values.get("CallUUID", "unknown")

        # Special zero-heavy retry
        if len(pin) > 6 and "0" in pin:
            log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", "Failed pin attempt - zero heavy")
            xml = f"""<Response>
  <GetInput action="{BASE_URL}/gather_pin" method="GET" inputType="dtmf speech" numDigits="6"
             digitEndTimeout="5" speechEndTimeout="3" speechModel="command_and_search"
             hints="0,1,2,3,4,5,6,7,8,9,zero,oh,o" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Sorry, I didn't get exactly 6 digits. For some reason I am better at hearing the letter O than the word zero.
      Please try again using O for zeros.
    </Speak>
  </GetInput>
</Response>"""
            return plivo_response(xml)

        # Invalid PIN
        if len(pin) != 6:
            log_call_to_csv(caller, call_uuid, pin, "PIN Rejected", "Failed pin attempt")
            return plivo_response(pin_retry_xml())

        # Successful PIN
        active_pins[call_uuid] = {"pin": pin}
        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Successful pin attempt")

        spoken = speak_pin_digits(pin)
        xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">You said {spoken}. Am I right?</Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="GET" inputType="dtmf speech" numDigits="1"
             digitEndTimeout="10" speechEndTimeout="2" hints="1,2,yes,no" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">Say yes or press 1. Say no or press 2.</Speak>
  </GetInput>
</Response>"""
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /gather_pin: {e}")
        return plivo_response(pin_retry_xml())

@app.route("/confirm_pin", methods=["GET"])
def confirm_pin():
    try:
        digits = request.values.get("Digits", "").strip()
        speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()
        call_uuid = request.values.get("CallUUID")
        caller = request.values.get("From", "unknown")

        is_yes = digits == "1" or any(w in speech for w in ["yes", "yeah", "yep", "correct", "right"])

        if not is_yes:
            logger.info("User said NO to PIN confirmation")
            return plivo_response(pin_retry_xml())

        pin = active_pins.get(call_uuid, {}).get("pin")
        if not pin:
            logger.info("No pin found in active_pins")
            return plivo_response(pin_retry_xml())

        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results read")

        results_df = df[df["pin_number"] == pin].sort_values("sequence_number")
        if results_df.empty:
            logger.info(f"No results found for PIN {pin}")
            return plivo_response(pin_retry_xml())

        xml = """<Response>
  <Speak voice="Polly.Joanna" language="en-US">Here are your milk test results.</Speak>"""

        for _, row in results_df.iterrows():
            day = int(row.get("day", 0))
            fat = float(row.get("fat", 0))
            protein = float(row.get("protein", 0))
            scc = int(row.get("scc", 0))
            mun = int(row.get("mun", 0))

            xml += f"""
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
  </Speak>"""

            if mun > 0:
                xml += f"""
  <Speak voice="Polly.Joanna" language="en-US">
    <prosody rate="medium">Munn {mun}.</prosody>
  </Speak>"""

        xml += f"""
  <GetInput action="{BASE_URL}/handle_action" method="GET" inputType="dtmf speech" numDigits="1"
             digitEndTimeout="10" speechEndTimeout="2"
             hints="1,2,repeat,goodbye,end" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      To hear these results again, say repeat or press 1.
      To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
</Response>"""
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /confirm_pin: {e}")
        return plivo_response(pin_retry_xml())

@app.route("/handle_action", methods=["GET"])
def handle_action():
    try:
        digits = request.values.get("Digits", "").strip()
        speech = (request.values.get("SpeechResult", "") or request.values.get("Speech", "")).lower()
        call_uuid = request.values.get("CallUUID")
        caller = request.values.get("From", "unknown")
        pin = active_pins.get(call_uuid, {}).get("pin", "")

        logger.info(f"User action input: Digits='{digits}' | Speech='{speech}' | PIN='{pin}'")

        if digits == "1" or "repeat" in speech:
            log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Results repeated")
            xml = f"""<Response>
  <Speak voice="Polly.Joanna" language="en-US">Repeating the results.</Speak>
  <Redirect method="GET">{BASE_URL}/confirm_pin</Redirect>
</Response>"""
            return plivo_response(xml)

        log_call_to_csv(caller, call_uuid, pin, "PIN Accepted", "Call ended")
        if call_uuid in active_pins:
            del active_pins[call_uuid]

        xml = """<Response>
  <Speak voice="Polly.Joanna" language="en-US">Thank you for calling. Goodbye.</Speak>
  <Hangup/>
</Response>"""
        return plivo_response(xml)

    except Exception as e:
        logger.error(f"Error in /handle_action: {e}")
        xml = f"""<Response>
  <GetInput action="{BASE_URL}/handle_action" method="GET"
            inputType="dtmf speech" numDigits="1" digitEndTimeout="10" speechEndTimeout="2"
            hints="1,2,repeat,goodbye,end" language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      I'm sorry, I didn't get that. To hear your results again, say repeat or press 1.
      To end the call, say goodbye or press 2.
    </Speak>
  </GetInput>
</Response>"""
        return plivo_response(xml)

@app.route("/hangup", methods=["POST"])
def hangup():
    call_uuid = request.values.get("CallUUID")
    pin = active_pins.get(call_uuid, {}).get("pin", "")
    caller = request.values.get("From", "unknown")
    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    logger.info(f"Call hung up - PIN={pin} Status={status}")
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")

    if call_uuid in active_pins:
        del active_pins[call_uuid]

    return Response("<Response></Response>", mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)
