from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os
import logging

app = Flask(__name__)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

active_pins = {}

logger.info("🚀 Starting Milk Test Results Voice App...")

# Load CSV
print("Loading milk test results...")
try:
    df = pd.read_csv("test_results_long.csv")
    df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
    logger.info(f"✅ Successfully loaded {len(df)} records.")
except Exception as e:
    logger.error(f"❌ Failed to load CSV: {e}")
    df = pd.DataFrame()

def speak_pin_digits(pin: str):
    return " ".join(pin)

def twiml_response(resp: VoiceResponse):
    return Response(str(resp), mimetype="text/xml")

def log_call(event: str, extra: dict = None):
    if extra is None:
        extra = {}
    call_sid = request.values.get('CallSid', 'unknown')
    from_number = request.values.get('From', 'unknown')
    details = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info(f"{event} | CallSid={call_sid} | From={from_number} {details}")

# ====================== VOICE ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    log_call("INCOMING_CALL")
    call_sid = request.values.get('CallSid')
    resp = VoiceResponse()

    if call_sid not in active_pins:
        resp.say("Thank you for calling the Milk Market Administrator Test Results Center.", 
                 voice="Polly.Joanna", language="en-US")
        active_pins[call_sid] = {"pin": None}

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=15,
        finish_on_key="#",
        input="dtmf speech",
        speech_timeout=4,
        language="en-US",
        speech_model="phone_call",
        barge_in="true"
    )
    gather.say("Please say or enter your 6 digit PIN.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    resp.say("We didn't receive any input. Goodbye.", voice="Polly.Joanna", language="en-US")
    return twiml_response(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    call_sid = request.values.get('CallSid')

    raw = digits if digits else speech
    print(f"Raw input received: '{raw}'")

    # Improved cleaning to handle speech artifacts like "200000.  81."
    pin = ''.join(filter(str.isdigit, raw))

    # Extra cleanup for common speech recognition issues
    if len(pin) != 6 and speech:
        cleaned_speech = speech.replace("point", "").replace(".", "").replace(",", "").replace(" ", "")
        pin = ''.join(filter(str.isdigit, cleaned_speech))

    # Safety: if more than 6 digits were heard, take only the first 6
    if len(pin) > 6:
        pin = pin[:6]

    log_call("PIN_ATTEMPT", {"raw": raw, "cleaned": pin, "length": len(pin)})

    resp = VoiceResponse()

    if len(pin) != 6:
        log_call("PIN_INVALID", {"reason": f"length={len(pin)}"})
        resp.say("Let's try again. Please say or enter your 6 digit PIN.", 
                 voice="Polly.Joanna", language="en-US")
        gather = Gather(
            action="/gather_pin",
            num_digits=6,
            timeout=15,
            finish_on_key="#",
            input="dtmf speech",
            speech_timeout=5,
            language="en-US",
            speech_model="phone_call",
            barge_in="true"
        )
        gather.say("Please say or enter your 6 digit PIN.", 
                   voice="Polly.Joanna", language="en-US")
        resp.append(gather)
        return twiml_response(resp)

    # PIN is valid - proceed
    active_pins[call_sid] = {"pin": pin}
    log_call("PIN_ACCEPTED", {"pin": pin})

    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")

    gather = Gather(
        action="/confirm_pin",
        num_digits=1,
        timeout=10,
        input="dtmf speech",
        speech_timeout="auto",
        language="en-US",
        barge_in="true"
    )
    gather.say("Say yes or press 1 for yes. Say no or press 2 for no.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return twiml_response(resp)


@app.route("/confirm_pin", methods=['POST'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower()
    call_sid = request.values.get('CallSid')

    resp = VoiceResponse()

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])
    log_call("CONFIRMATION", {"input": speech or digits, "is_yes": is_yes})

    if not is_yes:
        resp.say("Okay, let's try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    pin = active_pins.get(call_sid, {}).get("pin")
    if not pin:
        log_call("ERROR_PIN_LOST")
        resp.say("Sorry, something went wrong. Please start over.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    log_call("RESULTS_LOOKUP", {"pin": pin})
    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        log_call("NO_RESULTS_FOUND", {"pin": pin})
        resp.say("Sorry, no results were found for that PIN. Let's try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    log_call("RESULTS_DELIVERED", {"count": len(results_df)})
    resp.say("Here are your milk test results.", voice="Polly.Joanna", language="en-US")

    is_first = True
    for _, row in results_df.iterrows():
        try:
            date_str = str(row['latest_test_date'])
            year = int(date_str[:4])
            month_num = int(date_str[5:7])
            day = int(row['day'])
            month_name = pd.to_datetime(f"{year}-{month_num:02d}-01").strftime('%B')
        except:
            month_name = "the month"
            day = int(row['day'])
            year = 2023

        resp.pause(length=1)
        if is_first:
            resp.say(f"First sample dated {month_name} {day}, {year}.", voice="Polly.Joanna", language="en-US")
            is_first = False
        else:
            resp.say(f"Next sample dated {month_name} {day}.", voice="Polly.Joanna", language="en-US")

        resp.say(f"Butterfat {row['fat']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Protein {row['protein']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Somatic cell count {int(row['scc']):,}.", voice="Polly.Joanna", language="en-US")
        
        if int(row.get('mun', 0)) > 0:
            resp.say(f"Munn {int(row['mun'])}.", voice="Polly.Joanna", language="en-US")

        resp.pause(length=1)

    gather = Gather(action="/handle_action", num_digits=1, timeout=10)
    gather.say("To repeat these results, say repeat or press 1. To end the call, say goodbye or press 2.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return twiml_response(resp)


@app.route("/handle_action", methods=['POST'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower()
    log_call("FINAL_ACTION", {"choice": speech or digits})

    resp = VoiceResponse()

    if digits == "1" or "repeat" in speech:
        resp.say("Repeating the results.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.", voice="Polly.Joanna", language="en-US")
    return twiml_response(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port)