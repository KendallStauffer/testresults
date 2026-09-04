"""Andromeda utility routes for the existing Test Results Flask app.

Register with:
    from andromeda_routes import andromeda_bp
    app.register_blueprint(andromeda_bp)

Routes:
    POST /andromeda/email
    POST /andromeda/tickets
    POST /andromeda/calendar/availability
    POST /andromeda/calendar/book
    POST /andromeda/lab/email
    GET  /andromeda/health
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, time
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

andromeda_bp = Blueprint("andromeda", __name__, url_prefix="/andromeda")

TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
CALENDAR_ID = os.getenv("GOOGLE_BUSINESS_CALENDAR_ID", "ken@ksac.com")
APPOINTMENT_MINUTES = 30
APPOINTMENT_START = time(13, 0)  # 1:00 PM Eastern
APPOINTMENT_END = time(15, 0)    # 3:00 PM Eastern
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def _api_key_ok() -> bool:
    expected = os.getenv("APEX_AGENT_BACKEND_KEY", "").strip()
    supplied = (request.headers.get("x-apex-agent-key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _unauthorized():
    return jsonify({"ok": False, "error": "Unauthorized"}), 401


def _require_auth():
    if not _api_key_ok():
        return _unauthorized()
    return None


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _clean(value, limit=500) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _parse_local(value: str) -> datetime:
    value = _clean(value, 100)
    if not value:
        raise ValueError("Missing datetime")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _appointment_window(day):
    return (
        datetime.combine(day, APPOINTMENT_START, TZ),
        datetime.combine(day, APPOINTMENT_END, TZ),
    )


def _slot_allowed(start: datetime) -> bool:
    start = start.astimezone(TZ)
    end = start + timedelta(minutes=APPOINTMENT_MINUTES)
    window_start, window_end = _appointment_window(start.date())
    return start.weekday() < 5 and start >= window_start and end <= window_end


def _calendar_credentials():
    raw_b64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw_b64:
        raw_json = base64.b64decode(raw_b64).decode("utf-8")
    if raw_json:
        info = json.loads(raw_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=[CALENDAR_SCOPE]
        )

    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if refresh_token and client_id and client_secret:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[CALENDAR_SCOPE],
        )
        creds.refresh(GoogleAuthRequest())
        return creds

    raise RuntimeError(
        "Google Calendar credentials are not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON_B64 "
        "or GOOGLE_SERVICE_ACCOUNT_JSON, or the OAuth refresh-token variables."
    )


def _calendar_service():
    return build("calendar", "v3", credentials=_calendar_credentials(), cache_discovery=False)


def _busy_for(service, start: datetime, end: datetime):
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": TZ_NAME,
        "items": [{"id": CALENDAR_ID}],
    }
    result = service.freebusy().query(body=body).execute()
    calendar = result.get("calendars", {}).get(CALENDAR_ID, {})
    if calendar.get("errors"):
        raise RuntimeError("Google Calendar is not accessible to the configured credentials.")
    return [(_parse_local(x["start"]), _parse_local(x["end"])) for x in calendar.get("busy", [])]


def _overlaps(start: datetime, end: datetime, busy) -> bool:
    return any(start < b_end and end > b_start for b_start, b_end in busy)


def _available_slots_for_day(service, day, now: datetime):
    if day.weekday() >= 5:
        return []
    window_start, window_end = _appointment_window(day)
    busy = _busy_for(service, window_start, window_end)
    slots = []
    cursor = window_start
    duration = timedelta(minutes=APPOINTMENT_MINUTES)
    while cursor + duration <= window_end:
        if cursor > now and not _overlaps(cursor, cursor + duration, busy):
            slots.append({"start": cursor.isoformat(), "end": (cursor + duration).isoformat()})
        cursor += duration
    return slots


def _smtp_configured() -> bool:
    return bool(
        os.getenv("ANDROMEDA_SMTP_USER", "").strip()
        and os.getenv("ANDROMEDA_SMTP_APP_PASSWORD", "").strip()
    )


def _send_email(to_address: str, subject: str, body: str):
    host = os.getenv("ANDROMEDA_SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("ANDROMEDA_SMTP_PORT", "465"))
    user = os.getenv("ANDROMEDA_SMTP_USER", "").strip()
    password = os.getenv("ANDROMEDA_SMTP_APP_PASSWORD", "").strip()
    from_email = os.getenv("ANDROMEDA_FROM_EMAIL", user).strip() or user
    from_name = os.getenv("ANDROMEDA_FROM_NAME", "Andromeda - Apex Voice").strip()
    if not user or not password:
        raise RuntimeError("Andromeda SMTP is not configured.")

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


@andromeda_bp.post("/email")
def send_call_info():
    auth_error = _require_auth()
    if auth_error:
        return auth_error

    data = _json_body()
    caller_name = _clean(data.get("caller_name"), 120) or "Unknown caller"
    caller_phone = _clean(data.get("caller_phone"), 60) or "Unavailable"
    company = _clean(data.get("company"), 160)
    category = _clean(data.get("category"), 40).lower() or "other"
    purpose = _clean(data.get("purpose"), 500)
    summary = _clean(data.get("summary"), 1800)
    urgency = _clean(data.get("urgency"), 20).lower() or "normal"
    recipient = _clean(data.get("recipient"), 20).lower() or "ken"
    disposition = _clean(data.get("disposition"), 200) or "Follow-up requested"

    allowed_categories = {"support", "sales", "personal", "other"}
    if category not in allowed_categories:
        category = "other"
    if urgency not in {"normal", "urgent"}:
        urgency = "normal"
    if recipient not in {"ken", "sandy"}:
        return jsonify({"ok": False, "error": "Invalid recipient."}), 400
    if not summary:
        return jsonify({"ok": False, "error": "Summary is required."}), 400

    to_address = (
        os.getenv("ANDROMEDA_KEN_EMAIL", "ken@ksac.com").strip()
        if recipient == "ken"
        else os.getenv("ANDROMEDA_SANDY_EMAIL", "sandy@ksac.com").strip()
    )

    labels = {"support": "Support", "sales": "Sales", "personal": "Personal", "other": "Other"}
    subject_parts = [labels[category]]
    if company:
        subject_parts.append(company)
    subject_parts.append(caller_name)
    subject = " - ".join(subject_parts)
    if urgency == "urgent":
        subject = "URGENT - " + subject

    now = datetime.now(TZ)
    body_lines = [
        "Andromeda call follow-up", "",
        f"Caller: {caller_name}",
        f"Company: {company or 'Not provided'}",
        f"Callback number: {caller_phone}",
        f"Category: {labels[category]}",
    ]
    if purpose:
        body_lines.append(f"Purpose: {purpose}")
    body_lines += [
        f"Urgency: {urgency.upper()}",
        f"Disposition: {disposition}", "", "Summary:", summary, "",
        f"Received: {now.strftime('%A, %B %d, %Y at %-I:%M %p')} Eastern",
        "Source: Andromeda / Apex Voice",
    ]
    try:
        _send_email(to_address, subject, "\n".join(body_lines))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "sent": True, "recipient": recipient, "to": to_address, "subject": subject})



@andromeda_bp.post("/calendar/availability")
def calendar_availability():
    auth_error = _require_auth()
    if auth_error:
        return auth_error

    data = _json_body()
    requested_date = _clean(data.get("requested_date"), 20)
    requested_start = _clean(data.get("requested_start"), 100)
    now = datetime.now(TZ)

    try:
        service = _calendar_service()

        if requested_start:
            start = _parse_local(requested_start)
            end = start + timedelta(minutes=APPOINTMENT_MINUTES)
            if not _slot_allowed(start) or start <= now:
                return jsonify(
                    {
                        "ok": True,
                        "requested_available": False,
                        "requested_start": start.isoformat(),
                        "reason": "outside_appointment_window_or_past",
                        "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern, 30-minute appointments",
                        "available_slots": [],
                    }
                )
            window_start, window_end = _appointment_window(start.date())
            busy = _busy_for(service, window_start, window_end)
            available = not _overlaps(start, end, busy)
            return jsonify(
                {
                    "ok": True,
                    "requested_available": available,
                    "requested_start": start.isoformat(),
                    "requested_end": end.isoformat(),
                    "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern, 30-minute appointments",
                    "available_slots": [{"start": start.isoformat(), "end": end.isoformat()}] if available else [],
                }
            )

        if requested_date:
            day = datetime.fromisoformat(requested_date).date()
            slots = _available_slots_for_day(service, day, now)
            return jsonify(
                {
                    "ok": True,
                    "timezone": TZ_NAME,
                    "appointment_minutes": APPOINTMENT_MINUTES,
                    "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern",
                    "requested_date": requested_date,
                    "available_slots": slots,
                }
            )

        slots = []
        day = now.date()
        checked = 0
        while len(slots) < 8 and checked < 14:
            if day.weekday() < 5:
                slots.extend(_available_slots_for_day(service, day, now))
            day += timedelta(days=1)
            checked += 1
        return jsonify(
            {
                "ok": True,
                "timezone": TZ_NAME,
                "appointment_minutes": APPOINTMENT_MINUTES,
                "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern",
                "available_slots": slots[:8],
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@andromeda_bp.post("/calendar/book")
def calendar_book():
    auth_error = _require_auth()
    if auth_error:
        return auth_error

    data = _json_body()
    start_value = _clean(data.get("start_time"), 100)
    caller_name = _clean(data.get("caller_name"), 120)
    caller_phone = _clean(data.get("caller_phone"), 60)
    company = _clean(data.get("company"), 160)
    email = _clean(data.get("email"), 200)
    purpose = _clean(data.get("purpose"), 500)

    if not start_value or not caller_name or not purpose:
        return jsonify({"ok": False, "error": "start_time, caller_name, and purpose are required."}), 400

    try:
        start = _parse_local(start_value)
        end = start + timedelta(minutes=APPOINTMENT_MINUTES)
        now = datetime.now(TZ)
        if start <= now or not _slot_allowed(start):
            return jsonify(
                {
                    "ok": False,
                    "error": "Appointment must be a future 30-minute slot Monday-Friday between 1:00 PM and 3:00 PM Eastern.",
                }
            ), 400

        service = _calendar_service()
        window_start, window_end = _appointment_window(start.date())
        busy = _busy_for(service, window_start, window_end)
        if _overlaps(start, end, busy):
            return jsonify({"ok": False, "error": "That time is no longer available. Check availability again."}), 409

        title = f"Andromeda Appointment - {caller_name}"
        if company:
            title += f" - {company}"
        description_lines = [
            f"Purpose: {purpose}",
            f"Caller: {caller_name}",
            f"Phone: {caller_phone or 'not available'}",
        ]
        if company:
            description_lines.append(f"Company: {company}")
        if email:
            description_lines.append(f"Caller email: {email}")
        description_lines.append("Booked by Andromeda / Apex Voice")

        event_body = {
            "summary": title,
            "description": "\n".join(description_lines),
            "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
            "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
            "conferenceData": {
                "createRequest": {
                    "requestId": "andromeda-" + uuid.uuid4().hex,
                }
            },
        }
        event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event_body,
            sendUpdates="none",
            conferenceDataVersion=1,
        ).execute()

        meet_url = _clean(event.get("hangoutLink"), 500)
        if not meet_url:
            conference_data = event.get("conferenceData") or {}
            for entry in conference_data.get("entryPoints") or []:
                if str(entry.get("entryPointType") or "").lower() == "video" and entry.get("uri"):
                    meet_url = _clean(entry.get("uri"), 500)
                    break

        return jsonify(
            {
                "ok": True,
                "booked": True,
                "event_id": event.get("id", ""),
                "calendar_id": CALENDAR_ID,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "appointment_minutes": APPOINTMENT_MINUTES,
                "purpose": purpose,
                "meet_url": meet_url,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.I,
)


@andromeda_bp.post("/lab/email")
def lab_capture_email():
    """Email-only voice lab endpoint. Validates the caller-confirmed address.

    This endpoint deliberately does not send SMS and does not modify Calendar.
    """
    auth_error = _require_auth()
    if auth_error:
        return auth_error

    data = _json_body()
    email = _clean(data.get("email"), 320).lower()
    if not EMAIL_RE.fullmatch(email):
        return jsonify({"ok": False, "error": "Email address did not validate."}), 400

    return jsonify({"ok": True, "email": email, "captured": True})


@andromeda_bp.get("/health")
def health():
    auth_error = _require_auth()
    if auth_error:
        return auth_error

    calendar_auth = "none"
    if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip() or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        calendar_auth = "service_account"
    elif all(
        os.getenv(name, "").strip()
        for name in ("GOOGLE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    ):
        calendar_auth = "oauth_refresh_token"

    return jsonify(
        {
            "ok": True,
            "service": "andromeda-testresults-addon",
            "calendar_id": CALENDAR_ID,
            "calendar_auth": calendar_auth,
            "smtp_configured": _smtp_configured(),
            "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern",
            "appointment_minutes": APPOINTMENT_MINUTES,
        }
    )
