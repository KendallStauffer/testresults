#!/usr/bin/env python3
"""
Twilio + Deepgram PIN capture test app for Render.

Routes
------
/voice   Twilio Voice webhook. Returns TwiML with bidirectional Media Stream.
/media   Twilio websocket route.
/health  Health check.

Render
------
Start command:
    gunicorn app:app

Keep gunicorn.conf.py in the repo root so Gunicorn uses gthread + Render PORT.

Requirements:
    flask
    flask-sock
    twilio
    pandas
    gunicorn
    websockets
    python-dotenv

Environment variables
---------------------
Required:
    DEEPGRAM_API_KEY=...
    BASE_URL=https://testresults-1aja.onrender.com

Recommended:
    DEEPGRAM_TTS_MODEL=aura-2-luna-en
    DEEPGRAM_ENDPOINTING_MS=100
    DEEPGRAM_INTERIM_RESULTS=true
    DEEPGRAM_SMART_FORMAT=false
    TTS_GAIN=1.0
    LISTEN_RESUME_DELAY_MS=0

Behavior
--------
- Prompts for a 6 digit PIN.
- Accepts spoken digits via Deepgram STT.
- Accepts Twilio DTMF digits.
- If not exactly 6 digits: "I didn't get that. Let's try again."
- If 6 digits: "Am I right with PIN ...? Press 1 or say yes, or no or press 2."
- If no/2: retry.
- If yes/1: reads value, delays, and re-prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
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
            self.candidate_pin = ""
            self.dtmf_buffer = ""
            await self.say("I didn't get that. Let's try again.")
            await self.prompt_for_pin()
            return

        self.candidate_pin = pin
        self.dtmf_buffer = ""
        self.step = Step.CONFIRM_PIN
        await self.say(
            f"Am I right with PIN {self.spoken_pin(pin)}? "
            "Press 1 or say yes, or no or press 2."
        )

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
    await flow.prompt_for_pin()

    while True:
        user_input = input("YOU: ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break

        if user_input.lower().startswith("dtmf "):
            for d in user_input.split(maxsplit=1)[1]:
                await flow.handle_dtmf(d)
        else:
            await flow.handle_transcript(user_input)


def get_base_url() -> str:
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    if base_url:
        return base_url

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
    Twilio Voice webhook:
    https://testresults-1aja.onrender.com/voice
    """
    ws_url = get_ws_url("/media")

    # No <Say> here. The first prompt is generated by Deepgram TTS after the
    # websocket start event, so every prompt uses the same voice.
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}" />
  </Connect>
