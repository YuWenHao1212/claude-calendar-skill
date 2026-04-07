#!/usr/bin/env python3
"""
Calendar operations for Claude Code — Mac (JXA) & Windows/Linux (.ics URL).
Reads config from env.md in the skill directory.

Features:
  - Read calendar events (Mac: Apple Calendar, Windows/Linux: .ics URL)
  - Find available time slots
  - Create events (Mac: Apple Calendar, Others: export .ics)
  - Generate .ics invite files (cross-platform, RFC 5545 compliant)

Requires: Python 3.8+
"""

import sys
import os
import json
import re
import subprocess
import time
import tempfile
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, "env.md")

# Local timezone offset (detected once at import)
LOCAL_TZ = datetime.now(timezone.utc).astimezone().tzinfo


# --- Config ---

def load_env():
  """Load key: value pairs from env.md."""
  env = {}
  if not os.path.exists(ENV_FILE):
    print(json.dumps({"error": "env.md not found. Run setup first."}))
    sys.exit(1)
  with open(ENV_FILE) as f:
    for line in f:
      line = line.strip()
      if ":" in line and not line.startswith("#"):
        key, val = line.split(":", 1)
        env[key.strip()] = val.strip()
  return env


def detect_platform():
  """Detect Mac, Linux, or Windows."""
  if sys.platform == "darwin":
    return "mac"
  elif sys.platform.startswith("linux"):
    return "linux"
  return "windows"


def safe_int(val, default):
  """Parse int safely."""
  try:
    return int(val)
  except (ValueError, TypeError):
    return default


def utc_to_local(dt_utc):
  """Convert UTC datetime to local timezone."""
  if dt_utc.tzinfo is None:
    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
  return dt_utc.astimezone(LOCAL_TZ)


