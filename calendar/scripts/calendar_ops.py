#!/usr/bin/env python3
"""
Calendar operations for Claude Code — Mac (osascript/JXA) & Windows/Linux (.ics URL).
Reads config from env.md in the skill directory.

Features:
  - Read calendar events (Mac: Apple Calendar, Windows/Linux: .ics URL)
  - Find available time slots
  - Create events (Mac: Apple Calendar, Others: export .ics)
  - Generate .ics invite files (cross-platform, RFC 5545 compliant)
"""

import sys
import os
import json
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, "env.md")


# --- Config ---

def load_env():
  """Load key: value pairs from env.md."""
  env = {}
  if not os.path.exists(ENV_FILE):
    print(json.dumps({"error": f"env.md not found at {ENV_FILE}. Run setup first."}))
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
  """Parse int safely, return default on failure."""
  try:
    return int(val)
  except (ValueError, TypeError):
    return default


# --- Mac: JXA (JavaScript for Automation) ---

def read_events_jxa(calendar_name, days):
  """Read events from Apple Calendar using JXA (returns ISO dates, no locale issues)."""
  script = f'''
  const Calendar = Application("Calendar");
  const calName = "{calendar_name.replace('"', '\\"')}";
  const cal = Calendar.calendars.whose({{name: calName}})[0];
  const now = new Date();
  const end = new Date(now.getTime() + {days} * 86400000);
  const events = cal.events.whose({{
    _and: [
      {{startDate: {{_greaterThan: now}}}},
      {{startDate: {{_lessThan: end}}}}
    ]
  }})();
  const result = events.map(e => ({{
    summary: e.summary(),
    start: e.startDate().toISOString(),
    end: e.endDate().toISOString(),
    description: e.description() || "",
    location: e.location() || ""
  }}));
  JSON.stringify(result);
  '''
  try:
    result = subprocess.run(
      ["osascript", "-l", "JavaScript", "-e", script],
      capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    output = result.stdout.strip()
    if not output:
      return []
    events = json.loads(output)
    # Normalize ISO dates to readable format
    for e in events:
      for field in ("start", "end"):
        if e.get(field):
          try:
            dt = datetime.fromisoformat(e[field].replace("Z", "+00:00"))
            e[field] = dt.strftime("%Y-%m-%d %H:%M")
          except (ValueError, AttributeError):
            pass
    return events
  except subprocess.TimeoutExpired:
    return {"error": "osascript timed out"}
  except json.JSONDecodeError as ex:
    return {"error": f"Failed to parse JXA output: {ex}"}
  except Exception as e:
    return {"error": str(e)}


def create_event_jxa(calendar_name, summary, start_iso, end_iso, description="", location=""):
  """Create event in Apple Calendar using JXA (safe, no string injection)."""
  # Pass data as JSON env var to avoid any injection
  event_data = json.dumps({
    "calendarName": calendar_name,
    "summary": summary,
    "start": start_iso,
    "end": end_iso,
    "description": description,
    "location": location,
  })
  script = '''
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
  try:
    env = os.environ.copy()
    env["EVENT_DATA"] = event_data
    result = subprocess.run(
      ["osascript", "-l", "JavaScript", "-e", script],
      capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    return json.loads(result.stdout.strip()) if result.stdout.strip() else {"status": "created", "summary": summary}
  except Exception as e:
    return {"error": str(e)}


# --- Windows/Linux: .ics URL ---

def validate_ics_url(url):
  """Validate .ics URL scheme to prevent SSRF."""
  if not url.startswith("https://") and not url.startswith("http://"):
    return False
  return True


def read_events_ics_url(ics_url, days):
  """Read events from .ics URL, parse VEVENT blocks."""
  if not validate_ics_url(ics_url):
    return {"error": f"Invalid .ics URL scheme. Must start with https:// or http://"}

  import urllib.request
  try:
    data = urllib.request.urlopen(ics_url, timeout=30).read().decode("utf-8", errors="replace")
  except Exception as e:
    return {"error": f"Failed to fetch .ics URL: {e}"}

  now = datetime.now(timezone.utc)
  end_date = now + timedelta(days=days)
  events = []

  # Split into VEVENT blocks
  vevent_pattern = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL)
  for match in vevent_pattern.finditer(data):
    block = match.group(1)
    # Unfold continuation lines (RFC 5545: lines starting with space/tab are continuations)
    block = re.sub(r"\r?\n[ \t]", "", block)

    event = {}
    for field, key in [("SUMMARY", "summary"), ("DTSTART", "start"), ("DTEND", "end"),
                       ("DESCRIPTION", "description"), ("LOCATION", "location")]:
      m = re.search(rf"^{field}[^:]*:(.+)$", block, re.MULTILINE)
      if m:
        event[key] = m.group(1).strip()
      else:
        event[key] = ""

    # Parse start date for filtering
    start_raw = event.get("start", "")
    try:
      dt = parse_ics_datetime(start_raw)
      if dt and now <= dt <= end_date:
        event["start"] = dt.strftime("%Y-%m-%d %H:%M")
        end_raw = event.get("end", "")
        if end_raw:
          dt_end = parse_ics_datetime(end_raw)
          if dt_end:
            event["end"] = dt_end.strftime("%Y-%m-%d %H:%M")
        # Unescape .ics description
        event["description"] = event.get("description", "").replace("\\n", "\n").replace("\\,", ",")
        events.append(event)
    except (ValueError, TypeError):
      continue

  events.sort(key=lambda e: e.get("start", ""))
  return events


def parse_ics_datetime(raw):
  """Parse iCalendar datetime formats to timezone-aware datetime."""
  if not raw:
    return None
  raw = raw.strip()
  try:
    if raw.endswith("Z"):
      return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    elif "T" in raw:
      return datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    else:
      # All-day event: treat as start of day
      return datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
  except ValueError:
    return None


# --- Cross-platform ---

def find_slots(events, days=7, duration_min=60, work_start=9, work_end=18):
  """Find available slots from event list. Work hours 9:00-18:00, skip weekends."""
  if isinstance(events, dict) and "error" in events:
    return events

  now = datetime.now()
  slots = []

  for day_offset in range(days):
    day = now.date() + timedelta(days=day_offset)
    if day.weekday() >= 5:  # Skip weekends
      continue

    day_start = datetime.combine(day, datetime.min.time().replace(hour=work_start))
    day_end = datetime.combine(day, datetime.min.time().replace(hour=work_end))

    if day == now.date():
      day_start = max(day_start, now.replace(second=0, microsecond=0))

    # Get events for this day
    day_events = []
    for e in events:
      e_start = e.get("start", "")
      if isinstance(e_start, str) and day.strftime("%Y-%m-%d") in e_start:
        day_events.append(e)

    # Parse and sort busy times
    busy = []
    for e in day_events:
      try:
        s = datetime.strptime(e["start"], "%Y-%m-%d %H:%M")
        end_str = e.get("end", "")
        if end_str:
          en = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
        else:
          en = s + timedelta(hours=1)
        busy.append((s, en))
      except (ValueError, KeyError):
        continue
    busy.sort()

    # Find gaps
    cursor = day_start
    for b_start, b_end in busy:
      if cursor + timedelta(minutes=duration_min) <= b_start:
        slots.append({
          "date": day.strftime("%Y-%m-%d"),
          "weekday": day.strftime("%A"),
          "start": cursor.strftime("%H:%M"),
          "end": b_start.strftime("%H:%M"),
          "duration_min": int((b_start - cursor).total_seconds() / 60),
        })
      cursor = max(cursor, b_end)
    if cursor + timedelta(minutes=duration_min) <= day_end:
      slots.append({
        "date": day.strftime("%Y-%m-%d"),
        "weekday": day.strftime("%A"),
        "start": cursor.strftime("%H:%M"),
        "end": day_end.strftime("%H:%M"),
        "duration_min": int((day_end - cursor).total_seconds() / 60),
      })

  return slots


def fold_ics_line(line):
  """Fold long lines per RFC 5545 (max 75 octets per line)."""
  encoded = line.encode("utf-8")
  if len(encoded) <= 75:
    return line
  result = []
  while len(encoded) > 75:
    # Find a safe split point (don't split multi-byte chars)
    cut = 75 if not result else 74  # first line 75, continuation 74 (after space)
    while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
      cut -= 1
    if result:
      result.append(" " + encoded[:cut].decode("utf-8"))
    else:
      result.append(encoded[:cut].decode("utf-8"))
    encoded = encoded[cut:]
  if encoded:
    if result:
      result.append(" " + encoded.decode("utf-8"))
    else:
      result.append(encoded.decode("utf-8"))
  return "\r\n".join(result)


def generate_ics(summary, start, end, organizer, attendees,
                 description="", meet_url=None, uid=None):
  """Generate .ics calendar invite content (RFC 5545 compliant).
  start/end: ISO 8601 with timezone (e.g. 2026-04-08T14:00:00+08:00)
  attendees: comma-separated emails
  Returns: ics content string
  """
  uid = uid or f"{int(time.time())}-{os.getpid()}@calendar-skill"

  def to_ical_utc(iso_str):
    clean = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', iso_str)
    try:
      d = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
      d = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
      d = d.replace(tzinfo=timezone.utc)
    utc = d.astimezone(timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")

  dtstart = to_ical_utc(start)
  dtend = to_ical_utc(end)
  now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

  lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//bp2-calendar//calendar_ops//EN",
    "METHOD:REQUEST",
    "BEGIN:VEVENT",
    f"UID:{uid}",
    f"DTSTART:{dtstart}",
    f"DTEND:{dtend}",
    f"DTSTAMP:{now}",
    f"ORGANIZER;CN=Organizer:mailto:{organizer}",
    f"SUMMARY:{summary}",
  ]
  if description:
    desc_escaped = description.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,")
    lines.append(f"DESCRIPTION:{desc_escaped}")
  for addr in attendees.split(","):
    addr = addr.strip()
    if addr:
      lines.append(f"ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{addr}")
  if meet_url:
    lines.append(f"LOCATION:{meet_url}")
  lines.append("STATUS:CONFIRMED")
  lines.append("SEQUENCE:0")
  lines.append("END:VEVENT")
  lines.append("END:VCALENDAR")

  # Apply RFC 5545 line folding
  folded = [fold_ics_line(line) for line in lines]
  return "\r\n".join(folded)


def safe_output_path(requested_path):
  """Validate output path — restrict to /tmp or skill directory."""
  if not requested_path:
    return os.path.join("/tmp", f"invite-{int(time.time())}-{os.getpid()}.ics")
  resolved = os.path.realpath(requested_path)
  allowed = ["/tmp", os.path.realpath(SKILL_DIR)]
  if not any(resolved.startswith(d) for d in allowed):
    return os.path.join("/tmp", os.path.basename(resolved))
  return resolved


# --- Commands ---

def cmd_read_events(days=7):
  """Read calendar events. Mac: JXA, Others: .ics URL."""
  try:
    env = load_env()
    platform = env.get("platform", detect_platform())

    if platform == "mac":
      calendar_name = env.get("calendar_name", "Calendar")
      events = read_events_jxa(calendar_name, days)
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
      calendar_name = env.get("calendar_name", "Calendar")
      events = read_events_jxa(calendar_name, days)
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
  """Create event. Mac: Apple Calendar, Others: export .ics file."""
  try:
    env = load_env()
    platform = env.get("platform", detect_platform())

    if platform == "mac":
      calendar_name = env.get("calendar_name", "Calendar")
      result = create_event_jxa(calendar_name, summary, start, end, description, location)
    else:
      organizer = env.get("organizer_email", "user@example.com")
      ics_content = generate_ics(summary, start, end, organizer, "", description, location)
      output_path = safe_output_path(None)
      with open(output_path, "w") as f:
        f.write(ics_content)
      result = {"status": "created", "method": "ics_file", "path": output_path,
                "message": "Double-click the .ics file to import into your calendar."}

    print(json.dumps(result, indent=2, ensure_ascii=False))
  except Exception as e:
    print(json.dumps({"error": str(e)}))


def cmd_generate_ics(summary, start, end, organizer, attendees,
                     description="", meet_url=None, output_path=None):
  """Generate .ics invite file for email attachment."""
  try:
    env = load_env()
    if not meet_url:
      meet_url = env.get("meet_url", "")

    ics_content = generate_ics(summary, start, end, organizer, attendees, description, meet_url)
    output_path = safe_output_path(output_path)

    with open(output_path, "w") as f:
      f.write(ics_content)

    print(json.dumps({"status": "ok", "path": output_path}, ensure_ascii=False))
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
    days = safe_int(sys.argv[2] if len(sys.argv) > 2 else None, 7)
    cmd_read_events(days)

  elif cmd == "find_slots":
    days = safe_int(sys.argv[2] if len(sys.argv) > 2 else None, 7)
    duration = safe_int(sys.argv[3] if len(sys.argv) > 3 else None, 60)
    cmd_find_slots(days, duration)

  elif cmd == "create_event":
    if len(sys.argv) < 5:
      print(json.dumps({"error": "Usage: create_event <summary> <start> <end> [description] [location]"}))
      sys.exit(1)
    summary = sys.argv[2]
    start = sys.argv[3]
    end = sys.argv[4]
    description = sys.argv[5] if len(sys.argv) > 5 else ""
    location = sys.argv[6] if len(sys.argv) > 6 else ""
    cmd_create_event(summary, start, end, description, location)

  elif cmd == "generate_ics":
    if len(sys.argv) < 7:
      print(json.dumps({"error": "Usage: generate_ics <summary> <start> <end> <organizer> <attendees> [description] [meet_url] [output_path]"}))
      sys.exit(1)
    summary = sys.argv[2]
    start = sys.argv[3]
    end = sys.argv[4]
    organizer = sys.argv[5]
    attendees = sys.argv[6]
    description = sys.argv[7] if len(sys.argv) > 7 else ""
    meet_url = sys.argv[8] if len(sys.argv) > 8 else None
    output_path = sys.argv[9] if len(sys.argv) > 9 else None
    cmd_generate_ics(summary, start, end, organizer, attendees, description, meet_url, output_path)

  elif cmd == "detect_platform":
    print(json.dumps({"platform": detect_platform()}))

  else:
    print(json.dumps({"error": f"Unknown command: {cmd}"}))
    sys.exit(1)
