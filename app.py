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
    return " ".join(pin)

# ====================== MAIN FLOW ======================

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
        speech_timeout="auto",
        language="en-US",
        speech_model="default"          # Try to improve recognition
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
    print(f"Raw: '{raw_input}' → Cleaned PIN: '{pin}'")

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say(f"You entered {pin}. That is not 6 digits. Please try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # Confirmation
    spoken_pin = speak_pin_digits(pin)
    resp.say(f"Am I right with {spoken_pin}?", voice="Polly.Joanna", language="en-US")

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

    resp = VoiceResponse()

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])

    if not is_yes:
        resp.say("Okay, let's try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # === FIXED: Read results immediately after "yes" ===
    resp.say("Thank you. Here are your milk test results.", voice="Polly.Joanna", language="en-US")

    # We still need the PIN. For now we ask once more (fast). 
    # Better session version available if you want.
    resp.redirect("/read_results")
    return str(resp)


@app.route("/read_results", methods=['GET', 'POST'])
def read_results():
    resp = VoiceResponse()
    
    # Ask for PIN one last time (this is the 2nd ask - we'll reduce it later)
    gather = Gather(
        action="/final_read",
        num_digits=6,
        timeout=10,
        finish_on_key="",
        input="dtmf speech",
        speech_timeout="auto"
    )
    gather.say("Please enter or say your 6 digit PIN one more time to hear the results.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)
    return str(resp)


@app.route("/final_read", methods=['POST'])
def final_read():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    pin = ''.join(filter(str.isdigit, digits if digits else speech))

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say("Invalid PIN. Goodbye.", voice="Polly.Joanna", language="en-US")
        return str(resp)

    results_df = get_results_for_pin(pin)

    if results_df.empty:
        resp.say("Sorry, no results found for that PIN. Goodbye.", voice="Polly.Joanna", language="en-US")
        return str(resp)

    # === ACTUAL RESULTS READING ===
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