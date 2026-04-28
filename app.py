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

TTS_VOICE = os.environ.get("TTS_VOICE", "Telnyx.NaturalHD.jenny")
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")

os.makedirs(BACKUP_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

active_pins = {}
df = pd.DataFrame()


def xml_response(xml: str):
    return Response(xml, mimetype="application/xml")


def escape_xml(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def say(text: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{escape_xml(text)}</Say>'


def say_ssml(inner_ssml: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{inner_ssml}</Say>'


def get_call_id(): 
    return request.values.get("CallSid") or "unknown"

def get_from_number(): 
    return request.values.get("From") or "unknown"

def get_digits(): 
    return (request.values.get("Digits") or "").strip()

def get_speech(): 
    return (request.values.get("SpeechResult") or "").strip()


def log_call_to_csv(caller_id, call_id, entered_pin="", status="", notes=""):
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
    except: pass


def normalize_pin(raw: str) -> str:
    if not raw: return ""
    text = str(raw).lower().strip()
    word_map = {"zero":"0","oh":"0","o":"0","one":"1","two":"2","three":"3","four":"4","five":"5","six":"6","seven":"7","eight":"8","nine":"9"}
    tokens = re.findall(r"[a-z]+|\d", text)
    converted = [word_map.get(t, t) for t in tokens if t.isdigit() or t in word_map]
    return "".join(converted) or re.sub(r"\D", "", raw)


load_data = lambda: None  # placeholder - keep your full load_data if needed
# (add your full load_data, init_call_log, etc. if missing)


@app.route("/voice", methods=["GET", "POST"])
@app.route("/telnyx/voice", methods=["GET", "POST"])
def voice():
    xml = f'''<Response>
  <Gather action="{BASE_URL}/gather_pin" method="POST" input="dtmf speech" numDigits="6"
          timeout="1" speechTimeout="1" language="{TTS_LANGUAGE}"
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
          timeout="1" speechTimeout="1" language="{TTS_LANGUAGE}"
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
        return xml_response(pin_retry_xml())

    active_pins[get_call_id()] = {"pin": pin}
    spoken = " ".join(pin)

    xml = f'''<Response>
  {say(f"You said {spoken}. Am I right?")}
  <Gather action="{BASE_URL}/confirm_pin" method="POST" input="dtmf speech" numDigits="1"
          timeout="1" speechTimeout="1" language="{TTS_LANGUAGE}"
          hints="yes,yeah,yep,correct,right,one,no,wrong,two"
          transcriptionEngine="Deepgram">
    {say("Say yes or press 1. Say no or press 2.")}
  </Gather>
</Response>'''
    return xml_response(xml)


# Add your confirm_pin, handle_action, hangup, and all other routes from your original file here
# (keep them exactly as they were)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)