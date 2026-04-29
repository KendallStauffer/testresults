#!/usr/bin/env python3
"""
Flask + Gunicorn PIN capture test app for Render.

Flow
----
1) Twilio hits /voice.
2) /voice returns TwiML with <Connect><Stream url="wss://.../media" />.
3) /media receives Twilio websocket events:
   - media audio frames -> forwarded to Deepgram streaming STT
   - dtmf digits -> handled directly
4) App asks for a 6 digit PIN, validates it, confirms it, then loops.

Required Render env vars
------------------------
DEEPGRAM_API_KEY=your_deepgram_key
BASE_URL=https://testresults-1aja.onrender.com

Recommended Render start command
--------------------------------
gunicorn --threads 100 --timeout 0 app:app

Requirements
------------
flask
flask-sock
twilio
pandas
gunicorn
websockets
python-dotenv

Important
---------
This app logs dynamic prompts server-side. The first prompt is audible because it
is sent in TwiML <Say>. Follow-up prompts during the websocket stream require TTS
audio to be sent back to Twilio as outbound media frames. The PIN state machine,
DTMF ingestion, and Deepgram speech ingestion are implemented here.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

import websockets
from dotenv import load_dotenv
from flask import Flask, Response, request
from flask_sock import Sock

load_dotenv()

app = Flask(__name__)
sock = Sock(app)


DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "won": "1",
    "two": "2", "too": "2", "to": "2",
    "three": "3", "tree": "3",
    "four": "4", "for": "4", "fore": "4",
    "five": "5",
    "six": "6", "sicks": "6",
    "seven": "7",
    "eight": "8", "ate": "8",
    "nine": "9", "niner": "9",
}

YES_WORDS = {"yes", "yeah", "yep", "correct", "right", "confirm", "confirmed", "true", "1", "one"}
NO_WORDS = {"no", "nope", "wrong", "incorrect", "false", "2", "two"}


class Step(str, Enum):
    ASK_PIN = "ask_pin"
    CONFIRM_PIN = "confirm_pin"


def extract_digits(text: str) -> str:
    """Extract numeric digits from direct digits or spoken digit words."""
    text = text.lower().strip()

    literal = re.findall(r"\d", text)
    if literal:
        return "".join(literal)

    tokens = re.findall(r"[a-zA-Z]+", text)
    return "".join(DIGIT_WORDS[token] for token in tokens if token in DIGIT_WORDS)


def extract_yes_no(text: str) -> Optional[bool]:
    words = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
    if words & YES_WORDS:
        return True
    if words & NO_WORDS:
        return False
    return None


@dataclass
class PinFlow:
    say: Callable[[str], Awaitable[None]]
    delay_seconds: float = 1.25
    step: Step = Step.ASK_PIN
    candidate_pin: str = ""
    dtmf_buffer: str = field(default_factory=str)

    async def start(self) -> None:
        await self.prompt_for_pin()

    async def prompt_for_pin(self) -> None:
        self.step = Step.ASK_PIN
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        await self.say("Please enter or say your 6 digit PIN.")

    async def handle_dtmf(self, digit: str) -> None:
        digit = str(digit).strip()

        if self.step == Step.CONFIRM_PIN:
            if digit == "1":
                await self.confirm_yes()
            elif digit in {"2", "0", "*"}:
                await self.confirm_no()
            else:
                await self.say("Press 1 for yes, or 2 for no.")
            return

        if digit == "*":
            self.dtmf_buffer = ""
            await self.say("Cleared. Please enter your 6 digit PIN.")
            return

        if digit == "#":
            await self.submit_pin_text(self.dtmf_buffer)
            return

        if re.fullmatch(r"\d", digit):
            self.dtmf_buffer += digit
            print(f"DTMF buffer: {self.dtmf_buffer}", flush=True)
            if len(self.dtmf_buffer) >= 6:
                await self.submit_pin_text(self.dtmf_buffer[:6])

    async def handle_transcript(self, transcript: str) -> None:
        transcript = transcript.strip()
        if not transcript:
            return

        if self.step == Step.CONFIRM_PIN:
            yn = extract_yes_no(transcript)
            if yn is True:
                await self.confirm_yes()
            elif yn is False:
                await self.confirm_no()
            else:
                await self.say("Please say yes or no, or press 1 for yes and 2 for no.")
            return

        await self.submit_pin_text(transcript)

    async def submit_pin_text(self, text: str) -> None:
        pin = extract_digits(text)

        if not re.fullmatch(r"\d{6}", pin):
            await self.say("A PIN must be 6 numeric digits. Let's try again.")
            await self.prompt_for_pin()
            return

        self.candidate_pin = pin
        self.step = Step.CONFIRM_PIN
        await self.say(f"Am I right with {self.spoken_pin(pin)}? Say yes or press 1. Say no or press 2.")

    async def confirm_no(self) -> None:
        await self.say("Let's try again.")
        await self.prompt_for_pin()

    async def confirm_yes(self) -> None:
        pin = self.candidate_pin
        await self.say(f"Confirmed. The PIN is {self.spoken_pin(pin)}.")
        await asyncio.sleep(self.delay_seconds)
        await self.prompt_for_pin()

    @staticmethod
    def spoken_pin(pin: str) -> str:
        return " ".join(pin)


async def cli_say(text: str) -> None:
    print(f"\nAPP: {text}", flush=True)


async def run_cli() -> None:
    flow = PinFlow(say=cli_say)
    await flow.start()

    while True:
        user_input = input("YOU: ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break

        # Test DTMF by typing:
        #   dtmf 123456
        #   dtmf 1
        if user_input.lower().startswith("dtmf "):
            for d in user_input.split(maxsplit=1)[1]:
                await flow.handle_dtmf(d)
        else:
            await flow.handle_transcript(user_input)


def get_base_url() -> str:
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    if base_url:
        return base_url

    # Fallback for local testing only.
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if "onrender.com" in host else request.scheme
    return f"{scheme}://{host}"


@app.get("/health")
def health():
    return {"ok": True, "time": int(time.time())}


@app.route("/voice", methods=["GET", "POST"])
def voice():
    """
    Twilio Voice webhook. Your Twilio number should point here:
    https://testresults-1aja.onrender.com/voice
    """
    base_url = get_base_url()
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/media"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Please enter or say your 6 digit PIN.</Say>
  <Connect>
    <Stream url="{ws_url}" />
  </Connect>
</Response>"""
    return Response(xml, mimetype="application/xml")


