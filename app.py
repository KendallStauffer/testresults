from flask import Flask, request, Response, render_template_string, send_file, jsonify
from flask_sock import Sock
import pandas as pd
import os
import logging
import shutil
import re
import asyncio
import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
from html import escape
from werkzeug.utils import secure_filename
import websockets

try:
    from simple_websocket.errors import ConnectionClosed
except Exception:  # pragma: no cover
    ConnectionClosed = Exception


app = Flask(__name__)
sock = Sock(app)

# ====================== CONFIG ======================
UPLOAD_PASSWORD = "ForUSDA!2026"
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "change-this-now")

BASE_URL = os.environ.get("BASE_URL", "https://testresults-1aja.onrender.com").rstrip("/")

# Persistent disk paths
DATA_DIR = "/mnt/data"
CSV_PATH = os.path.join(DATA_DIR, "test_results_long.csv")
LOG_PATH = os.path.join(DATA_DIR, "call_logs.csv")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

active_calls = {}
df = pd.DataFrame()

# ====================== DATA / LOG HELPERS ======================
def normalize_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Keep this light: uploaded files may still arrive with spaces/case differences.
    This preserves the old upload behavior without doing heavy transformations.
    """
    dataframe.columns = [c.strip().lower().replace(" ", "_") for c in dataframe.columns]
    return dataframe


def load_data():
    global df
    try:
        if not os.path.exists(CSV_PATH):
            df = pd.DataFrame()
            logger.info(f"No CSV found at {CSV_PATH}")
            return False

        loaded = pd.read_csv(CSV_PATH)
        loaded = normalize_columns(loaded)

        if "pin_number" not in loaded.columns:
            raise ValueError("CSV missing Pin_Number / pin_number column")
        if "day" not in loaded.columns:
            raise ValueError("CSV missing day column")

        if "sequence_number" not in loaded.columns:
            loaded["sequence_number"] = 0

        for col in ["fat", "protein", "mun", "scc"]:
            if col not in loaded.columns:
                loaded[col] = 0

        loaded["pin_number"] = loaded["pin_number"].astype(str).str.strip().str.zfill(6)
        loaded["sequence_number"] = pd.to_numeric(loaded["sequence_number"], errors="coerce").fillna(0).astype(int)
        loaded["day"] = pd.to_numeric(loaded["day"], errors="coerce").fillna(0).astype(int)
        loaded["fat"] = pd.to_numeric(loaded["fat"], errors="coerce").fillna(0.0)
        loaded["protein"] = pd.to_numeric(loaded["protein"], errors="coerce").fillna(0.0)
        loaded["mun"] = pd.to_numeric(loaded["mun"], errors="coerce").fillna(0).astype(int)
        loaded["scc"] = pd.to_numeric(loaded["scc"], errors="coerce").fillna(0).astype(int)

        df = loaded
        logger.info(f"Loaded {len(df)} records from {CSV_PATH}")
        return True

    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        df = pd.DataFrame()
        return False


def init_call_log():
    if not os.path.exists(LOG_PATH):
        pd.DataFrame(columns=[
            "Timestamp", "CallerID", "CallUUID", "EnteredPIN", "Status", "Notes"
        ]).to_csv(LOG_PATH, index=False)
        logger.info("Created call_logs.csv")
    else:
        logger.info("call_logs.csv already exists - append only")


def log_call_to_csv(caller_id, call_uuid, entered_pin="", status="PIN Rejected", notes=""):
    try:
        file_exists = os.path.exists(LOG_PATH)
        new_row = pd.DataFrame([{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "CallerID": caller_id,
            "CallUUID": call_uuid,
            "EnteredPIN": entered_pin,
            "Status": status,
            "Notes": notes
        }])
        new_row.to_csv(LOG_PATH, mode="a", header=not file_exists, index=False)
        logger.info(f"APPENDED TO CSV: PIN={entered_pin} | Status={status} | Notes={notes}")
    except Exception as e:
        logger.error(f"Failed to append to call_logs.csv: {e}")


def speak_pin_digits(pin: str):
    return " ".join(list(pin))


def get_ws_url(path: str = "/media") -> str:
    return BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + path


# ====================== STARTUP ======================
load_data()
init_call_log()

# ====================== ADMIN ======================
@app.route("/status")
def status():
    record_count = len(df) if not df.empty else 0
    log_count = len(pd.read_csv(LOG_PATH)) if os.path.exists(LOG_PATH) else 0
    return jsonify({
        "ok": True,
        "records": record_count,
        "call_logs": log_count,
        "csv_path": CSV_PATH,
        "csv_exists": os.path.exists(CSV_PATH),
        "log_path": LOG_PATH,
        "log_exists": os.path.exists(LOG_PATH),
        "voice_stack": "twilio_deepgram"
    })


@app.route("/logs")
def view_logs():
    if not os.path.exists(LOG_PATH):
        return "<h2>No logs yet.</h2>"
    logs_df = pd.read_csv(LOG_PATH).sort_values("Timestamp", ascending=False).head(200)
    return render_template_string("""
        <h2>Recent Call Logs (200 newest)</h2>
        <a href="/status">← Back</a> | <a href="/download_logs">Download Full CSV</a><br><br>
        {{ html|safe }}
        <style>table, th, td {border:1px solid black; padding:8px;}</style>
    """, html=logs_df.to_html(index=False))


@app.route("/download_logs")
def download_logs():
    if not os.path.exists(LOG_PATH):
        return "No logs yet.", 404
    return send_file(LOG_PATH, as_attachment=True, download_name="call_logs.csv")


@app.route("/upload", methods=["GET", "POST"])
def upload_csv_manual():
    """
    Manual browser upload for you.
    """
    if request.method == "POST":
        if request.form.get("password") != UPLOAD_PASSWORD:
            return "<h2>Wrong password</h2><a href='/upload'>Try again</a>", 401

        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".csv"):
            return "<h2>Please upload a valid CSV</h2>", 400

        temp_name = secure_filename(file.filename)
        temp_path = os.path.join(DATA_DIR, f"manual_{temp_name}")
        file.save(temp_path)

        try:
            test_df = pd.read_csv(temp_path)
            test_df = normalize_columns(test_df)

            if "pin_number" not in test_df.columns:
                raise ValueError("CSV missing Pin_Number / pin_number column")
            if "day" not in test_df.columns:
                raise ValueError("CSV missing day column")

            if os.path.exists(CSV_PATH):
                backup_path = os.path.join(
                    BACKUP_DIR,
                    f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                shutil.copy2(CSV_PATH, backup_path)

            shutil.move(temp_path, CSV_PATH)
            load_data()

            return f"<h2>✅ Uploaded! {len(df)} records loaded.</h2><a href='/status'>Status</a>"

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return f"<h2>Upload failed: {e}</h2><a href='/upload'>Try again</a>", 400

    return """
        <h2>Upload test_results_long.csv</h2>
        <form method="post" enctype="multipart/form-data">
            Password: <input type="password" name="password"><br><br>
            File: <input type="file" name="file" accept=".csv"><br><br>
            <button type="submit">Upload</button>
        </form>
        <a href="/status">← Status</a>
    """


@app.route("/upload-csv", methods=["POST"])
def upload_csv_api():
    """
    Automated upload endpoint for customer script.
    """
    try:
        api_key = request.headers.get("X-API-Key", "")
        if api_key != UPLOAD_API_KEY:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file part"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"ok": False, "error": "No file selected"}), 400

        if not file.filename.lower().endswith(".csv"):
            return jsonify({"ok": False, "error": "Only CSV files are allowed"}), 400

        temp_name = secure_filename(file.filename)
        temp_path = os.path.join(DATA_DIR, f"api_{temp_name}")
        file.save(temp_path)

        test_df = pd.read_csv(temp_path)
        test_df = normalize_columns(test_df)

        if "pin_number" not in test_df.columns:
            raise ValueError("CSV missing Pin_Number / pin_number column")
        if "day" not in test_df.columns:
            raise ValueError("CSV missing day column")

        if os.path.exists(CSV_PATH):
            backup_path = os.path.join(
                BACKUP_DIR,
                f"test_results_long_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            shutil.copy2(CSV_PATH, backup_path)

        shutil.move(temp_path, CSV_PATH)
        load_data()

        return jsonify({
            "ok": True,
            "message": "CSV uploaded and reloaded successfully",
            "rows_loaded": len(df),
            "csv_path": CSV_PATH
        })

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ====================== DEEPGRAM / TWILIO VOICE FLOW ======================
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
REPEAT_WORDS = {"repeat", "again", "replay", "1", "one"}
GOODBYE_WORDS = {"goodbye", "bye", "end", "hangup", "hang", "2", "two"}


class Step(str, Enum):
    ASK_PIN = "ask_pin"
    CONFIRM_PIN = "confirm_pin"
    POST_RESULTS_ACTION = "post_results_action"
    ENDED = "ended"


def extract_digits(text: str) -> str:
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


def extract_post_results_action(text: str) -> Optional[str]:
    words = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
    if words & REPEAT_WORDS:
        return "repeat"
    if words & GOODBYE_WORDS:
        return "goodbye"
    return None


def format_results_for_pin(pin: str) -> list[str]:
    """
    Build speakable result lines for a confirmed PIN.
    """
    if df.empty:
        return []

    results_df = df[df["pin_number"] == pin].sort_values("sequence_number")
    if results_df.empty:
        return []

    lines = ["Here are your milk test results."]

    for _, row in results_df.iterrows():
        day = int(row.get("day", 0))
        fat = float(row.get("fat", 0))
        protein = float(row.get("protein", 0))
        scc = int(row.get("scc", 0))
        mun = int(row.get("mun", 0))

        lines.append(f"Sample from the {day}th.")
        lines.append(f"Butterfat {fat} percent.")
        lines.append(f"Protein {protein} percent.")
        lines.append(f"Somatic cell count {scc:,}.")
        if mun > 0:
            # Keep close to old wording. Change to "M U N" if preferred later.
            lines.append(f"Munn {mun}.")

    return lines


@dataclass
class VoiceFlow:
    say: Callable[[str], Awaitable[None]]
    caller_id: str = "unknown"
    call_uuid: str = "unknown"
    delay_seconds: float = 0.8
    step: Step = Step.ASK_PIN
    candidate_pin: str = ""
    confirmed_pin: str = ""
    dtmf_buffer: str = field(default_factory=str)
    end_call_requested: bool = False

    async def prompt_for_pin(self) -> None:
        self.step = Step.ASK_PIN
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        await self.say(
            "Thank you for calling the Milk Market Administrator Test Results Center. "
            "Please say or enter your 6 digit PIN."
        )

    async def retry_pin(self) -> None:
        self.step = Step.ASK_PIN
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        await self.say("Sorry, I didn't get that. Let's try again. Please say or enter your 6 digit PIN.")

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

        if self.step == Step.POST_RESULTS_ACTION:
            if digit == "1":
                await self.repeat_results()
            elif digit == "2":
                await self.goodbye()
            else:
                await self.ask_post_results_action()
            return

        if self.step != Step.ASK_PIN:
            return

        if digit == "*":
            self.dtmf_buffer = ""
            await self.retry_pin()
            return

        if digit == "#":
            await self.submit_pin_text(self.dtmf_buffer)
            return

        if re.fullmatch(r"\d", digit):
            self.dtmf_buffer += digit
            logger.info(f"DTMF buffer: {self.dtmf_buffer}")
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

        if self.step == Step.POST_RESULTS_ACTION:
            action = extract_post_results_action(transcript)
            if action == "repeat":
                await self.repeat_results()
            elif action == "goodbye":
                await self.goodbye()
            else:
                await self.ask_post_results_action()
            return

        if self.step == Step.ASK_PIN:
            await self.submit_pin_text(transcript)

    async def submit_pin_text(self, text: str) -> None:
        pin = extract_digits(text)

        # Ignore stale yes/no that arrives after a prior confirmation.
        if not pin and extract_yes_no(text) is not None:
            logger.info(f"IGNORED STRAY CONFIRMATION WHILE ASKING PIN: {text}")
            return

        # User requested: no input or anything other than 6 digits gets this exact retry flow.
        if not re.fullmatch(r"\d{6}", pin):
            log_call_to_csv(self.caller_id, self.call_uuid, pin, "PIN Rejected", "Failed pin attempt")
            await self.retry_pin()
            return

        self.candidate_pin = pin
        self.dtmf_buffer = ""
        self.step = Step.CONFIRM_PIN
        log_call_to_csv(self.caller_id, self.call_uuid, pin, "PIN Accepted", "Successful pin attempt")
        await self.say(
            f"Am I right with PIN {speak_pin_digits(pin)}? "
            "Press 1 or say yes, or no or press 2."
        )

    async def confirm_no(self) -> None:
        logger.info("User said NO to PIN confirmation")
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        await self.retry_pin()

    async def confirm_yes(self) -> None:
        pin = self.candidate_pin
        if not pin:
            await self.retry_pin()
            return

        self.confirmed_pin = pin
        self.candidate_pin = ""
        self.dtmf_buffer = ""
        log_call_to_csv(self.caller_id, self.call_uuid, pin, "PIN Accepted", "Results requested")
        await self.read_results()

    async def read_results(self) -> None:
        pin = self.confirmed_pin
        result_lines = format_results_for_pin(pin)

        if not result_lines:
            logger.info(f"No results found for PIN {pin}")
            log_call_to_csv(self.caller_id, self.call_uuid, pin, "PIN Rejected", "No results found")
            await self.retry_pin()
            return

        for line in result_lines:
            await self.say(line)
            await asyncio.sleep(0.1)

        log_call_to_csv(self.caller_id, self.call_uuid, pin, "PIN Accepted", "Results read")
        await self.ask_post_results_action()

    async def ask_post_results_action(self) -> None:
        self.step = Step.POST_RESULTS_ACTION
        await self.say(
            "To hear these results again, say repeat or press 1. "
            "To end the call, say goodbye or press 2."
        )

    async def repeat_results(self) -> None:
        log_call_to_csv(self.caller_id, self.call_uuid, self.confirmed_pin, "PIN Accepted", "Results repeated")
        await self.say("Repeating the results.")
        await self.read_results()

    async def goodbye(self) -> None:
        log_call_to_csv(self.caller_id, self.call_uuid, self.confirmed_pin, "PIN Accepted", "Call ended")
        await self.say("Thank you for calling. Goodbye.")
        self.step = Step.ENDED
        self.end_call_requested = True


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


def clear_twilio_audio(ws, stream_sid: Optional[str]) -> None:
    """
    Barge-in helper for confirmation/action prompts.
    """
    if not ws or not stream_sid:
        return
    try:
        ws.send(json.dumps({
            "event": "clear",
            "streamSid": stream_sid,
        }))
        logger.info("Sent Twilio clear for barge-in")
    except Exception as exc:
        logger.error(f"Failed to clear Twilio audio: {exc}")


async def say_to_call(text: str, ws=None, stream_sid: Optional[str] = None) -> None:
    """
    Send Deepgram TTS back to Twilio as one raw mu-law media message.
    Single-send is intentionally used because chunked mode caused static.
    """
    logger.info(f"APP SAY: {text}")

    if ws is None or not stream_sid:
        logger.info("No streamSid yet; prompt logged only")
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

        logger.info(f"Sent TTS to call: {len(audio)} bytes, mark={mark_name}")

    except Exception as exc:
        logger.error(f"Failed to speak prompt to call: {exc}")


@app.route("/voice", methods=["GET", "POST"])
def voice():
    """
    Twilio Voice webhook.

    Set your Twilio number webhook to:
    https://testresults-1aja.onrender.com/voice
    """
    caller = request.values.get("From", "unknown")
    call_sid = request.values.get("CallSid", request.values.get("CallUUID", "unknown"))
    logger.info(f"INCOMING_CALL | CallSid={call_sid} | From={caller}")

    ws_url = get_ws_url("/media")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{escape(ws_url)}">
      <Parameter name="caller" value="{escape(caller)}" />
      <Parameter name="call_sid" value="{escape(call_sid)}" />
    </Stream>
  </Connect>
</Response>"""
    return Response(xml, mimetype="application/xml")


