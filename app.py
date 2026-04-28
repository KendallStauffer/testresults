from flask import Flask, request, Response, render_template_string, send_file
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime

app = Flask(__name__)

UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "CHANGE_ME")
CSV_PATH = os.environ.get("CSV_PATH", "/mnt/data/test_results_long.csv")
LOG_PATH = os.environ.get("LOG_PATH", "/mnt/data/call_logs.csv")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/mnt/data/backups")
BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")

# ==================== VOICE SETTINGS ====================
TTS_VOICE = os.environ.get("TTS_VOICE", "Telnyx.NaturalHD.amanda")
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")

os.makedirs(BACKUP_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

active_pins = {}
df = pd.DataFrame()


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


def get_call_id() -> str:
    return request.values.get("CallSid") or "unknown"


def get_from_number() -> str:
    return request.values.get("From") or "unknown"


def get_digits() -> str:
    return (request.values.get("Digits") or "").strip()


def get_speech() -> str:
    return (request.values.get("SpeechResult") or "").strip()


def speak_pin_digits(pin: str):
    return " ".join(list(str(pin)))


def normalize_pin(raw: str) -> str:
    if not raw:
        return ""
    text = str(raw).lower().strip()
    word_map = {
        "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2",
        "three": "3", "four": "4", "five": "5", "six": "6",
        "seven": "7", "eight": "8", "nine": "9"
    }
    tokens = re.findall(r"[a-z]+|\d", text)
    converted = [word_map.get(t, t) for t in tokens if t.isdigit() or t in word_map]
    return "".join(converted) or re.sub(r"\D", "", raw)


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
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")


def log_call_to_csv(caller_id, call_id, entered_pin="", status="PIN Rejected", notes=""):
    try:
        new_row = pd.DataFrame([{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "CallerID": caller_id,
            "CallID": call_id,
            "EnteredPIN": entered_pin,
            "Status": status,
            "Notes": notes,
        }])
        new_row.to_csv(LOG_PATH, mode="a", header=False, index=False)
    except Exception as e:
        logger.error(f"Failed to log call: {e}")


load_data()


# ====================== MAIN ENTRY ======================
@app.route("/voice", methods=["GET", "POST"])
@app.route("/telnyx/voice", methods=["GET", "POST"])
def voice():
    xml = f'''<Response>
  <Gather action="{BASE_URL}/gather_pin" method="POST" input="dtmf speech" numDigits="6"
          timeout="4" speechTimeout="3" language="{TTS_LANGUAGE}"
          hints="zero,oh,o,0,one,two,three,four,five,six,seven,eight,nine"
          transcriptionEngine="Deepgram">
    {say("Please say or enter your 6 digit pin.")}
  </Gather>
  {say("We didn't receive any input. Goodbye.")}
</Response>'''
    return xml_response(xml)


def pin_retry_xml():
    return f'''<Response>
  <Gather action="{BASE_URL}/gather_pin" method="POST" input="dtmf speech" numDigits="6"
          timeout="4" speechTimeout="3" language="{TTS_LANGUAGE}"
          hints="zero,oh,o,0,one,two,three,four,five,six,seven,eight,nine"
          transcriptionEngine="Deepgram">
    {say("I'm sorry, I didn't get that. Please say your six digit PIN one number at a time.")}
  </Gather>
</Response>'''


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    pin = normalize_pin(raw)

    if len(pin) != 6:
        log_call_to_csv(get_from_number(), get_call_id(), pin, "PIN Rejected", "Failed pin attempt")
        return xml_response(pin_retry_xml())

    active_pins[get_call_id()] = {"pin": pin}
    spoken = speak_pin_digits(pin)

    xml = f'''<Response>
  {say(f"You said {spoken}. Am I right?")}
  <Gather action="{BASE_URL}/confirm_pin" method="POST" input="dtmf speech" numDigits="1"
          timeout="4" speechTimeout="3" language="{TTS_LANGUAGE}"
          hints="yes,yeah,yep,correct,right,one,no,wrong,two"
          transcriptionEngine="Deepgram">
    {say("Say yes or press 1. Say no or press 2.")}
  </Gather>
</Response>'''
    return xml_response(xml)


@app.route("/confirm_pin", methods=["GET", "POST"])
def confirm_pin():
    digits = get_digits()
    speech = get_speech().lower()
    call_id = get_call_id()
    is_yes = digits == "1" or any(w in speech for w in ["yes", "yeah", "yep", "correct", "right"])

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
        xml = f'''<Response>
  {say("I found your PIN, but I do not have results for that PIN. Please check the number and try again.")}
  {pin_retry_xml().replace("<Response>", "").replace("</Response>", "")}
</Response>'''
        return xml_response(xml)

    xml = f'''<Response>
  {say("Here are your milk test results.")}'''

    for _, row in results_df.iterrows():
        day = int(float(row.get("day", 1)))
        fat = float(row.get("fat", 0))
        protein = float(row.get("protein", 0))
        scc = int(float(row.get("scc", 0)))
        mun = int(float(row.get("mun", 0)))

        result_ssml = f'''
    <prosody rate="medium">
      Sample from the {day}th.
      <break time="600ms"/>
      Butterfat {fat:.2f} percent.
      <break time="600ms"/>
      Protein {protein:.2f} percent.
      <break time="600ms"/>
      Somatic cell count {scc:,}.
      <break time="600ms"/>
    </prosody>'''
        xml += "\n  " + say_ssml(result_ssml)
        if mun > 0:
            xml += "\n  " + say_ssml(f'<prosody rate="medium">Mun {mun}.</prosody>')

    xml += f'''
  <Gather action="{BASE_URL}/handle_action" method="POST" input="dtmf speech" numDigits="1"
          timeout="4" speechTimeout="3" language="{TTS_LANGUAGE}"
          hints="repeat,goodbye,again,one,two"
          transcriptionEngine="Deepgram">
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
    if digits == "1" or "repeat" in speech or "again" in speech:
        xml = f'''<Response>
  {say("Repeating the results.")}
  <Redirect method="POST">{BASE_URL}/gather_pin</Redirect>
</Response>'''
        return xml_response(xml)

    xml = f'''<Response>
  {say("Thank you for calling. Goodbye.")}
  <Hangup/>
</Response>'''
    return xml_response(xml)


# Other routes (status, upload, etc.)
@app.route("/health")
def health():
    return {"status": "ok", "records": len(df)}

@app.route("/")
def home():
    return '<h2>MMA Test Results IVR</h2><p><a href="/status">Status</a></p>'


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
