from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

active_pins = {}

print("Loading milk test results...")
try:
    df = pd.read_csv("test_results_long.csv")
    df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
    print(f"✅ Loaded {len(df)} records.")
except Exception as e:
    print(f"❌ Error loading CSV: {e}")
    df = pd.DataFrame()

def speak_pin_digits(pin: str):
    return " ".join(pin)

def twiml_response(resp: VoiceResponse):
    return Response(str(resp), mimetype="text/xml")

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    call_sid = request.values.get('CallSid')
    resp = VoiceResponse()

    if call_sid not in active_pins:
        resp.say("Thank you for calling the Milk Market Administrator Test Results Center.", 
                 voice="Polly.Joanna", language="en-US")
        # Initial pause removed as requested
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
    pin = ''.join(filter(str.isdigit, raw))

    if len(pin) < 6 and speech:
        word_to_digit = {
            "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
            "four": "4", "five": "5", "six": "6", "seven": "7",
            "eight": "8", "nine": "9"
        }
        spoken = speech.lower().split()
        extra = ''.join(word_to_digit.get(w, '') for w in spoken)
        if extra:
            pin = (pin + extra)[:6]

    print(f"Raw: '{raw}' → Cleaned PIN: '{pin}' (length: {len(pin)})")

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say("Let's try again. Please say or enter your 6 digit PIN.", 
                 voice="Polly.Joanna", language="en-US")
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
        return twiml_response(resp)

    active_pins[call_sid] = {"pin": pin}

    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")
    # No pause here (as previously requested)

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

    if not is_yes:
        resp.say("Okay, let's try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    pin = active_pins.get(call_sid, {}).get("pin")
    if not pin:
        resp.say("Sorry, something went wrong. Please start over.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

    resp.say("Finding your results.", voice="Polly.Joanna", language="en-US")

    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        resp.say("Sorry, no results were found for that PIN. Let's try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return twiml_response(resp)

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

        resp.pause(length=1)                    # Pause before each sample date
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

        resp.pause(length=1)                    # Pause after each full result

    # Final gather - no pause before it (as requested)
    gather = Gather(action="/handle_action", num_digits=1, timeout=10)
    gather.say("To repeat these results, say repeat or press 1. To end the call, say goodbye or press 2.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return twiml_response(resp)


@app.route("/handle_action", methods=['POST'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower()

    resp = VoiceResponse()

    if digits == "1" or "repeat" in speech:
        resp.say("Repeating the results.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.", voice="Polly.Joanna", language="en-US")
    return twiml_response(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)