@app.route("/twiml", methods=["GET", "POST"])
def twiml_alias():
    """Optional alias. /voice is the one you said your app uses."""
    return voice()


async def say_to_call(text: str, ws=None, stream_sid: Optional[str] = None) -> None:
    """
    Placeholder speech output.

    The initial prompt is spoken by Twilio <Say> in /voice. Dynamic prompts inside
    the stream are logged for now. Later, generate mu-law 8kHz TTS audio and send
    Twilio outbound websocket media messages here.
    """
    print(f"APP: {text}", flush=True)


async def media_stream_async(ws) -> None:
    stream_sid: Optional[str] = None

    async def say(text: str) -> None:
        await say_to_call(text, ws=ws, stream_sid=stream_sid)

    flow = PinFlow(say=say)
    await flow.start()

    dg_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not dg_api_key:
        await say("Missing DEEPGRAM_API_KEY on the server.")
        return

    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-3"
        "&language=en-US"
        "&encoding=mulaw"
        "&sample_rate=8000"
        "&channels=1"
        "&interim_results=false"
        "&smart_format=true"
        "&endpointing=300"
    )

    async with websockets.connect(
        dg_url,
        additional_headers={"Authorization": f"Token {dg_api_key}"},
        ping_interval=20,
        ping_timeout=20,
    ) as dg_ws:

        async def receive_deepgram():
            async for raw in dg_ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if data.get("type") != "Results":
                    continue

                channel = data.get("channel") or {}
                alternatives = channel.get("alternatives") or []
                if not alternatives:
                    continue

                transcript = (alternatives[0].get("transcript") or "").strip()
                is_final = data.get("is_final") or data.get("speech_final")

                if transcript and is_final:
                    print(f"DEEPGRAM: {transcript}", flush=True)
                    await flow.handle_transcript(transcript)

        dg_task = asyncio.create_task(receive_deepgram())

        try:
            while True:
                raw_msg = ws.receive()
                if raw_msg is None:
                    break

                try:
                    event = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event")

                if event_type == "connected":
                    print("TWILIO: connected", flush=True)

                elif event_type == "start":
                    stream_sid = event.get("streamSid") or event.get("start", {}).get("streamSid")
                    print(f"TWILIO: stream started {stream_sid}", flush=True)

                elif event_type == "media":
                    payload = event.get("media", {}).get("payload")
                    if payload:
                        await dg_ws.send(base64.b64decode(payload))

                elif event_type == "dtmf":
                    digit = event.get("dtmf", {}).get("digit")
                    if digit:
                        print(f"TWILIO DTMF: {digit}", flush=True)
                        await flow.handle_dtmf(digit)

                elif event_type == "stop":
                    print("TWILIO: stream stopped", flush=True)
                    break

        finally:
            dg_task.cancel()
            try:
                await dg_ws.close()
            except Exception:
                pass


@sock.route("/media")
def media(ws):
    """
    Twilio Media Streams websocket route.

    Flask-Sock websocket handlers are synchronous functions, so we run the async
    Deepgram/Twilio bridge inside an event loop for this connection.
    """
    asyncio.run(media_stream_async(ws))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run a terminal-only test loop.")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(run_cli())
        return

    # Local dev only. Render should run through gunicorn.
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
