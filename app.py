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
DEEPGRAM_ENDPOINTING_MS=100
TTS_GAIN=1.6
LISTEN_RESUME_DELAY_MS=0

Recommended Render start command
--------------------------------
python app.py

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
This app speaks the first prompt with TwiML <Say>. Follow-up prompts are
converted to 8 kHz mu-law audio with Deepgram TTS and sent back to Twilio as
outbound websocket media frames.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

import websockets
from dotenv import load_dotenv
from flask import Flask, Response, request
from flask_sock import Sock
try:
    from simple_websocket.errors import ConnectionClosed
except Exception:  # pragma: no cover
    ConnectionClosed = Exception

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
            await self.say("I didn't get that. Let's try again.")
            await self.prompt_for_pin()
            return

        self.candidate_pin = pin
        self.dtmf_buffer = ""
        self.step = Step.CONFIRM_PIN
        await self.say(f"Am I right with PIN {self.spoken_pin(pin)}? Press 1 or say yes, or no or press 2.")

    async def confirm_no(self) -> None:
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        await self.say("Let's try again.")
        await self.prompt_for_pin()

    async def confirm_yes(self) -> None:
        pin = self.candidate_pin
        self.candidate_pin = ""
        self.dtmf_buffer = ""
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


def get_ws_url(path: str = "/media") -> str:
    base_url = get_base_url()
    return base_url.replace("https://", "wss://").replace("http://", "ws://") + path


@app.get("/health")
def health():
    return {"ok": True, "time": int(time.time())}


@app.route("/voice", methods=["GET", "POST"])
def voice():
    """
    Twilio Voice webhook. Your Twilio number should point here:
    https://testresults-1aja.onrender.com/voice
    """
    ws_url = get_ws_url("/media")

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


@app.route("/telnyx/voice", methods=["GET", "POST"])
def telnyx_voice():
    """
    Telnyx TeXML webhook.

    Point a Telnyx TeXML application here if you want the same app to accept
    Telnyx calls. Experimental. Twilio is the known-good path; Telnyx may need provider-specific stream setup.
    """
    ws_url = get_ws_url("/media")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Please enter or say your 6 digit PIN.</Say>
  <Connect>
    <Stream url="{ws_url}" track="inbound_track" codec="PCMU" />
  </Connect>