def sanitize_ics_text(text):
  """Remove CRLF and control characters to prevent iCalendar property injection."""
  if not text:
    return ""
  return re.sub(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


# --- Mac: JXA (JavaScript for Automation) ---

# JXA script for reading events — uses env var for calendar name (no injection)
READ_EVENTS_JXA = '''
const calName = $.NSProcessInfo.processInfo.environment.objectForKey("CAL_NAME").js;
const days = parseInt($.NSProcessInfo.processInfo.environment.objectForKey("CAL_DAYS").js);
const Calendar = Application("Calendar");
const cal = Calendar.calendars.whose({name: calName})[0];
const now = new Date();
const end = new Date(now.getTime() + days * 86400000);
const events = cal.events.whose({
  _and: [
    {startDate: {_greaterThan: now}},
    {startDate: {_lessThan: end}}
  ]
})();
const result = events.map(function(e) {
  return {
    summary: e.summary(),
    start: e.startDate().toISOString(),
    end: e.endDate().toISOString(),
    description: e.description() || "",
    location: e.location() || ""
  };
});
JSON.stringify(result);
'''

# JXA script for creating events — uses env var for all data (no injection)
CREATE_EVENT_JXA = '''
const data = JSON.parse($.NSProcessInfo.processInfo.environment.objectForKey("EVENT_DATA").js);
const Calendar = Application("Calendar");
const cal = Calendar.calendars.whose({name: data.calendarName})[0];
const event = Calendar.Event({
  summary: data.summary,
  startDate: new Date(data.start),
  endDate: new Date(data.end),
  description: data.description,
  location: data.location
});
cal.events.push(event);
JSON.stringify({status: "created", summary: data.summary});
'''


def read_events_jxa(calendar_name, days):
  """Read events from Apple Calendar using JXA. All params via env vars."""
  try:
    env = os.environ.copy()
    env["CAL_NAME"] = calendar_name
    env["CAL_DAYS"] = str(days)
    result = subprocess.run(
      ["osascript", "-l", "JavaScript", "-e", READ_EVENTS_JXA],
      capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    output = result.stdout.strip()
    if not output:
      return []
    events = json.loads(output)
    # Convert UTC ISO strings to local time
    for e in events:
      for field in ("start", "end"):
        raw = e.get(field, "")
        if raw:
          try:
            dt_utc = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt_local = utc_to_local(dt_utc)
            e[field] = dt_local.strftime("%Y-%m-%d %H:%M")
          except (ValueError, AttributeError):
            pass
    return events
  except subprocess.TimeoutExpired:
    return {"error": "osascript timed out"}
  except json.JSONDecodeError as ex:
    return {"error": "Failed to parse JXA output: {}".format(ex)}
  except Exception as e:
    return {"error": str(e)}


def create_event_jxa(calendar_name, summary, start_iso, end_iso, description="", location=""):
  """Create event in Apple Calendar using JXA. All data via env var JSON."""
  event_data = json.dumps({
    "calendarName": calendar_name,
    "summary": summary,
    "start": start_iso,
    "end": end_iso,
    "description": description,
    "location": location,
  })
  try:
    env = os.environ.copy()
    env["EVENT_DATA"] = event_data
    result = subprocess.run(
      ["osascript", "-l", "JavaScript", "-e", CREATE_EVENT_JXA],
      capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    out = result.stdout.strip()
    return json.loads(out) if out else {"status": "created", "summary": summary}
  except Exception as e:
    return {"error": str(e)}


# --- Windows/Linux: .ics URL ---

def validate_ics_url(url):
  """Validate .ics URL — must be https (http allowed), block internal IPs."""
  if not url or not isinstance(url, str):
    return False
  if not url.startswith("https://") and not url.startswith("http://"):
    return False
  # Block common internal/metadata IPs
  blocked_prefixes = ["169.254.", "127.0.", "127.", "10.", "172.16.", "172.17.",
                      "172.18.", "172.19.", "172.20.", "172.21.", "172.22.",
                      "172.23.", "172.24.", "172.25.", "172.26.", "172.27.",
                      "172.28.", "172.29.", "172.30.", "172.31.", "192.168.", "0."]
  blocked_exact = ["localhost", "::1"]
  from urllib.parse import urlparse
  host = urlparse(url).hostname or ""
  for b in blocked_prefixes:
    if host.startswith(b):
      return False
  if host in blocked_exact:
    return False
  return True


def read_events_ics_url(ics_url, days):
  """Read events from .ics URL, parse VEVENT blocks."""
  if not validate_ics_url(ics_url):
    return {"error": "Invalid or blocked .ics URL."}

  import urllib.request
  try:
    data = urllib.request.urlopen(ics_url, timeout=30).read().decode("utf-8", errors="replace")
  except Exception as e:
    return {"error": "Failed to fetch .ics URL: {}".format(e)}

  now = datetime.now(timezone.utc)
  end_date = now + timedelta(days=days)
  events = []

  vevent_pattern = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL)
  for match in vevent_pattern.finditer(data):
    block = match.group(1)
    # Unfold continuation lines (RFC 5545)
    block = re.sub(r"\r?\n[ \t]", "", block)

    event = {}
    for field, key in [("SUMMARY", "summary"), ("DESCRIPTION", "description"),
                       ("LOCATION", "location")]:
      m = re.search(r"^" + field + r"[^:]*:(.+)$", block, re.MULTILINE)
      event[key] = m.group(1).strip() if m else ""

    # Extract DTSTART with optional TZID
    start_match = re.search(r"^DTSTART(?:;[^:]*TZID=([^:;]+))?[^:]*:(.+)$", block, re.MULTILINE)
    start_raw = start_match.group(2).strip() if start_match else ""
    start_tzid = start_match.group(1) if start_match and start_match.group(1) else None

    # Extract DTEND with optional TZID
    end_match = re.search(r"^DTEND(?:;[^:]*TZID=([^:;]+))?[^:]*:(.+)$", block, re.MULTILINE)
    end_raw = end_match.group(2).strip() if end_match else ""
    end_tzid = end_match.group(1) if end_match and end_match.group(1) else None

    dt = parse_ics_datetime(start_raw, start_tzid)
    if dt and now <= dt <= end_date:
      dt_local = utc_to_local(dt)
      event["start"] = dt_local.strftime("%Y-%m-%d %H:%M")
      dt_end = parse_ics_datetime(end_raw, end_tzid)
      if dt_end:
        dt_end_local = utc_to_local(dt_end)
        event["end"] = dt_end_local.strftime("%Y-%m-%d %H:%M")
      event["description"] = event.get("description", "").replace("\\n", "\n").replace("\\,", ",")
      events.append(event)

  events.sort(key=lambda e: e.get("start", ""))
  return events


# Common TZID to UTC offset mapping (avoids zoneinfo dependency for Python 3.8 compat)
TZID_OFFSETS = {
  "Asia/Taipei": 8, "Asia/Tokyo": 9, "Asia/Shanghai": 8, "Asia/Hong_Kong": 8,
  "Asia/Singapore": 8, "Asia/Seoul": 9, "Asia/Kolkata": 5.5,
  "America/New_York": -5, "America/Chicago": -6, "America/Denver": -7,
  "America/Los_Angeles": -8, "America/Toronto": -5,
  "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1, "Europe/Moscow": 3,
  "Australia/Sydney": 11, "Pacific/Auckland": 13,
  "US/Eastern": -5, "US/Central": -6, "US/Mountain": -7, "US/Pacific": -8,
}


def parse_ics_datetime(raw, tzid=None):
  """Parse iCalendar datetime to timezone-aware UTC datetime.
  Handles: 20260408T140000Z, 20260408T140000, 20260408, and TZID parameter."""
  if not raw:
    return None
  raw = raw.strip()
  try:
    if raw.endswith("Z"):
      return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    elif "T" in raw:
      dt_naive = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
      if tzid and tzid in TZID_OFFSETS:
        offset_hours = TZID_OFFSETS[tzid]
        tz = timezone(timedelta(hours=offset_hours))
        return dt_naive.replace(tzinfo=tz).astimezone(timezone.utc)
      # No TZID — assume local timezone
      return dt_naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    else:
      return datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
  except ValueError:
    return None


# --- Cross-platform ---

def find_slots(events, days=7, duration_min=60, work_start=9, work_end=18):
  """Find available slots. All times in local timezone. Skip weekends."""
  if isinstance(events, dict) and "error" in events:
    return events

  now = datetime.now()
  slots = []

  for day_offset in range(days):
    day = now.date() + timedelta(days=day_offset)
    if day.weekday() >= 5:
      continue

    day_start = datetime.combine(day, datetime.min.time().replace(hour=work_start))
    day_end = datetime.combine(day, datetime.min.time().replace(hour=work_end))

    if day == now.date():
      day_start = max(day_start, now.replace(second=0, microsecond=0))

    day_events = []
    day_str = day.strftime("%Y-%m-%d")
    for e in events:
      e_start = e.get("start", "")
      if isinstance(e_start, str) and day_str in e_start:
        day_events.append(e)

    busy = []
    for e in day_events:
      try:
        s = datetime.strptime(e["start"], "%Y-%m-%d %H:%M")
        end_str = e.get("end", "")
        en = datetime.strptime(end_str, "%Y-%m-%d %H:%M") if end_str else s + timedelta(hours=1)
        busy.append((s, en))
      except (ValueError, KeyError):
        continue
    busy.sort()

    cursor = day_start
    for b_start, b_end in busy:
      if cursor + timedelta(minutes=duration_min) <= b_start:
        slots.append({
          "date": day_str,
          "weekday": day.strftime("%A"),
          "start": cursor.strftime("%H:%M"),
          "end": b_start.strftime("%H:%M"),
          "duration_min": int((b_start - cursor).total_seconds() / 60),
        })
      cursor = max(cursor, b_end)
    if cursor + timedelta(minutes=duration_min) <= day_end:
      slots.append({
        "date": day_str,
        "weekday": day.strftime("%A"),
        "start": cursor.strftime("%H:%M"),
        "end": day_end.strftime("%H:%M"),
        "duration_min": int((day_end - cursor).total_seconds() / 60),
      })

  return slots


def fold_ics_line(line):
  """Fold long lines per RFC 5545 (max 75 octets)."""
  encoded = line.encode("utf-8")
  if len(encoded) <= 75:
    return line
  result = []
  while len(encoded) > 75:
    cut = 75 if not result else 74
    while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
      cut -= 1
    chunk = encoded[:cut].decode("utf-8")
    if result:
      result.append(" " + chunk)
    else:
      result.append(chunk)
    encoded = encoded[cut:]
  if encoded:
    tail = encoded.decode("utf-8")
    result.append(" " + tail if result else tail)
  return "\r\n".join(result)


def generate_ics(summary, start, end, organizer, attendees,
                 description="", meet_url=None, uid=None):
  """Generate RFC 5545 .ics content. All text inputs are sanitized."""
  uid = uid or "{}-{}@calendar-skill".format(int(time.time()), os.getpid())

  # Sanitize text inputs (strip \r and control chars, but preserve \n for description escaping)
  summary = sanitize_ics_text(summary)
  organizer = sanitize_ics_text(organizer)
  # Description: only strip \r and control chars, keep \n for proper escaping below
  description = re.sub(r"[\r\x00-\x08\x0b\x0c\x0e-\x1f]", " ", description) if description else ""
  if meet_url:
    meet_url = sanitize_ics_text(meet_url)

  def to_ical_utc(iso_str):
    clean = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', iso_str)
    try:
      d = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
      d = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
      d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

  dtstart = to_ical_utc(start)
  dtend = to_ical_utc(end)
  now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

  lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//claude-calendar-skill//calendar_ops//EN",
    "METHOD:REQUEST",
    "BEGIN:VEVENT",
    "UID:{}".format(uid),
    "DTSTART:{}".format(dtstart),
    "DTEND:{}".format(dtend),
    "DTSTAMP:{}".format(now_utc),
    "ORGANIZER;CN=Organizer:mailto:{}".format(organizer),
    "SUMMARY:{}".format(summary),
  ]
  if description:
    desc_escaped = description.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,")
    lines.append("DESCRIPTION:{}".format(desc_escaped))
  if attendees:
    for addr in attendees.split(","):
      addr = sanitize_ics_text(addr.strip())
      if addr:
        lines.append("ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{}".format(addr))
  if meet_url:
    lines.append("LOCATION:{}".format(meet_url))
  lines.append("STATUS:CONFIRMED")
  lines.append("SEQUENCE:0")
  lines.append("END:VEVENT")
  lines.append("END:VCALENDAR")

  return "\r\n".join(fold_ics_line(l) for l in lines)


def safe_write_tmp(content, prefix="cal-", suffix=".ics"):
  """Write to a secure temp file. Returns path."""
  fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
  try:
    os.fchmod(fd, 0o600)
    os.write(fd, content.encode("utf-8"))
  finally:
    os.close(fd)
  return path


def safe_output_path(requested_path):
  """Validate output path. Returns path or None (use safe_write_tmp instead)."""
  if not requested_path:
    return None
  resolved = os.path.realpath(requested_path)
  # Use realpath for /tmp too (macOS: /tmp → /private/tmp)
  allowed = [os.path.realpath("/tmp"), os.path.realpath(SKILL_DIR)]
  if not any(resolved.startswith(d) for d in allowed):
    return None
  return resolved


# --- Commands ---

def cmd_read_events(days=7):
  """Read calendar events."""
  try:
    env = load_env()
    platform = env.get("platform", detect_platform())
    if platform == "mac":
      events = read_events_jxa(env.get("calendar_name", "Calendar"), days)
    else:
      ics_url = env.get("ics_url", "")
      if not ics_url:
        print(json.dumps({"error": "No ics_url in env.md. Run setup."}))
        return
      events = read_events_ics_url(ics_url, days)
    print(json.dumps(events, indent=2, ensure_ascii=False))
  except Exception as e:
    print(json.dumps({"error": str(e)}))


def cmd_find_slots(days=7, duration_min=60):
  """Find available time slots."""
  try:
    env = load_env()
    platform = env.get("platform", detect_platform())
    if platform == "mac":
      events = read_events_jxa(env.get("calendar_name", "Calendar"), days)
    else:
      ics_url = env.get("ics_url", "")
      if not ics_url:
        print(json.dumps({"error": "No ics_url in env.md. Run setup."}))
        return
      events = read_events_ics_url(ics_url, days)
    slots = find_slots(events, days, duration_min)
    print(json.dumps(slots, indent=2, ensure_ascii=False))
  except Exception as e:
    print(json.dumps({"error": str(e)}))


def cmd_create_event(summary, start, end, description="", location=""):
  """Create event. Mac: Apple Calendar. Others: .ics export."""
  try:
    env = load_env()
    platform = env.get("platform", detect_platform())
    if platform == "mac":
      result = create_event_jxa(env.get("calendar_name", "Calendar"),
                                summary, start, end, description, location)
    else:
      organizer = env.get("organizer_email", "user@example.com")
      ics_content = generate_ics(summary, start, end, organizer, "", description, location)
      path = safe_write_tmp(ics_content, prefix="event-")
      result = {"status": "created", "method": "ics_file", "path": path,
                "message": "Double-click the .ics file to import into your calendar."}
    print(json.dumps(result, indent=2, ensure_ascii=False))
  except Exception as e:
    print(json.dumps({"error": str(e)}))


def cmd_generate_ics(summary, start, end, organizer, attendees,
                     description="", meet_url=None, output_path=None):
  """Generate .ics invite file."""
  try:
    env = load_env()
    if not meet_url:
      meet_url = env.get("meet_url", "")
    ics_content = generate_ics(summary, start, end, organizer, attendees, description, meet_url)
    validated = safe_output_path(output_path)
    if validated:
      # Write with restricted permissions (same as safe_write_tmp)
      fd = os.open(validated, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
      try:
        os.write(fd, ics_content.encode("utf-8"))
      finally:
        os.close(fd)
      path = validated
    else:
      path = safe_write_tmp(ics_content, prefix="invite-")
    print(json.dumps({"status": "ok", "path": path}, ensure_ascii=False))
  except Exception as e:
    print(json.dumps({"error": str(e)}))


# --- CLI ---

if __name__ == "__main__":
  if len(sys.argv) < 2:
    print("Usage: calendar_ops.py <command> [args]")
    print("Commands: read_events, find_slots, create_event, generate_ics, detect_platform")
    sys.exit(1)

  cmd = sys.argv[1]

  if cmd == "read_events":
    cmd_read_events(safe_int(sys.argv[2] if len(sys.argv) > 2 else None, 7))

  elif cmd == "find_slots":
    cmd_find_slots(
      safe_int(sys.argv[2] if len(sys.argv) > 2 else None, 7),
      safe_int(sys.argv[3] if len(sys.argv) > 3 else None, 60)
    )

  elif cmd == "create_event":
    if len(sys.argv) < 5:
      print(json.dumps({"error": "Usage: create_event <summary> <start> <end> [description] [location]"}))
      sys.exit(1)
    cmd_create_event(
      sys.argv[2], sys.argv[3], sys.argv[4],
      sys.argv[5] if len(sys.argv) > 5 else "",
      sys.argv[6] if len(sys.argv) > 6 else ""
    )

  elif cmd == "generate_ics":
    if len(sys.argv) < 7:
      print(json.dumps({"error": "Usage: generate_ics <summary> <start> <end> <organizer> <attendees> [description] [meet_url] [output_path]"}))
      sys.exit(1)
    cmd_generate_ics(
      sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6],
      sys.argv[7] if len(sys.argv) > 7 else "",
      sys.argv[8] if len(sys.argv) > 8 else None,
      sys.argv[9] if len(sys.argv) > 9 else None
    )

  elif cmd == "detect_platform":
    print(json.dumps({"platform": detect_platform()}))

  else:
    print(json.dumps({"error": "Unknown command: {}".format(cmd)}))
    sys.exit(1)
