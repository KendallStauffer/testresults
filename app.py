from flask import Flask, request, Response, render_template_string, send_file
import pandas as pd
import os
import logging
import shutil
import re
from datetime import datetime

app = Flask(__name__)

# ... (keep all your original imports, helpers, load_data, etc.)

TTS_VOICE = os.environ.get("TTS_VOICE", "Telnyx.NaturalHD.astra")   # ← Change here or in Render env
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-US")

# ==================== MAIN VOICE ENDPOINT ====================
@app.route("/voice", methods=["GET", "POST"])
@app.route("/telnyx/voice", methods=["GET", "POST"])
def voice():
    xml = f'''<Response>
  <Gather action="{BASE_URL}/gather_pin" method="POST" input="dtmf speech" numDigits="6"
          timeout="2" speechTimeout="2" language="{TTS_LANGUAGE}"
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
          timeout="2" speechTimeout="2" language="{TTS_LANGUAGE}"
          hints="zero,oh,o,0,one,two,three,four,five,six,seven,eight,nine"
          transcriptionEngine="Deepgram">
    {say("I'm sorry, I didn't get that. Please say your six digit PIN one number at a time.")}
  </Gather>
</Response>'''


# Keep the rest of your app exactly as it was (gather_pin with confirmation, confirm_pin, handle_action, etc.)
# Just make sure all <Gather> tags have timeout="2" speechTimeout="2" and transcriptionEngine="Deepgram"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)