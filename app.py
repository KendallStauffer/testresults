from flask import Flask, request, Response
import os
import logging
import re
from datetime import datetime

app = Flask(__name__)

BASE_URL = os.environ.get("BASE_URL", "https://your-render-app.onrender.com").rstrip("/")

# Change these in Render Environment Variables.
TTS_VOICE = os.environ.get("TTS_VOICE", "Telnyx.NaturalHD.amanda")
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
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def say(text: str) -> str:
    return f'<Say voice="{TTS_VOICE}" language="{TTS_LANGUAGE}">{escape_xml(text)}</Say>'


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
        or request.values.get("speech_result")
        or request.values.get("Speech")
        or request.values.get("speech")
        or request.values.get("transcription")
        or request.values.get("TranscriptionText")
        or ""
    ).strip()


def normalize_pin(raw: str) -> str:
    if not raw:
        return ""

    text = str(raw).lower().strip()
    word_map = {
        "zero": "0",
        "oh": "0",
        "o": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "for": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "ate": "8",
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

    return re.sub(r"\D", "", str(raw))


def pin_gather_xml(prompt: str):
    return f"""<Response>
  <Gather action="{BASE_URL}/gather_pin"
          method="POST"
          input="dtmf speech"
          numDigits="6"
          timeout="2"
          speechTimeout="3"
          language="{TTS_LANGUAGE}"
          transcriptionEngine="{ASR_ENGINE}"
          hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine">
    {say(prompt)}
  </Gather>
  {say("I did not receive anything. Let's try again.")}
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>"""


@app.route("/", methods=["GET"])
def home():
    return "Telnyx diagnostic IVR is running."


@app.route("/health", methods=["GET"])
def health():
    return {
        "ok": True,
        "voice": TTS_VOICE,
        "language": TTS_LANGUAGE,
        "asr_engine": ASR_ENGINE,
        "base_url": BASE_URL,
    }


@app.route("/telnyx/voice", methods=["GET", "POST"])
@app.route("/voice", methods=["GET", "POST"])
def telnyx_voice():
    logger.info("=== /telnyx/voice HIT ===")
    logger.info(f"METHOD: {request.method}")
    logger.info(f"VALUES: {dict(request.values)}")

    return xml_response(pin_gather_xml("Please say or enter your six digit PIN."))


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    logger.info("=== /gather_pin HIT ===")
    logger.info(f"TIME: {datetime.utcnow().isoformat()}Z")
    logger.info(f"METHOD: {request.method}")
    logger.info(f"FORM: {dict(request.form)}")
    logger.info(f"ARGS: {dict(request.args)}")
    logger.info(f"VALUES: {dict(request.values)}")

    digits = get_digits()
    speech = get_speech()
    raw = digits if digits else speech
    pin = normalize_pin(raw)

    logger.info(f"DIGITS: '{digits}'")
    logger.info(f"SPEECH: '{speech}'")
    logger.info(f"RAW INPUT: '{raw}'")
    logger.info(f"PIN: '{pin}'")

    heard = raw if raw else "nothing"
    pin_spoken = " ".join(pin) if pin else "blank"

    xml = f"""<Response>
  {say(f"I heard raw input: {heard}. The normalized PIN was: {pin_spoken}.")}
  <Pause length="1"/>
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>"""
    return xml_response(xml)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
