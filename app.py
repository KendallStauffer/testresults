from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

# ====================== LOAD DATA ======================
# Load once when the app starts
print("Loading milk test results data...")
try:
    df = pd.read_csv("test_results_long.csv")
    df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
    print(f"Successfully loaded {len(df)} test records.")
except Exception as e:
    print(f"Error loading CSV: {e}")
    df = pd.DataFrame()  # empty dataframe as fallback

def get_results_for_pin(pin: str):
    """Return results for a PIN, sorted newest to oldest"""
    results = df[df['Pin_Number'] == pin].sort_values('sequence_number')
    return results

def speak_results(resp: VoiceResponse, results_df, pin: str):
    """Speak the test results naturally"""
    if results_df.empty:
        resp.say("I'm sorry, I could not find any test results for that PIN.")
        resp.redirect("/voice")
        return resp

    resp.say(f"Thank you. Here are your milk test results for PIN {pin}, starting with the most recent.")

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
        resp.say(f"Sample from {month_name} {day}, {year}.")
        resp.say(f"Butterfat {row['fat']} percent.")
        resp.say(f"Protein {row['protein']} percent.")
        resp.say(f"Somatic cell count {int(row['scc']):,}.")
        
        if int(row.get('mun', 0)) > 0:
            resp.say(f"Munn {int(row['mun'])}.")

        resp.pause(length=0.7)

    # Options to repeat or end
    gather = Gather(
        action="/handle_action",
        num_digits=1,
        timeout=15,
        finish_on_key="#"
    )
    gather.say("To repeat these results, press 1. To end the call, press 2 or say goodbye.")
    resp.append(gather)
    return resp


# ====================== ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    """Welcome and ask for PIN"""
    resp = VoiceResponse()
    resp.say("Hello, this is the milk testing results line.")
    resp.pause(length=0.5)

    gather = Gather(
        action="/gather_pin",
        num_digits=6,
        timeout=10,
        finish_on_key="#"
    )
    gather.say("Please enter your 6-digit PIN using your keypad, then press the pound key.")
    resp.append(gather)

    # Fallback
    resp.say("We didn't receive any input. Goodbye.")
    return str(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    """Process the PIN"""
    pin = request.values.get('Digits', '').strip()

    resp = VoiceResponse()

    if len(pin) != 6 or not pin.isdigit():
        resp.say("Invalid PIN. Please try again.")
        resp.redirect("/voice")
        return str(resp)

    results_df = get_results_for_pin(pin)
    speak_results(resp, results_df, pin)
    return str(resp)

@app.route("/handle_action", methods=['POST'])
def handle_action():
    """Handle repeat or goodbye"""
    digits = request.values.get('Digits', '').strip()

    resp = VoiceResponse()

    if digits == "1":
        resp.say("Repeating the results.")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.")

    return str(resp)


# For Render / Gunicorn
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)