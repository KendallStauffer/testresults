from flask import Flask, request, Response
import os
import logging
import re
from datetime import datetime

app = Flask(__name__)

BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")

TTS_VOICE = os.environ.get("TTS_VOICE", "AWS.Polly.Joanna")   # or Telnyx.NaturalHD.amanda
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")
ASR_ENGINE = os.environ.get("ASR_ENGINE", "Deepgram")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def xml_response(xml: str):
    return Response(xml, mimetype="application/xml")


def escape_xml(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def say(text: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{escape_xml(text)}</Say>'


def get_digits() -> str:
    return (request.values.get("Digits") or "").strip()


def get_speech() -> str:
    return (
        request.values.get("SpeechResult")
        or request.values.get("speech_result")
        or request.values.get("Speech")
        or ""
    ).strip()


def normalize_pin(raw: str) -> str:
    if not raw:
        return ""
    text = str(raw).lower().strip()
    word_map = {
        "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2",
        "three": "3", "four": "4", "for": "4", "five": "5", "six": "6",
        "seven": "7", "eight": "8", "ate": "8", "nine": "9"
    }
    tokens = re.findall(r"[a-z]+|\d", text)
    converted = [word_map.get(t, t) for t in tokens if t.isdigit() or t in word_map]
    return "".join(converted) or re.sub(r"\D", "", raw)


def pin_gather_xml(prompt: str):
    return f"""<Response>
  <Gather action="{BASE_URL}/gather_pin"
          method="POST"
          input="dtmf speech"
          numDigits="6"
          timeout="5"
          speechTimeout="4"          <!-- increased for natural pauses -->
          language="{TTS_LANGUAGE}"
          transcriptionEngine="{ASR_ENGINE}"
          hints="zero oh o one two three four five six seven eight nine">
    {say(prompt)}
  </Gather>
  {say("I did not receive anything. Let's try again.")}
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>"""


@app.route("/telnyx/voice", methods=["GET", "POST"])
@app.route("/voice", methods=["GET", "POST"])
def telnyx_voice():
    logger.info("=== New call started ===")
    return xml_response(pin_gather_xml("Please say or enter your 6 digit pin."))


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    logger.info("=== gather_pin HIT ===")
    logger.info(f"Full form: {dict(request.form)}")

    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    pin = normalize_pin(raw)

    logger.info(f"RAW: '{raw}' → PIN: '{pin}'")

    if len(pin) == 6:
        logger.info(f"✅ SUCCESS: {pin}")
        xml = f"""<Response>
  {say(f"Thank you. Pin {pin} received.")}
  <Hangup/>
</Response>"""
    else:
        logger.info("❌ No valid pin detected")
        xml = pin_gather_xml("Sorry, I didn't catch that. Please try again.")

    return xml_response(xml)


@app.route("/health")
def health():
    return {"status": "ok", "voice": TTS_VOICE, "asr": ASR_ENGINE}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)