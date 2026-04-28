from flask import Flask, request, Response
import os
import traceback

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
    
    cleaned = ""
    for word in text.lower().split():
        word = word.strip(".,!?")
        cleaned += word_map.get(word, word)
    
    cleaned = "".join(c for c in cleaned if c.isdigit())
    return cleaned


# ====================== YOUR PATH: /telnyx/voice ======================
@app.route('/telnyx/voice', methods=['GET', 'POST'])
def start_call():
    try:
        print("=== /telnyx/voice HIT by Telnyx ===")
        print("Method:", request.method)
        
        texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather 
        action="/telnyx/voice/gather-handler"
        method="POST"
        input="speech"
        numDigits="6"
        timeout="8"
        speechTimeout="3"
        hints="0 1 2 3 4 5 6 7 8 9 zero one two three four five six seven eight nine oh"
        language="en-US"
        transcriptionEngine="Deepgram"
        profanityFilter="false">
        
        <Say voice="Telnyx.NaturalHD.astra" language="en-US">
            Please say your 6 digit code, speaking each digit clearly and separately. 
            For example: one two three four five six.
        </Say>
    </Gather>

    <Say voice="Telnyx.NaturalHD.astra" language="en-US">
        Sorry, I didn't catch your 6 digit code. Let's try again.
    </Say>
    <Redirect>/telnyx/voice</Redirect>
</Response>'''

        return Response(texml, mimetype='text/xml', status=200)
    
    except Exception as e:
        print("🚨 ERROR in /telnyx/voice:")
        print(traceback.format_exc())
        return Response('''<?xml version="1.0" encoding="UTF-8"?>
<Response><Say voice="Telnyx.NaturalHD.astra">An application error occurred.</Say><Hangup/></Response>''', 
                        mimetype='text/xml', status=500)


# ====================== GATHER HANDLER ======================
@app.route('/telnyx/voice/gather-handler', methods=['POST'])
def gather_handler():
    try:
        print("=== /telnyx/voice/gather-handler HIT ===")
        print("Full form data:", dict(request.form))
        
        speech_result = request.form.get('SpeechResult', '').strip()
        digits_raw = request.form.get('Digits', '').strip()
        
        print(f"Raw SpeechResult: {speech_result}")
        
        code = speech_to_digits(speech_result)
        if not code and digits_raw and len(digits_raw) == 6:
            code = digits_raw
        
        if len(code) == 6:
            print(f"✅ SUCCESS! Code: {code}")
            texml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Telnyx.NaturalHD.astra" language="en-US">Thank you. Your code {code} was received.</Say>
    <Hangup/>
</Response>'''
        else:
            print(f"❌ Invalid (got '{code}')")
            texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Telnyx.Natural.abbie" language="en-US">Sorry, I couldn't understand the 6 digit code.</Say>
    <Redirect>/telnyx/voice</Redirect>
</Response>'''

        return Response(texml, mimetype='text/xml', status=200)
    
    except Exception as e:
        print("🚨 ERROR in gather-handler:")
        print(traceback.format_exc())
        return Response('''<?xml version="1.0" encoding="UTF-8"?>
<Response><Say voice="Telnyx.NaturalHD.astra">An application error occurred.</Say><Hangup/></Response>''', 
                        mimetype='text/xml', status=500)


@app.route('/health', methods=['GET'])
def health():
    return {"status": "ok"}, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
