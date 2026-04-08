@app.route("/gather_pin", methods=['GET'])
def gather_pin():
    digits = request.values.get('Digits', '').strip()
    speech = request.values.get('SpeechResult', '').strip()
    call_uuid = request.values.get('CallUUID', 'unknown')

    raw = digits if digits else speech
    logger.info(f"GATHER_PIN | Digits='{digits}' | Speech='{speech}'")

    # === STRONGER CLEANING FOR SPEECH ===
    pin = ''

    if digits:
        pin = ''.join(filter(str.isdigit, digits))
    else:
        # Speech cleaning
        text = speech.lower()
        
        # Replace common spoken numbers
        word_map = {
            "zero": "0", "oh": "0", "o": "0",
            "one": "1", "two": "2", "three": "3",
            "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9"
        }
        
        # Replace words with numbers
        for word, num in word_map.items():
            text = text.replace(word, num)
        
        # Remove everything except digits
        pin = ''.join(filter(str.isdigit, text))

    # Final fallback: take any 6 consecutive digits
    if len(pin) != 6:
        all_digits = ''.join(filter(str.isdigit, raw))
        if len(all_digits) >= 6:
            pin = all_digits[-6:]   # take last 6 digits

    log_call("PIN_ATTEMPT", {"raw": raw, "cleaned_pin": pin, "length": len(pin)})

    response = plivoxml.ResponseElement()

    if len(pin) != 6:
        logger.info("PIN length still invalid - asking again")
        get_input = plivoxml.GetInputElement(
            action=f"{BASE_URL}/gather_pin",
            method="GET",
            input_type="dtmf speech",
            num_digits=6,
            digit_end_timeout=8,
            speech_end_timeout=3,
            language="en-US"
        )
        get_input.add(plivoxml.SpeakElement(
            "Sorry, I didn't get 6 digits. Please say or enter your 6 digit PIN again.",
            voice="Polly.Joanna", language="en-US"
        ))
        response.add(get_input)
        return plivo_response(response)

    # Success!
    active_pins[call_uuid] = {"pin": pin}
    log_call("PIN_ACCEPTED", {"pin": pin})

    spoken = speak_pin_digits(pin)
    response.add(plivoxml.SpeakElement(f"You said {spoken}. Am I right?", voice="Polly.Joanna", language="en-US"))

    get_input = plivoxml.GetInputElement(
        action=f"{BASE_URL}/confirm_pin",
        method="GET",
        input_type="dtmf speech",
        num_digits=1,
        digit_end_timeout=10,
        speech_end_timeout=3,
        language="en-US"
    )
    get_input.add(plivoxml.SpeakElement(
        "Say yes or press 1 for yes. Say no or press 2 for no.",
        voice="Polly.Joanna", language="en-US"
    ))
    response.add(get_input)

    return plivo_response(response)