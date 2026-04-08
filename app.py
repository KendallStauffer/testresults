from flask import Flask, request, Response
import plivo
from plivo import plivoxml
import logging
import os

app = Flask(__name__)

# ====================== CONFIG ======================
BASE_URL = "https://YOUR-APP-NAME.onrender.com"   # ← CHANGE THIS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def plivo_response(resp):
    return Response(resp.to_string(), mimetype="application/xml")

# ====================== VOICE ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    logger.info("INCOMING_CALL - /voice called")
    response = plivoxml.ResponseElement()

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/gather_pin",
        method="GET",
        input_type="dtmf",
        num_digits=6,
        digit_end_timeout=10,
        finish_on_key="#"
    )

    get_input.add(plivoxml.SpeakElement(
        "Hello. Please enter any 6 digits on your keypad then press pound.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)
    response.add(plivoxml.SpeakElement("No input. Goodbye.", voice="Polly.Joanna", language="en-US"))

    return plivo_response(response)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    logger.info(f"GATHER_PIN called | Digits received: '{digits}'")

    response = plivoxml.ResponseElement()

    if len(digits) == 6:
        response.add(plivoxml.SpeakElement(f"Thank you. You entered {digits}.", voice="Polly.Joanna", language="en-US"))
    else:
        response.add(plivoxml.SpeakElement("Sorry, no 6 digits received.", voice="Polly.Joanna", language="en-US"))

    response.add(plivoxml.HangupElement())
    return plivo_response(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App starting on port {port}")
    app.run(host="0.0.0.0", port=port)