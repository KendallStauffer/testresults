from flask import Flask, request, Response
import os

app = Flask(__name__)

# ====================== WORD TO DIGIT CONVERTER ======================
def speech_to_digits(text):
    if not text:
        return ""
    
    word_map = {
        "zero": "0", "oh": "0", "o": "0",
        "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"
    }
    
    # Split and convert each word
    cleaned = ""
    for word in text.lower().split():
        word = word.strip(".,!?")
        cleaned += word_map.get(word, word)
    
    # Remove any remaining non-digits (just in case)
    cleaned = "".join(c for c in cleaned if c.isdigit())
    return cleaned


# ====================== START CALL (TeXML) ======================
@app.route('/start', methods=['GET', 'POST'])
def start_call():
    print("=== /start HIT by Telnyx ===")
    print("Method:", request.method)
    
    texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather 
        action="/gather-handler"
        method="POST"
        input="speech"
        numDigits="6"
        timeout="15"
        speechTimeout="auto"
        hints="0 1 2 3 4 5 6 7 8 9 zero one two three four five six seven eight nine oh"
        language="en-US"
        transcriptionEngine="Deepgram"
        profanityFilter="false">
        
        <Say voice="female" language="en-US">
            Please say your 6 digit code, speaking each digit clearly and separately. 
            For example: one two three four five six.
        </Say>
    </Gather>

    <!-- Fallback -->
    <Say>Sorry, I didn't catch your 6 digit code. Let's try again.</Say>
    <Redirect>/start</Redirect>
</Response>'''

    return Response(texml, mimetype='text/xml', status=200)


# ====================== GATHER HANDLER (FIXED PIN INPUT) ======================
@app.route('/gather-handler', methods=['POST'])
def gather_handler():
    print("=== /gather-handler HIT ===")
    print("Full form data:", dict(request.form))
    
    speech_result = request.form.get('SpeechResult', '').strip()
    digits_raw = request.form.get('Digits', '').strip()
    call_sid = request.form.get('CallSid')
    
    print(f"Raw SpeechResult: {speech_result}")
    print(f"Raw Digits: {digits_raw}")
    
    # FIXED: Convert spoken words to actual digits
    code = speech_to_digits(speech_result)
    
    # Also accept direct digits if user presses keypad
    if not code and digits_raw and len(digits_raw) == 6:
        code = digits_raw
    
    if len(code) == 6:
        print(f"✅ SUCCESS! 6-digit code received: {code}")
        
        texml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="female">Thank you. Your code {code} was received.</Say>
    <Hangup/>
</Response>'''
    else:
        print(f"❌ Invalid code (got '{code}' from '{speech_result}')")
        texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Sorry, I couldn't understand the 6 digit code.</Say>
    <Redirect>/start</Redirect>
</Response>'''

    return Response(texml, mimetype='text/xml', status=200)


# ====================== HEALTH CHECK ======================
@app.route('/health', methods=['GET'])
def health():
    return {"status": "ok"}, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)