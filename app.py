from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import pandas as pd
import os

app = Flask(__name__)

# ====================== LOAD DATA ======================
print("Loading milk test results...")
try:
    df = pd.read_csv("test_results_long.csv")
    # Clean Pin_Number properly
    df['Pin_Number'] = df['Pin_Number'].astype(str).str.strip().str.zfill(6)
    print(f"✅ Loaded {len(df)} records. Sample PINs: {df['Pin_Number'].head(3).tolist()}")
except Exception as e:
    print(f"❌ Error loading CSV: {e}")
    df = pd.DataFrame()

def get_results_for_pin(pin: str):
    pin = str(pin).strip().zfill(6)
    results = df[df['Pin_Number'] == pin].sort_values('sequence_number')
    print(f"Lookup for PIN {pin} → Found {len(results)} records")   # Debug line
    return results

# ====================== ROUTES ======================

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    resp.say("Hello, this is the milk testing results line.")
    resp.pause(length=0.5)

    gather = Gather(action="/gather_pin", num_digits=6, timeout=10, finish_on_key="#")
    gather.say("Please enter your 6-digit PIN using your keypad, then press the pound key.")
    resp.append(gather)

    resp.say("We didn't receive any input. Goodbye.")
    return str(resp)


@app.route("/gather_pin", methods=['POST'])
def gather_pin():
    pin = request.values.get('Digits', '').strip()
    print(f"Received PIN from Twilio: '{pin}'")   # This will show in Render logs

    resp = VoiceResponse()

    if len(pin) != 6 or not pin.isdigit():
        resp.say("Invalid PIN format. Please try again.")
        resp.redirect("/voice")
        return str(resp)

    results_df = get_results_for_pin(pin)

    if results_df.empty:
        resp.say(f"I'm sorry, no results found for PIN {pin}. Please check the number and try again.")
        resp.redirect("/voice")
        return str(resp)

    # Speak the results
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

    # Repeat or end
    gather = Gather(action="/handle_action", num_digits=1, timeout=12)
    gather.say("To repeat these results, press 1. To end the call, press 2.")
    resp.append(gather)

    return str(resp)


@app.route("/handle_action", methods=['POST'])
def handle_action():
    digits = request.values.get('Digits', '').strip()
    resp = VoiceResponse()

    if digits == "1":
        resp.say("Repeating the results.")
        resp.redirect("/voice")
    else:
        resp.say("Thank you for calling. Goodbye.")
    return str(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)