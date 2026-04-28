from flask import Flask, request, Response
import os
import logging

app = Flask(__name__)

BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")
TTS_VOICE = os.environ.get("TTS_VOICE", "AWS.Polly.Joanna")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def xml_response(xml):
    return Response(xml, mimetype="application/xml")


@app.route("/telnyx/voice", methods=["GET", "POST"])
@app.route("/voice", methods=["GET", "POST"])
def voice():
    logger.info("=== Call started ===")
    
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather 
    action="{BASE_URL}/gather_pin"
    method="POST"
    input="dtmf speech"
    timeout="10"
    speechTimeout="3"
    language="en-US"
    hints="zero, oh, o, one, two, three, four, five, six, seven, eight, nine, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9"
    transcriptionEngine="Telnyx">
    <Say voice="{TTS_VOICE}">Please say or enter your 6 digit pin.</Say>
  </Gather>
  <Say voice="{TTS_VOICE}">We didn't receive any input. Goodbye.</Say>
</Response>'''
    
    return xml_response(xml)


@app.route("/gather_pin", methods=["GET", "POST"])
def gather_pin():
    logger.info("=== Gather received ===")
    logger.info(f"Form data: {dict(request.form)}")
    
    speech = request.form.get("SpeechResult", "").strip()
    digits = request.form.get("Digits", "").strip()
    raw = digits if digits else speech
    pin = "".join(c for c in raw if c.isdigit())
    
    if len(pin) == 6:
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{TTS_VOICE}">Thank you. Your pin {pin} was received.</Say>
  <Hangup/>
</Response>'''
    else:
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{TTS_VOICE}">Sorry, I didn't get that. Please try again.</Say>
  <Redirect>{BASE_URL}/telnyx/voice</Redirect>
</Response>'''
    
    return xml_response(xml)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
