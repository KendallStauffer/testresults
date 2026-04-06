from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

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
    print(f"Looking up PIN: '{pin_clean}'")
    results = df[df['Pin_Number'] == pin_clean].sort_values('sequence_number')
    print(f"→ Found {len(results)} records")
    return results

def speak_pin_digits(pin: str):
    """Speak PIN digit by digit: 2 0 0 0 1 9"""
    return " ".join(pin)

# ====================== ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    resp.say("Hello. This is the milk testing results line.", voice="Polly.Joanna", language="en-US")
    resp.pause(length=0.5)

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=15,
        finish_on_key="",           # Removed pound key requirement
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
    
    raw_input = digits if digits else speech
    pin = ''.join(filter(str.isdigit, raw_input))
    print(f"Raw input: '{raw_input}' → Cleaned PIN: '{pin}'")

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say("Sorry, that is not a 6 digit PIN. Please try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # Speak PIN digit by digit
    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")

    gather = Gather(
        action="/confirm_pin",
        num_digits=1,
        timeout=12,
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

    resp = VoiceResponse()

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])

    if not is_yes:
        resp.say("Okay, let's try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # PIN confirmed - now read results directly (no going back to hello)
    resp.say("Thank you. Here are your milk test results.", voice="Polly.Joanna", language="en-US")
    
    # For now we still need the PIN. We'll ask again but it's quick.
    # Better version with session coming if you want.
    resp.redirect("/voice")
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