@app.route("/hangup", methods=["POST", "GET"])
def hangup():
    call_uuid = request.values.get("CallSid", request.values.get("CallUUID", "unknown"))
    caller = request.values.get("From", "unknown")
    state = active_calls.get(call_uuid, {})
    pin = state.get("pin", "")
    status = "PIN Accepted" if pin and len(pin) == 6 else "PIN Rejected"
    logger.info(f"Call hung up - PIN={pin} Status={status}")
    log_call_to_csv(caller, call_uuid, pin, status, "Caller hung up")

    if call_uuid in active_calls:
        del active_calls[call_uuid]

    return Response("<Response></Response>", mimetype="application/xml")


async def media_stream_async(ws) -> None:
    stream_sid: Optional[str] = None
    caller_id = "unknown"
    call_uuid = "unknown"
    listen_resume_at = 0.0
    resume_delay_ms = int(os.getenv("LISTEN_RESUME_DELAY_MS", "0"))

    async def say(text: str) -> None:
        nonlocal listen_resume_at
        listen_resume_at = time.monotonic() + 3600.0
        await say_to_call(text, ws=ws, stream_sid=stream_sid)
        listen_resume_at = time.monotonic() + (resume_delay_ms / 1000.0)

    flow = VoiceFlow(say=say)
    flow.step = Step.ASK_PIN

    dg_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not dg_api_key:
        await say("Missing Deepgram API key on the server.")
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

    logger.info(
        f"DEEPGRAM STT SETTINGS: endpointing_ms={endpointing_ms}, "
        f"interim_results={interim_results}, smart_format={smart_format}"
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
                    logger.info(
                        f"DEEPGRAM IGNORED DURING TTS: {transcript} "
                        f"is_final={is_final} speech_final={speech_final}"
                    )
                    continue

                logger.info(f"DEEPGRAM: {transcript} is_final={is_final} speech_final={speech_final}")

                # Confirmation/action barge-in.
                if flow.step == Step.CONFIRM_PIN and extract_yes_no(transcript) is not None:
                    clear_twilio_audio(ws, stream_sid)
                elif flow.step == Step.POST_RESULTS_ACTION and extract_post_results_action(transcript) is not None:
                    clear_twilio_audio(ws, stream_sid)

                await flow.handle_transcript(transcript)

        dg_task = asyncio.create_task(receive_deepgram())

        try:
            while True:
                if flow.end_call_requested:
                    # Let final goodbye media/mark get out, then close the stream.
                    await asyncio.sleep(1.0)
                    break

                try:
                    raw_msg = await asyncio.to_thread(ws.receive, 1)
                except ConnectionClosed:
                    logger.info("TWILIO: websocket closed")
                    break
                except Exception as exc:
                    logger.error(f"TWILIO: websocket receive error: {exc}")
                    break

                if raw_msg is None:
                    continue

                try:
                    event = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event")

                if event_type == "connected":
                    logger.info("TWILIO: connected")

                elif event_type == "start":
                    start_data = event.get("start", {}) or {}
                    custom = start_data.get("customParameters") or {}

                    stream_sid = event.get("streamSid") or start_data.get("streamSid")
                    caller_id = custom.get("caller", caller_id)
                    call_uuid = custom.get("call_sid", call_uuid)

                    # Twilio also often includes callSid in start data.
                    call_uuid = start_data.get("callSid") or start_data.get("call_sid") or call_uuid

                    flow.caller_id = caller_id
                    flow.call_uuid = call_uuid

                    active_calls[call_uuid] = {
                        "caller": caller_id,
                        "stream_sid": stream_sid,
                        "pin": ""
                    }

                    logger.info(f"TWILIO: stream started streamSid={stream_sid} call={call_uuid} from={caller_id}")

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
                        logger.info(f"TWILIO DTMF: {digit}")

                        if flow.step == Step.CONFIRM_PIN and digit in {"1", "2", "0", "*"}:
                            clear_twilio_audio(ws, stream_sid)
                        elif flow.step == Step.POST_RESULTS_ACTION and digit in {"1", "2"}:
                            clear_twilio_audio(ws, stream_sid)

                        await flow.handle_dtmf(digit)

                        if flow.confirmed_pin and call_uuid in active_calls:
                            active_calls[call_uuid]["pin"] = flow.confirmed_pin

                elif event_type == "mark":
                    logger.info(f"TWILIO MARK: {event.get('mark')}")

                elif event_type == "stop":
                    logger.info("TWILIO: stream stopped")
                    break

        finally:
            dg_task.cancel()
            try:
                await dg_ws.close()
            except Exception:
                pass

            if call_uuid in active_calls and flow.end_call_requested:
                del active_calls[call_uuid]


@sock.route("/media")
def media(ws):
    asyncio.run(media_stream_async(ws))


# Legacy Plivo callback routes intentionally return a clear message now.
# They are kept only so old bookmarked/provider URLs fail safely instead of 404.
@app.route("/gather_pin", methods=["GET", "POST"])
@app.route("/confirm_pin", methods=["GET", "POST"])
@app.route("/handle_action", methods=["GET", "POST"])
def legacy_plivo_routes():
    return Response(
        "<Response><Speak>This app now uses Twilio and Deepgram. Please update the voice webhook to slash voice.</Speak></Response>",
        mimetype="application/xml"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"App running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
