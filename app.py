from flask import Flask, request, Response
import os
import logging
import re

app = Flask(__name__)

BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")
TTS_VOICE = os.environ.get("TTS_VOICE", "AWS.Polly.Joanna")
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")

GATHER_TIMEOUT = os.environ.get("GATHER_TIMEOUT", "12")
SPEECH_TIMEOUT = os.environ.get("SPEECH_TIMEOUT", "3")
ASR_ENGINE = os.environ.get("ASR_ENGINE", "Telnyx")

PIN_HINTS = os.environ.get(
    "PIN_HINTS",
    "zero, oh, o, q, one, won, two, too, to, three, tree, four, for, five, six, seven, eight, ate, nine, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def speak_digits(pin):
    return " ".join(list(str(pin)))


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

    if len(normalized) > 6:
        normalized = normalized[-6:]

    return normalized


def gather_xml(prompt):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather
    action="{BASE_URL}/gather_pin"
    method="POST"
    input="dtmf speech"
    timeout="{GATHER_TIMEOUT}"
    numDigits="6"
    speechTimeout="{SPEECH_TIMEOUT}"
    language="{TTS_LANGUAGE}"
    hints="{escape_xml(PIN_HINTS)}"
    transcriptionEngine="{ASR_ENGINE}">
    {say(prompt)}
  </Gather>
  {say("We did not receive any input. Let's try again.")}
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>'''
    return xml


@app.route("/telnyx/voice", methods=["GET", "POST"])
@app.route("/voice", methods=["GET", "POST"])
def voice():
    logger.info("=== Call started ===")
    logger.info(f"Voice request form: {dict(request.form)}")
    return xml_response(gather_xml("Please say or enter your 6 digit pin."))


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    logger.info("=== Gather received ===")
    logger.info(f"Form data: {dict(request.form)}")

    speech = request.form.get("SpeechResult", "").strip()
    digits = request.form.get("Digits", "").strip()
    confidence = request.form.get("Confidence", "").strip()

    raw = digits if digits else speech
    pin = normalize_pin(raw)

    logger.info(f"Digits field: '{digits}'")
    logger.info(f"SpeechResult field: '{speech}'")
    logger.info(f"Confidence field: '{confidence}'")
    logger.info(f"Raw input used: '{raw}'")
    logger.info(f"Normalized PIN: '{pin}'")

    if len(pin) == 6:
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say(f"Thank you. I heard your pin as {speak_digits(pin)}.")}
  <Pause length="1"/>
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>'''
    else:
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {say("Sorry, I did not get a complete 6 digit pin. Please try again.")}
  <Pause length="1"/>
  <Redirect method="POST">{BASE_URL}/telnyx/voice</Redirect>
</Response>'''

    return xml_response(xml)


@app.route("/health")
def health():
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "tts_voice": TTS_VOICE,
        "tts_language": TTS_LANGUAGE,
        "asr_engine": ASR_ENGINE,
        "gather_timeout": GATHER_TIMEOUT,
        "speech_timeout": SPEECH_TIMEOUT,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
