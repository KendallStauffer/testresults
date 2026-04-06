from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

# ====================== LOAD DATA ======================
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

# ====================== ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    
    # Use better voice + language
    resp.say("Hello. This is the milk testing results line.", voice="Polly.Joanna", language="en-US")
    resp.pause(length=0.6)

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=12,
        finish_on_key="#"
    )
    gather.say("Please type your 6 digit PIN using your keypad, then press the pound key.", 
               voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    resp.say("We didn't receive any input. Goodbye.", voice="Polly.Joanna", language="en-US")
    return str(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    raw_digits = request.values.get('Digits', '').strip()
    print(f"Raw input received: '{raw_digits}'")

    pin = ''.join(filter(str.isdigit, raw_digits))
    print(f"Cleaned PIN: '{pin}'")

    resp = VoiceResponse()

    if len(pin) != 6:
        resp.say("Invalid PIN. Please try again.", voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    results_df = get_results_for_pin(pin)

    if results_df.empty:
        resp.say(f"Sorry, no results found for PIN {pin}. Please try again.", 
                 voice="Polly.Joanna", language="en-US")
        resp.redirect("/voice")
        return str(resp)

    # Speak results with better voice
    resp.say(f"Thank you. Here are your milk test results for PIN {pin}, starting with the most recent.", 
             voice="Polly.Joanna", language="en-US")

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
        resp.say(f"Sample from {month_name} {day}, {year}.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Butterfat {row['fat']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Protein {row['protein']} percent.", voice="Polly.Joanna", language="en-US")
        resp.say(f"Somatic cell count {int(row['scc']):,}.", voice="Polly.Joanna", language="en-US")
        
        if int(row.get('mun', 0)) > 0:
            resp.say(f"Munn {int(row['mun'])}.", voice="Polly.Joanna", language="en-US")

        resp.pause(length=0.7)

    gather = Gather(action="/handle_action", num_digits=1, timeout=12)
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