</Response>"""
    return Response(xml, mimetype="application/xml")


@app.route("/twiml", methods=["GET", "POST"])
def twiml_alias():
    return voice()


def mulaw_byte_to_linear(byte: int) -> int:
    byte = (~byte) & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


def linear_to_mulaw_byte(sample: int) -> int:
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
    if abs(gain - 1.0) < 0.001:
        return audio

    out = bytearray(len(audio))
    for i, byte in enumerate(audio):
        sample = mulaw_byte_to_linear(byte)
        out[i] = linear_to_mulaw_byte(sample * gain)
    return bytes(out)


def deepgram_tts_mulaw_8k(text: str) -> bytes:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPGRAM_API_KEY")

    model = os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-luna-en")
    url = (
        "https://api.deepgram.com/v1/speak"
        f"?model={model}"
        "&encoding=mulaw"
        "&sample_rate=8000"
        "&container=none"
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
            gain = float(os.getenv("TTS_GAIN", "1.0"))
            return apply_mulaw_gain(audio, gain)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Deepgram TTS failed: HTTP {exc.code}: {err}") from exc


async def say_to_call(text: str, ws=None, stream_sid: Optional[str] = None) -> None:
    """
    Send Deepgram TTS back to Twilio as one raw mu-law media message.

    Single-send is the mode that was clear in your tests. Chunked mode caused
    static, so this clean Twilio version intentionally does not chunk playback.
    """
    print(f"APP: {text}", flush=True)

    if ws is None or not stream_sid:
        print("APP: no streamSid yet; prompt logged only", flush=True)
        return

    try:
        audio = await asyncio.to_thread(deepgram_tts_mulaw_8k, text)
        payload = base64.b64encode(audio).decode("ascii")

        ws.send(json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload},
        }))

        mark_name = f"prompt-{int(time.time() * 1000)}"
        ws.send(json.dumps({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": mark_name},
        }))

        print(
            f"APP: sent TTS to call: {len(audio)} bytes, single media message, mark={mark_name}",
            flush=True,
        )

    except Exception as exc:
        print(f"APP: failed to speak prompt to call: {exc}", flush=True)


async def media_stream_async(ws) -> None:
    stream_sid: Optional[str] = None
    listen_resume_at = 0.0
    resume_delay_ms = int(os.getenv("LISTEN_RESUME_DELAY_MS", "0"))

    async def say(text: str) -> None:
        nonlocal listen_resume_at
        listen_resume_at = time.monotonic() + 3600.0
        await say_to_call(text, ws=ws, stream_sid=stream_sid)
        listen_resume_at = time.monotonic() + (resume_delay_ms / 1000.0)

    flow = PinFlow(say=say)
    flow.step = Step.ASK_PIN
    flow.candidate_pin = ""
    flow.dtmf_buffer = ""

    dg_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not dg_api_key:
        await say("Missing DEEPGRAM_API_KEY on the server.")
        return

    endpointing_ms = int(os.getenv("DEEPGRAM_ENDPOINTING_MS", "100"))
    interim_results = os.getenv("DEEPGRAM_INTERIM_RESULTS", "true").strip().lower()
    smart_format = os.getenv("DEEPGRAM_SMART_FORMAT", "false").strip().lower()

    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-3"
        "&language=en-US"
        "&encoding=mulaw"
        "&sample_rate=8000"
        "&channels=1"
        f"&interim_results={interim_results}"
        f"&smart_format={smart_format}"
        f"&endpointing={endpointing_ms}"
    )

    print(
        f"DEEPGRAM STT SETTINGS: endpointing_ms={endpointing_ms}, "
        f"interim_results={interim_results}, smart_format={smart_format}",
        flush=True,
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
                is_final = bool(data.get("is_final"))
                speech_final = bool(data.get("speech_final"))

                if not transcript or not (speech_final or is_final):
                    continue

                now = time.monotonic()
                if now < listen_resume_at:
                    print(
                        f"DEEPGRAM IGNORED DURING TTS: {transcript} "
                        f"is_final={is_final} speech_final={speech_final}",
                        flush=True,
                    )
                    continue

                print(
                    f"DEEPGRAM: {transcript} is_final={is_final} speech_final={speech_final}",
                    flush=True,
                )
                await flow.handle_transcript(transcript)

        dg_task = asyncio.create_task(receive_deepgram())

        try:
            while True:
                try:
                    raw_msg = await asyncio.to_thread(ws.receive, 1)
                except ConnectionClosed:
                    print("TWILIO: websocket closed", flush=True)
                    break
                except Exception as exc:
                    print(f"TWILIO: websocket receive error: {exc}", flush=True)
                    break

                if raw_msg is None:
                    continue

                try:
                    event = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event")

                if event_type == "connected":
                    print("TWILIO: connected", flush=True)

                elif event_type == "start":
                    start_data = event.get("start", {}) or {}
                    stream_sid = event.get("streamSid") or start_data.get("streamSid")
                    print(f"TWILIO: stream started {stream_sid}", flush=True)

                    if stream_sid and not getattr(flow, "initial_prompt_sent", False):
                        flow.initial_prompt_sent = True
                        await flow.prompt_for_pin()

                elif event_type == "media":
                    payload = event.get("media", {}).get("payload")
                    if payload:
                        await dg_ws.send(base64.b64decode(payload))

                elif event_type == "dtmf":
                    digit = event.get("dtmf", {}).get("digit")
                    if digit:
                        print(f"TWILIO DTMF: {digit}", flush=True)
                        await flow.handle_dtmf(digit)

                elif event_type == "mark":
                    print(f"TWILIO MARK: {event.get('mark')}", flush=True)

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
    asyncio.run(media_stream_async(ws))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run terminal-only test mode.")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(run_cli())
        return

    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Flask app on 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
