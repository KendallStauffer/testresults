from flask import Flask, request, Response
import plivo
from plivo import plivoxml
import logging
import os
import re

app = Flask(__name__)

BASE_URL = "https://testresults-1aja.onrender.com"

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def plivo_response(resp):
    return Response(resp.to_string(), mimetype="application/xml")

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    logger.info("=== /voice called ===")
    response = plivoxml.ResponseElement()

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/gather_pin",
        method="GET",
        input_type="dtmf speech",
        num_digits=6,
        digit_end_timeout=8,
        speech_end_timeout=3,
        language="en-US"
    )

    get_input.add(plivoxml.SpeakElement(
        "Please say or enter your 6 digit PIN.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)
    return plivo_response(response)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()

    raw = digits if digits else speech
    logger.info(f"GATHER_PIN | raw = '{raw}'")

    # Simple regex - remove everything that is not a digit
    pin = re.sub(r'\D', '', raw)

    logger.info(f"Cleaned pin = '{pin}' (length = {len(pin)})")

    response = plivoxml.ResponseElement()

    if len(pin) == 6:
        response.add(plivoxml.SpeakElement(f"Thank you. You said {pin}. Goodbye.", voice="Polly.Joanna", language="en-US"))
    else:
        response.add(plivoxml.SpeakElement("Sorry, I didn't get 6 digits. Goodbye.", voice="Polly.Joanna", language="en-US"))

    response.add(plivoxml.HangupElement())
    return plivo_response(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App started on port {port}")
    app.run(host="0.0.0.0", port=port)