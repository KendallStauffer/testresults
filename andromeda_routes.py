"""Andromeda utility routes for the existing Test Results Flask app.

Register with:
    from andromeda_routes import andromeda_bp
    app.register_blueprint(andromeda_bp)

Routes:
    POST /andromeda/email
    POST /andromeda/calendar/availability
    POST /andromeda/calendar/book
    POST /andromeda/calendar/find
    POST /andromeda/calendar/cancel
    POST /andromeda/calendar/reschedule
    POST /andromeda/sms/appointment
    GET  /andromeda/health
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import smtplib
import ssl
import time as time_module
import uuid
import urllib.parse
import urllib.request
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


def _normalize_email(value: str) -> str:
    return _clean(value, 320).lower()


def _normalize_phone(value: str) -> str:
    raw = _clean(value, 80)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) != 11 or not digits.startswith("1"):
        raise ValueError("Phone number must be a valid US/Canada number.")
    return "+" + digits


def _event_meet_url(event: dict) -> str:
    direct = _clean(event.get("hangoutLink"), 500)
    if direct:
        return direct
    conference = event.get("conferenceData") or {}
    for entry in conference.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return _clean(entry.get("uri"), 500)
    return ""


def _event_private(event: dict) -> dict:
    return ((event.get("extendedProperties") or {}).get("private") or {})


def _event_snapshot(event: dict) -> dict:
    private = _event_private(event)
    attendees = event.get("attendees") or []
    attendee_email = ""
    for attendee in attendees:
        address = _normalize_email(attendee.get("email"))
        if address and address != _normalize_email(CALENDAR_ID):
            attendee_email = address
            break
    start_raw = ((event.get("start") or {}).get("dateTime") or "")
    end_raw = ((event.get("end") or {}).get("dateTime") or "")
    return {
        "event_id": event.get("id", ""),
        "summary": event.get("summary", ""),
        "start": _parse_local(start_raw).isoformat() if start_raw else "",
        "end": _parse_local(end_raw).isoformat() if end_raw else "",
        "caller_name": private.get("caller_name", ""),
        "company": private.get("company", ""),
        "email": private.get("caller_email", "") or attendee_email,
        "phone": private.get("caller_phone", ""),
        "purpose": private.get("purpose", ""),
        "meet_url": _event_meet_url(event),
    }


def _find_andromeda_events(service, caller_name="", email="", appointment_date="", caller_phone=""):
    now = datetime.now(TZ)
    time_min = (now - timedelta(days=30)).isoformat()
    time_max = (now + timedelta(days=180)).isoformat()
    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=250,
    ).execute()
    wanted_name = _clean(caller_name, 120).lower()
    wanted_email = _normalize_email(email)
    wanted_phone = ""
    if caller_phone:
        try:
            wanted_phone = _normalize_phone(caller_phone)
        except Exception:
            wanted_phone = ""
    matches = []
    for event in result.get("items") or []:
        private = _event_private(event)
        if private.get("andromeda") != "1" and not str(event.get("summary") or "").startswith("Andromeda Appointment -"):
            continue
        snap = _event_snapshot(event)
        if appointment_date and snap["start"][:10] != appointment_date:
            continue
        if wanted_name:
            hay = (snap["caller_name"] + " " + snap["summary"]).lower()
            if wanted_name not in hay:
                continue
        if wanted_email and wanted_email != _normalize_email(snap["email"]):
            continue
        if wanted_phone:
            try:
                if wanted_phone != _normalize_phone(snap["phone"]):
                    continue
            except Exception:
                continue
        matches.append(snap)
    return matches[:10]


def _event_conflicts(service, start: datetime, end: datetime, ignore_event_id: str = "") -> bool:
    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    for event in result.get("items") or []:
        if ignore_event_id and event.get("id") == ignore_event_id:
            continue
        if event.get("status") == "cancelled":
            continue
        ev_start = ((event.get("start") or {}).get("dateTime") or "")
        ev_end = ((event.get("end") or {}).get("dateTime") or "")
        if not ev_start or not ev_end:
            continue
        if start < _parse_local(ev_end) and end > _parse_local(ev_start):
            return True
    return False


def _twilio_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        and (
            os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
            or os.getenv("TWILIO_FROM_NUMBER", "").strip()
            or os.getenv("TWILIO_NUMBER", "").strip()
        )
    )


def _send_twilio_sms(to_number: str, body: str) -> dict:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
    from_number = (os.getenv("TWILIO_FROM_NUMBER", "").strip() or os.getenv("TWILIO_NUMBER", "").strip())
    if not sid or not token or (not messaging_service_sid and not from_number):
        raise RuntimeError("Twilio SMS is not configured.")
    payload = {"To": _normalize_phone(to_number), "Body": body}
    if messaging_service_sid:
        payload["MessagingServiceSid"] = messaging_service_sid
    else:
        payload["From"] = _normalize_phone(from_number)
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    request_obj = urllib.request.Request(url, data=data, method="POST")
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    request_obj.add_header("Authorization", "Basic " + auth)
    request_obj.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request_obj, timeout=15) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    return {"sid": parsed.get("sid", ""), "status": parsed.get("status", "")}


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
    company = _clean(data.get("company"), 160) or "Not provided"
    category = _clean(data.get("category"), 40).lower() or "other"
    summary = _clean(data.get("summary"), 1800)
    urgency = _clean(data.get("urgency"), 20).lower() or "normal"
    recipient = _clean(data.get("recipient"), 20).lower() or "ken"
    disposition = _clean(data.get("disposition"), 200) or "Follow-up requested"

    allowed_categories = {"support", "sales", "vendor", "billing", "new_customer", "other"}
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

    labels = {
        "support": "SUPPORT",
        "sales": "SALES LEAD",
        "vendor": "VENDOR CALL",
        "billing": "BILLING",
        "new_customer": "NEW CUSTOMER SERVICE REQUEST",
        "other": "CALL FOLLOW-UP",
    }
    subject = f"{labels[category]} - {company} - {caller_name}"
    if urgency == "urgent":
        subject = "URGENT - " + subject

    now = datetime.now(TZ)
    body = "\n".join(
        [
            "Andromeda call follow-up",
            "",
            f"Caller: {caller_name}",
            f"Company: {company}",
            f"Callback number: {caller_phone}",
            f"Category: {labels[category]}",
            f"Urgency: {urgency.upper()}",
            f"Disposition: {disposition}",
            "",
            "Summary:",
            summary,
            "",
            f"Received: {now.strftime('%A, %B %d, %Y at %-I:%M %p')} Eastern",
            "Source: Andromeda / Apex Voice",
        ]
    )

    try:
        _send_email(to_address, subject, body)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    return jsonify(
        {
            "ok": True,
            "sent": True,
            "recipient": recipient,
            "to": to_address,
            "subject": subject,
        }
    )


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
    email = _normalize_email(data.get("email"))
    purpose = _clean(data.get("purpose"), 500)

    if not start_value or not caller_name or not company or not purpose:
        return jsonify({"ok": False, "error": "start_time, caller_name, company, and purpose are required."}), 400

    try:
        start = _parse_local(start_value)
        end = start + timedelta(minutes=APPOINTMENT_MINUTES)
        now = datetime.now(TZ)
        if start <= now or not _slot_allowed(start):
            return jsonify({"ok": False, "error": "Appointment must be a future 30-minute slot Monday-Friday between 1:00 PM and 3:00 PM Eastern."}), 400

        service = _calendar_service()
        if _event_conflicts(service, start, end):
            return jsonify({"ok": False, "error": "That time is no longer available. Check availability again."}), 409

        title = f"Andromeda Appointment - {caller_name} - {company}"
        description_lines = [
            f"Purpose: {purpose}",
            f"Caller: {caller_name}",
            f"Company: {company}",
            f"Phone: {caller_phone or 'not available'}",
        ]
        if email:
            description_lines.append(f"Caller email: {email}")
        description_lines.append("Booked by Andromeda / Apex Voice")

        event_body = {
            "summary": title,
            "description": "\
".join(description_lines),
            "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
            "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
            "extendedProperties": {
                "private": {
                    "andromeda": "1",
                    "caller_name": caller_name,
                    "company": company,
                    "caller_email": email,
                    "caller_phone": caller_phone,
                    "purpose": purpose,
                }
            },
        }
        if email:
            event_body["attendees"] = [{"email": email}]

        calendar_info = service.calendars().get(calendarId=CALENDAR_ID).execute()
        allowed_conferences = ((calendar_info.get("conferenceProperties") or {}).get("allowedConferenceSolutionTypes") or [])
        wants_meet = "hangoutsMeet" in allowed_conferences
        if wants_meet:
            event_body["conferenceData"] = {"createRequest": {"requestId": "andromeda-" + uuid.uuid4().hex}}

        insert_kwargs = {
            "calendarId": CALENDAR_ID,
            "body": event_body,
            "sendUpdates": "all" if email else "none",
        }
        if wants_meet:
            insert_kwargs["conferenceDataVersion"] = 1
        event = service.events().insert(**insert_kwargs).execute()

        # Meet generation can be asynchronous. Re-read briefly so the caller/SMS path gets the link when possible.
        if wants_meet and not _event_meet_url(event):
            event_id = event.get("id", "")
            for _ in range(4):
                time_module.sleep(0.35)
                event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
                if _event_meet_url(event):
                    break

        return jsonify({
            "ok": True,
            "booked": True,
            "event_id": event.get("id", ""),
            "calendar_id": CALENDAR_ID,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "appointment_minutes": APPOINTMENT_MINUTES,
            "purpose": purpose,
            "company": company,
            "email": email,
            "meet_url": _event_meet_url(event),
            "calendar_url": event.get("htmlLink", ""),
            "invite_sent": bool(email),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@andromeda_bp.post("/calendar/find")
def calendar_find():
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    data = _json_body()
    caller_name = _clean(data.get("caller_name"), 120)
    email = _normalize_email(data.get("email"))
    appointment_date = _clean(data.get("appointment_date"), 20)
    caller_phone = _clean(data.get("caller_phone"), 60)
    if not caller_name and not email and not appointment_date and not caller_phone:
        return jsonify({"ok": False, "error": "Provide at least one appointment identifier."}), 400
    try:
        service = _calendar_service()
        matches = _find_andromeda_events(service, caller_name, email, appointment_date, caller_phone)
        return jsonify({"ok": True, "count": len(matches), "appointments": matches})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@andromeda_bp.post("/calendar/cancel")
def calendar_cancel():
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    event_id = _clean(_json_body().get("event_id"), 200)
    if not event_id:
        return jsonify({"ok": False, "error": "event_id is required."}), 400
    try:
        service = _calendar_service()
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        snap = _event_snapshot(event)
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id, sendUpdates="all").execute()
        return jsonify({"ok": True, "cancelled": True, "appointment": snap})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@andromeda_bp.post("/calendar/reschedule")
def calendar_reschedule():
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    data = _json_body()
    event_id = _clean(data.get("event_id"), 200)
    new_start_value = _clean(data.get("new_start_time"), 100)
    if not event_id or not new_start_value:
        return jsonify({"ok": False, "error": "event_id and new_start_time are required."}), 400
    try:
        new_start = _parse_local(new_start_value)
        new_end = new_start + timedelta(minutes=APPOINTMENT_MINUTES)
        if new_start <= datetime.now(TZ) or not _slot_allowed(new_start):
            return jsonify({"ok": False, "error": "New appointment time must be a future allowed 30-minute slot."}), 400
        service = _calendar_service()
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        if _event_conflicts(service, new_start, new_end, ignore_event_id=event_id):
            return jsonify({"ok": False, "error": "That new time is no longer available."}), 409
        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": TZ_NAME}
        event["end"] = {"dateTime": new_end.isoformat(), "timeZone": TZ_NAME}
        updated = service.events().update(
            calendarId=CALENDAR_ID,
            eventId=event_id,
            body=event,
            sendUpdates="all",
            conferenceDataVersion=1,
        ).execute()
        return jsonify({
            "ok": True,
            "rescheduled": True,
            "event_id": event_id,
            "start": new_start.isoformat(),
            "end": new_end.isoformat(),
            "meet_url": _event_meet_url(updated),
            "appointment": _event_snapshot(updated),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@andromeda_bp.post("/sms/appointment")
def sms_appointment():
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    data = _json_body()
    event_id = _clean(data.get("event_id"), 200)
    phone_number = _clean(data.get("phone_number"), 80)
    if not event_id or not phone_number:
        return jsonify({"ok": False, "error": "event_id and phone_number are required."}), 400
    try:
        service = _calendar_service()
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        snap = _event_snapshot(event)
        meet_url = snap.get("meet_url", "")
        if not meet_url:
            return jsonify({"ok": False, "error": "Google Meet link is not available for this appointment yet."}), 409
        start = _parse_local(snap["start"])
        body = (
            "Affiliated Telecom appointment with Ken: "
            + start.strftime("%A, %B %-d at %-I:%M %p Eastern")
            + ". Google Meet: " + meet_url
        )
        twilio_result = _send_twilio_sms(phone_number, body)
        return jsonify({
            "ok": True,
            "sent": True,
            "to": _normalize_phone(phone_number),
            "event_id": event_id,
            "meet_url": meet_url,
            "message_sid": twilio_result.get("sid", ""),
            "message_status": twilio_result.get("status", ""),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


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
            "twilio_sms_configured": _twilio_configured(),
            "appointment_window": "Monday-Friday, 1:00 PM-3:00 PM Eastern",
            "appointment_minutes": APPOINTMENT_MINUTES,
        }
    )
