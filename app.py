from flask import Flask, request, Response
import logging

app = Flask(__name__)

BASE_URL = "https://testresults-1aja.onrender.com"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def plivo_response(xml):
    return Response(xml, mimetype="text/xml")

def get_call_uuid():
    return request.values.get("CallUUID", "unknown")

def get_caller():
    return request.values.get("From", "unknown")

@app.route("/voice", methods=["GET", "POST"])
def voice():
    call_uuid = get_call_uuid()
    logger.info(f"INCOMING_CALL | CallUUID={call_uuid} | From={get_caller()}")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <GetInput action="{BASE_URL}/gather_pin"
            method="POST"
            inputType="dtmf speech"
            numDigits="6"
            digitEndTimeout="5"
            speechEndTimeout="3"
            speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine"
            language="en-US">
    <Speak voice="Polly.Joanna" language="en-US">
      Thank you for calling. Please say or enter your 6 digit PIN.
    </Speak>
  </GetInput>

  <Speak voice="Polly.Joanna" language="en-US">
    We did not receive any input. Goodbye.
  </Speak>
  <Hangup/>
</Response>"""

    logger.info(f"/voice XML returned:\n{xml}")
    return plivo_response(xml)

@app.route("/gather_pin", methods=["POST"])
def gather_pin():
    digits = request.values.get("Digits", "")
    speech = request.values.get("SpeechResult", "")

    logger.info(f"RAW INPUT digits='{digits}' speech='{speech}'")

    pin = digits if digits else speech
    pin = "".join([c for c in pin if c.isdigit()])

    logger.info(f"PARSED PIN: {pin}")

    if len(pin) != 6:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak voice="Polly.Joanna">
    Invalid PIN. Please try again.
  </Speak>
  <Redirect method="POST">{BASE_URL}/voice</Redirect>
</Response>"""
        return plivo_response(xml)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak voice="Polly.Joanna">
    You entered { ' '.join(pin) }. Goodbye.
  </Speak>
  <Hangup/>
</Response>"""

    return plivo_response(xml)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)