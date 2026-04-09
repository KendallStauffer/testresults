from flask import Flask, request, Response
import pandas as pd
import os
import re
import logging

app = Flask(__name__)

BASE_URL = "https://testresults-1aja.onrender.com"
CSV_PATH = "/mnt/data/test_results_long.csv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

df = pd.DataFrame()

# ================= LOAD DATA =================

def load_data():
    global df
    try:
        if os.path.exists(CSV_PATH):
            df = pd.read_csv(CSV_PATH, dtype=str)

            # normalize columns
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

            # clean pin_number ONLY (no padding, no guessing)
            if "pin_number" not in df.columns:
                df["pin_number"] = ""

            df["pin_number"] = (
                df["pin_number"]
                .astype(str)
                .str.strip()
                .str.replace(".0", "", regex=False)
                .str.replace(r"\D", "", regex=True)
            )

            logger.info(f"Loaded {len(df)} records")
            logger.info(f"Sample PINs: {df['pin_number'].head(10).tolist()}")
        else:
            logger.warning("CSV not found")

    except Exception as e:
        logger.error(f"CSV load failed: {e}")
        df = pd.DataFrame()

load_data()

# ================= HELPERS =================

def plivo_response(xml):
    return Response(xml, mimetype="text/xml")

NUMBER_WORDS = {
    "zero": "0","oh": "0","o": "0",
    "one": "1","won": "1",
    "two": "2","to": "2","too": "2",
    "three": "3",
    "four": "4","for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8","ate": "8",
    "nine": "9",
}

def extract_digits(text):
    if not text:
        return ""

    text = text.lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", text)

    result = []
    for t in tokens:
        if t.isdigit():
            result.extend(list(t))
        elif t in NUMBER_WORDS:
            result.append(NUMBER_WORDS[t])

    return "".join(result)

def speak_pin(pin):
    return " ".join(list(pin))

# ================= VOICE =================

@app.route("/voice", methods=["GET", "POST"])
def voice():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <GetInput action="{BASE_URL}/gather_pin"
            method="POST"
            inputType="dtmf speech"
            numDigits="6"
            speechModel="command_and_search"
            hints="zero,oh,o,one,two,three,four,five,six,seven,eight,nine"
            language="en-US">
    <Speak voice="Polly.Joanna">
      Thank you for calling the Milk Market Administrator Test Results Center.
      Please say or enter your six digit PIN.
    </Speak>
  </GetInput>

  <Speak voice="Polly.Joanna">
    We did not receive any input. Goodbye.
  </Speak>
  <Hangup/>
</Response>"""
    return plivo_response(xml)

# ================= GATHER PIN =================

@app.route("/gather_pin", methods=["POST"])
def gather_pin():
    digits = request.values.get("Digits", "")
    speech = request.values.get("SpeechResult", "")

    raw = digits if digits else speech

    logger.info(f"RAW INPUT: {raw}")

    pin = extract_digits(raw)
    logger.info(f"PARSED PIN: {pin}")

    if len(pin) != 6:
        return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna">
    Invalid PIN. Please try again.
  </Speak>
  <Redirect>{BASE_URL}/voice</Redirect>
</Response>""")

    spoken = speak_pin(pin)

    return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna">
    You said {spoken}. Am I right?
  </Speak>
  <GetInput action="{BASE_URL}/confirm_pin" method="POST" numDigits="1">
    <Speak voice="Polly.Joanna">
      Press 1 for yes or 2 for no.
    </Speak>
  </GetInput>
</Response>""")

# ================= CONFIRM =================

@app.route("/confirm_pin", methods=["POST"])
def confirm_pin():
    digits = request.values.get("Digits", "")

    if digits != "1":
        return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna">Okay, let's try again.</Speak>
  <Redirect>{BASE_URL}/voice</Redirect>
</Response>""")

    pin = request.values.get("SpeechResult", "") or request.values.get("Digits", "")
    pin = extract_digits(pin)

    logger.info(f"LOOKUP PIN: {pin}")

    if "pin_number" not in df.columns:
        return plivo_response("<Response><Speak>No data loaded.</Speak></Response>")

    results = df[df["pin_number"] == pin]

    if results.empty:
        return plivo_response(f"""<Response>
  <Speak voice="Polly.Joanna">
    No results found for that PIN.
  </Speak>
  <Redirect>{BASE_URL}/voice</Redirect>
</Response>""")

    xml = "<Response><Speak>Here are your milk test results.</Speak>"

    for _, row in results.iterrows():
        fat = row.get("fat", "")
        protein = row.get("protein", "")
        scc = row.get("scc", "")
        mun = row.get("mun", "")

        xml += f"""
  <Speak>
    Butterfat {fat} percent.
    Protein {protein} percent.
    Somatic cell count {scc}.
  </Speak>
"""

        if mun:
            xml += f"""
  <Speak>Munn {mun}.</Speak>
"""

    xml += "<Hangup/></Response>"

    return plivo_response(xml)

# ================= RUN =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)