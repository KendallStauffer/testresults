from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

# Simple in-memory session (works fine for low traffic)
sessions = {}

# Load data
print("Loading milk test results...")
try:
    df = pd.read_csv("test_results_long.csv")
    df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
    print(f"✅ Loaded {len(df)} records.")
except Exception as e:
    print(f"❌ Error loading CSV: {e}")
    df = pd.DataFrame()

def get_results_for_pin(pin: str):
    pin_clean = str(pin).strip().zfill(6)
    results = df[df['Pin_Number'] == pin_clean].sort_values('sequence_number')
    print(f"→ Found {len(results)} records for PIN {pin_clean}")
    return results

def speak_pin_digits(pin: str):
    return " ".join(pin)

# ====================== ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    resp.say("Thank you for calling the Milk Market Administrator Test Results Center.", 
             voice="Polly.Joanna", language="en-US")
    resp.pause(length=0.5)

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=15,
        finish_on_key="",
        input="dtmf speech",
        speech_timeout="auto"
    )
    gather.say("Please say or enter your 6 digit PIN.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    resp.say("We didn't receive any input. Goodbye.", voice="Polly.Joanna", language="en-US")
    return str(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    call_sid = request.values.get('CallSid')

    raw_input = digits if digits else speech
    pin = ''.join(filter(str.isdigit, raw_input))
    print(f"Raw: '{raw_input}' → Cleaned PIN: '{pin}'")

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say(f"You entered {pin}. That is not 6 digits. Please try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # Store PIN in session so we don't ask again
    sessions[call_sid] = pin

    # Short pause as you requested
    resp.pause(length=0.2)
    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")
    resp.pause(length=0.3)

    gather = Gather(
        action="/confirm_pin",
        num_digits=1,
        timeout=10,
        input="dtmf speech",
        speech_timeout="auto"
    )
    gather.say("Say yes or press 1 for yes. Say no or press 2 for no.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return str(resp)


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
        return str(resp)

    # Get the PIN we saved earlier
    pin = sessions.get(call_sid)
    if not pin:
        resp.say("Sorry, something went wrong. Please try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # === NOW READ RESULTS IMMEDIATELY ===
    resp.say("Thank you. Here are your milk test results.", voice="Polly.Joanna", language="en-US")

    results_df = get_results_for_pin(pin)

    if results_df.empty:
        resp.say("Sorry, no results found for that PIN.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # Read results
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

        resp.pause(length=0.5)
        if is_first:
            resp.say(f"First sample dated {month_name} {day}, {year}.", voice="Polly.Joanna", language="en-US")
            is_first = False
        else:
            resp.say(f"The next sample dated {month_name} {day}.", voice="Polly.Joanna", language="en-US")

        resp.say(f"Butterfat {row['fat']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Protein {row['protein']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Somatic cell count {int(row['scc']):,}.", voice="Polly.Joanna", language="en-US")
        
        if int(row.get('mun', 0)) > 0:
            resp.say(f"Munn {int(row['mun'])}.", voice="Polly.Joanna", language="en-US")

        resp.pause(length=0.7)

    # Final options
    gather = Gather(action="/handle_action", num_digits=1, timeout=10)
    gather.say("To repeat these results, press 1. To end the call, press 2.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    return str(resp)


@app.route("/handle_action", methods=['POST'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    resp = VoiceResponse()

    if digits == "1":
        resp.say("Repeating the results.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.", voice="Polly.Joanna", language="en-US")
    return str(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
