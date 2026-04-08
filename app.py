@app.route("/confirm_pin", methods=['GET'])
def confirm_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip().lower() or request.values.get('Speech', '').strip().lower()
    call_uuid = request.values.get('CallUUID')

    is_yes = digits == "1" or any(word in speech for word in ["yes", "yeah", "correct", "right", "yep"])

    response = plivoxml.ResponseElement()

    if not is_yes:
        response.add(plivoxml.SpeakElement("Okay, let's try again.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.RedirectElement(f"{BASE_URL}/gather_pin"))  # Changed: go back to gather_pin, not voice
        return plivo_response(response)

    pin = active_pins.get(call_uuid, {}).get("pin")
    if not pin:
        response.add(plivoxml.SpeakElement("Sorry, something went wrong. Please start over.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.RedirectElement(f"{BASE_URL}/voice"))
        return plivo_response(response)

    # ... keep the rest of your results reading code exactly as it is ...

    log_call("RESULTS_LOOKUP", {"pin": pin})
    results_df = df[df['Pin_Number'] == pin].sort_values('sequence_number')

    if results_df.empty:
        response.add(plivoxml.SpeakElement("Sorry, no results were found for that PIN. Let's try again.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.RedirectElement(f"{BASE_URL}/voice"))
        return plivo_response(response)

    response.add(plivoxml.SpeakElement("Here are your milk test results.", voice="Polly.Joanna", language="en-US"))

    for _, row in results_df.iterrows():
        day = int(row.get('day', 1))
        response.add(plivoxml.WaitElement(length=1))
        response.add(plivoxml.SpeakElement(f"Sample from the {day}th.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.SpeakElement(f"Butterfat {row.get('fat', 0)} percent.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.SpeakElement(f"Protein {row.get('protein', 0)} percent.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.SpeakElement(f"Somatic cell count {int(row.get('scc', 0)):,}.", voice="Polly.Joanna", language="en-US"))
        if int(row.get('mun', 0)) > 0:
            response.add(plivoxml.SpeakElement(f"Munn {int(row.get('mun', 0))}.", voice="Polly.Joanna", language="en-US"))
        response.add(plivoxml.WaitElement(length=1))

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/handle_action",
        method="GET",
        input_type="dtmf speech",
        num_digits=1,
        digit_end_timeout=10,
        speech_end_timeout=3,
        language="en-US"
    )
    get_input.add(plivoxml.SpeakElement(
        "To hear these results again, say repeat or press 1. To end the call, say goodbye or press 2.",
        voice="Polly.Joanna", language="en-US"
    ))
    response.add(get_input)

    return plivo_response(response)