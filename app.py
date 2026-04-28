from flask import Flask, request, Response
import os

app = Flask(__name__)

# ==================== MAIN ENTRY POINT ====================
@app.route('/start', methods=['GET', 'POST'])
def start_call():
    """This is the initial webhook URL you set in your Telnyx TeXML Application"""
    texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather 
        action="/gather-handler"
        method="POST"
        input="speech"
        numDigits="6"
        timeout="15"
        speechTimeout="auto"
        hints="0,1,2,3,4,5,6,7,8,9,zero,one,two,three,four,five,six,seven,eight,nine,oh"
        language="en-US"
        transcriptionEngine="Deepgram"
        profanityFilter="false">
        
        <Say voice="female" language="en-US">
            Please say your 6 digit code, speaking each digit clearly and separately. 
            For example: one two three four five six.
        </Say>
    </Gather>

    <!-- Fallback if no input or not understood -->
    <Say>Sorry, I didn't catch your 6 digit code. Let's try again.</Say>
    <Redirect>/start</Redirect>
</Response>'''

    return Response(texml, mimetype='text/xml')


# ==================== GATHER HANDLER ====================
@app.route('/gather-handler', methods=['POST'])
def gather_handler():
    """Telnyx posts here after the user speaks"""
    
    # Debug - see exactly what Telnyx sent
    print("=== GATHER CALLBACK RECEIVED ===")
    for key, value in request.form.items():
        print(f"{key}: {value}")
    
    speech_result = request.form.get('SpeechResult', '').strip()
    digits = request.form.get('Digits', '').strip()
    call_sid = request.form.get('CallSid')

    print(f"SpeechResult: {speech_result}")
    print(f"Digits: {digits}")

    # Clean the result (remove spaces, etc.)
    cleaned = speech_result.replace(" ", "").replace("-", "")

    if len(cleaned) == 6 and cleaned.isdigit():
        code = cleaned
        print(f"✅ SUCCESS! 6-digit code received: {code}")
        
        texml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="female">Thank you. Your code {code} was received.</Say>
    <!-- Add your next action here (e.g. <Hangup/>, another Gather, etc.) -->
    <Hangup/>
</Response>'''
        
    else:
        print("❌ Could not get valid 6 digits")
        texml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Sorry, I couldn't understand the 6 digit code.</Say>
    <Redirect>/start</Redirect>
</Response>'''

    return Response(texml, mimetype='text/xml')


# ==================== HEALTH CHECK (optional but useful) ====================
@app.route('/health', methods=['GET'])
def health():
    return {"status": "ok"}, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