</Response>"""
    return Response(xml, mimetype="application/xml")


@app.route("/telnyx/call-control", methods=["POST"])
def telnyx_call_control():
    """
    Placeholder for Telnyx Call Control webhooks.

    For Call Control, Telnyx sends HTTP events here. To actually answer calls
    and start media streaming, add TELNYX_API_KEY and call Telnyx's answer/start
    streaming APIs using the call_control_id from the webhook.
    """
    event = request.get_json(silent=True) or {}
    print(f"TELNYX CALL CONTROL EVENT: {event}", flush=True)
    return {"ok": True}


def mulaw_byte_to_linear(byte: int) -> int:
    """
    Decode one 8-bit mu-law byte to signed 16-bit PCM.

    Pure Python implementation because Python 3.14 no longer includes audioop.
    """
    byte = (~byte) & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


def linear_to_mulaw_byte(sample: int) -> int:
    """
    Encode one signed 16-bit PCM sample to 8-bit mu-law.
    """
    sample = max(-32635, min(32635, int(sample)))
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample += 0x84

    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        mask >>= 1
        exponent -= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def apply_mulaw_gain(audio: bytes, gain: float) -> bytes:
    """
    Increase/decrease raw mu-law volume.

    TTS_GAIN=1.0 means unchanged.
    TTS_GAIN=1.4 to 1.8 is usually a reasonable phone-call boost.
    Too high can distort/clamp.
    """
    if abs(gain - 1.0) < 0.001:
        return audio

    out = bytearray(len(audio))
    for i, byte in enumerate(audio):
        sample = mulaw_byte_to_linear(byte)
        out[i] = linear_to_mulaw_byte(sample * gain)
    return bytes(out)


def deepgram_tts_mulaw_8k(text: str) -> bytes:
    """
    Generate raw 8 kHz mu-law audio with Deepgram TTS.

    Twilio Media Streams expects outbound audio payloads as base64-encoded
    audio/x-mulaw at 8000 Hz, with no WAV/header bytes.
    """
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPGRAM_API_KEY")

    model = os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-luna-en")
    url = (
        f"https://api.deepgram.com/v1/speak"
        f"?model={model}"
        f"&encoding=mulaw"
        f"&sample_rate=8000"
        f"&container=none"
    )

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mulaw",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            audio = resp.read()
            gain = float(os.getenv("TTS_GAIN", "1.6"))
            return apply_mulaw_gain(audio, gain)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Deepgram TTS failed: HTTP {exc.code}: {err}") from exc


async def say_to_call(text: str, ws=None, stream_sid: Optional[str] = None, stream_id: Optional[str] = None) -> None:
    """
    Speak dynamic prompts back into the active Twilio bidirectional Media Stream.

    Twilio expects outbound media as base64-encoded raw mu-law/8000 audio.
    To keep playback reliable, send small 20 ms frames instead of one huge blob.
    """
    print(f"APP: {text}", flush=True)

    active_stream_id = stream_sid or stream_id

    if ws is None or not active_stream_id:
        print("APP: no active stream id yet; prompt logged only", flush=True)
        return

    try:
        audio = await asyncio.to_thread(deepgram_tts_mulaw_8k, text)

        # 8 kHz mu-law = 8000 bytes/sec. 20 ms = 160 bytes.
        # Sending 20 ms frames matches telephony packet pacing and is much more
        # reliable than pushing the whole TTS file as one websocket message.
        frame_size = int(os.getenv("TTS_FRAME_BYTES", "160"))
        sleep_seconds = frame_size / 8000.0

        total_frames = 0
        for i in range(0, len(audio), frame_size):
            chunk = audio[i:i + frame_size]
            if not chunk:
                continue

            payload = base64.b64encode(chunk).decode("ascii")
            ws.send(json.dumps({
                "event": "media",
                "streamSid": active_stream_id,
                "media": {"payload": payload},
            }))
            total_frames += 1

            # Pace the audio so Twilio can play it smoothly.
            await asyncio.sleep(sleep_seconds)

        mark_name = f"prompt-{int(time.time() * 1000)}"
        ws.send(json.dumps({
            "event": "mark",
            "streamSid": active_stream_id,
            "mark": {"name": mark_name},
        }))

        print(
            f"APP: sent TTS to call: {len(audio)} bytes, {total_frames} frames, mark={mark_name}",
            flush=True,
        )

    except Exception as exc:
        print(f"APP: failed to speak prompt to call: {exc}", flush=True)



async def media_stream_async(ws) -> None:
    stream_id: Optional[str] = None

    # Avoid self-hearing and stale recognition: while we are playing TTS back
    # into the call, ignore Deepgram transcripts until shortly after playback.
    listen_resume_at = 0.0
    resume_delay_ms = int(os.getenv("LISTEN_RESUME_DELAY_MS", "0"))

    async def say(text: str) -> None:
        nonlocal listen_resume_at
        listen_resume_at = time.monotonic() + 3600.0
        await say_to_call(text, ws=ws, stream_sid=stream_id)
        listen_resume_at = time.monotonic() + (resume_delay_ms / 1000.0)

    flow = PinFlow(say=say)
    # /voice already plays the first prompt with Twilio <Say>.
    # Keep the state ready without sending another prompt over the stream.
    flow.step = Step.ASK_PIN
    flow.candidate_pin = ""
    flow.dtmf_buffer = ""

    dg_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not dg_api_key:
        await say("Missing DEEPGRAM_API_KEY on the server.")
        return

    endpointing_ms = int(os.getenv("DEEPGRAM_ENDPOINTING_MS", "175"))

    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-3"
        "&language=en-US"
        "&encoding=mulaw"
        "&sample_rate=8000"
        "&channels=1"
        "&interim_results=false"
        f"&smart_format={smart_format}"
        f"&endpointing={endpointing_ms}"
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
                    now = time.monotonic()
                    if now < listen_resume_at:
                        print(f"DEEPGRAM IGNORED DURING TTS: {transcript}", flush=True)
                        continue

                    print(f"DEEPGRAM: {transcript}", flush=True)
                    await flow.handle_transcript(transcript)

        dg_task = asyncio.create_task(receive_deepgram())

        try:
            while True:
                # Flask-Sock/simple-websocket is synchronous. Calling ws.receive()
                # directly inside async code blocks the event loop and can cause
                # Gunicorn to kill the worker. Run it in a thread and use a short
                # timeout so Deepgram receive tasks keep moving.
                try:
                    raw_msg = await asyncio.to_thread(ws.receive, 1)
                except ConnectionClosed:
                    print("MEDIA: websocket closed", flush=True)
                    break
                except Exception as exc:
                    print(f"MEDIA: websocket receive error: {exc}", flush=True)
                    break

                # None means timeout/no message yet. Keep polling.
                if raw_msg is None:
                    continue

                try:
                    event = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event")

                if event_type == "connected":
                    print("MEDIA: connected", flush=True)

                elif event_type == "start":
                    start_data = event.get("start", {}) or {}
                    # Twilio uses streamSid. Telnyx commonly uses stream_id.
                    stream_id = (
                        event.get("streamSid")
                        or event.get("stream_id")
                        or start_data.get("streamSid")
                        or start_data.get("stream_id")
                    )
                    print(f"MEDIA: stream started {stream_id}", flush=True)

                elif event_type == "media":
                    payload = event.get("media", {}).get("payload")
                    if payload:
                        await dg_ws.send(base64.b64decode(payload))

                elif event_type == "dtmf":
                    digit = event.get("dtmf", {}).get("digit")
                    if digit:
                        print(f"MEDIA DTMF: {digit}", flush=True)
                        await flow.handle_dtmf(digit)

                elif event_type == "mark":
                    print(f"MEDIA MARK: {event.get('mark')}", flush=True)

                elif event_type == "stop":
                    print("MEDIA: stream stopped", flush=True)
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

    # Render injects PORT automatically. This is the "port connect" built into
    # the app so the Render start command can stay: python app.py
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Flask app on 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
