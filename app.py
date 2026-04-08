from flask import Flask, request, Response
import plivo
from plivo import plivoxml
import logging
import os

app = Flask(__name__)

BASE_URL = "https://testresults-1aja.onrender.com"

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def plivo_response(resp):
    return Response(resp.to_string(), mimetype="application/xml")

# Health check to help Render keep the app warm
@app.route("/health")
def health():
    return "OK", 200

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    logger.info("=== /voice called ===")
    response = plivoxml.ResponseElement()

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/gather_pin",
        method="GET",
        input_type="dtmf speech",
        num_digits=6,
        digit_end_timeout=10,
        finish_on_key="#"
    )

    get_input.add(plivoxml.SpeakElement(
        "Thank you for calling the Milk Market Administrator. Please say or enter your 6 digit PIN.",
        voice="Polly.Joanna", language="en-US"
    ))

    response.add(get_input)
    return plivo_response(response)


@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    logger.info(f"=== /gather_pin called | Digits='{digits}' | Speech='{speech}' ===")

    response = plivoxml.ResponseElement()

    if len(digits) == 6:
        response.add(plivoxml.SpeakElement(f"Thank you. You entered {digits}.", voice="Polly.Joanna", language="en-US"))
    elif speech:
        response.add(plivoxml.SpeakElement(f"You said {speech}.", voice="Polly.Joanna", language="en-US"))
    else:
        response.add(plivoxml.SpeakElement("No input received.", voice="Polly.Joanna", language="en-US"))

    response.add(plivoxml.HangupElement())
    return plivo_response(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App started on port {port}")
    app.run(host="0.0.0.0", port=port)