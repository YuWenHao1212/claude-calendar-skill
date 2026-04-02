#!/usr/bin/env python3
"""
Calendar operations for Claude Code — Mac (osascript) & Windows (.ics URL).
Reads config from env.md in the skill directory.

Features:
  - Read calendar events (Mac: Apple Calendar, Windows: .ics URL)
  - Find available time slots
  - Create events (Mac: Apple Calendar, Windows: export .ics)
  - Generate .ics invite files (cross-platform)
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
  """Detect Mac or Windows."""
  if sys.platform == "darwin":
    return "mac"
  return "windows"


# --- Mac: osascript ---

def read_events_osascript(calendar_name, days):
  """Read events from Apple Calendar using osascript."""
  script = f'''
  set startDate to current date
  set endDate to startDate + ({days} * days)
  set output to ""
  tell application "Calendar"
    set targetCal to first calendar whose name is "{calendar_name}"
    set eventList to (every event of targetCal whose start date >= startDate and start date <= endDate)
    repeat with e in eventList
      set eSummary to summary of e
      set eStart to start date of e
      set eEnd to end date of e
      set eDesc to ""
      try
        set eDesc to description of e
      end try
      set eLoc to ""
      try
        set eLoc to location of e
      end try
      set output to output & eSummary & "|||" & (eStart as string) & "|||" & (eEnd as string) & "|||" & eDesc & "|||" & eLoc & "\\n"
    end repeat
  end tell
  return output
  '''
  try:
    result = subprocess.run(
      ["osascript", "-e", script],
      capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    events = []
    for line in result.stdout.strip().split("\n"):
      if "|||" in line:
        parts = line.split("|||")
        if len(parts) >= 3:
          events.append({
            "summary": parts[0].strip(),
            "start": parts[1].strip(),
            "end": parts[2].strip(),
            "description": parts[3].strip() if len(parts) > 3 else "",
            "location": parts[4].strip() if len(parts) > 4 else "",
          })
    return events
  except subprocess.TimeoutExpired:
    return {"error": "osascript timed out"}
  except Exception as e:
    return {"error": str(e)}


def create_event_osascript(calendar_name, summary, start_str, end_str, description="", location=""):
  """Create event in Apple Calendar using osascript."""
  # Escape quotes in strings
  summary = summary.replace('"', '\\"')
  description = description.replace('"', '\\"')
  location = location.replace('"', '\\"')

  script = f'''
  tell application "Calendar"
    set targetCal to first calendar whose name is "{calendar_name}"
    set startDate to date "{start_str}"
    set endDate to date "{end_str}"
    set newEvent to make new event at end of events of targetCal with properties {{summary:"{summary}", start date:startDate, end date:endDate, description:"{description}", location:"{location}"}}
    return summary of newEvent
  end tell
  '''
  try:
    result = subprocess.run(
      ["osascript", "-e", script],
      capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
      return {"error": result.stderr.strip()}
    return {"status": "created", "method": "osascript", "summary": summary}
  except Exception as e:
    return {"error": str(e)}


# --- Windows / Universal: .ics URL ---

def read_events_ics_url(ics_url, days):
  """Read events from .ics URL, parse VEVENT blocks."""
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
      if "T" in start_raw:
        if start_raw.endswith("Z"):
          dt = datetime.strptime(start_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
          dt = datetime.strptime(start_raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
      else:
        dt = datetime.strptime(start_raw[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
      if now <= dt <= end_date:
        event["start"] = dt.strftime("%Y-%m-%d %H:%M")
        # Parse end date
        end_raw = event.get("end", "")
        if end_raw:
          try:
            if "T" in end_raw:
              if end_raw.endswith("Z"):
                dt_end = datetime.strptime(end_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
              else:
                dt_end = datetime.strptime(end_raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
              event["end"] = dt_end.strftime("%Y-%m-%d %H:%M")
          except ValueError:
            pass
        events.append(event)
    except ValueError:
      continue

  events.sort(key=lambda e: e.get("start", ""))
  return events


# --- Cross-platform ---

def find_slots(events, days=7, duration_min=60, work_start=9, work_end=18):
  """Find available slots from event list. Work hours 9:00-18:00."""
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
      try:
        e_start = e.get("start", "")
        if isinstance(e_start, str) and day.strftime("%Y-%m-%d") in e_start:
          day_events.append(e)
      except (ValueError, TypeError):
        continue

    # Sort by start time and find gaps
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
          "start": cursor.strftime("%H:%M"),
          "end": b_start.strftime("%H:%M"),
          "duration_min": int((b_start - cursor).total_seconds() / 60),
        })
      cursor = max(cursor, b_end)
    if cursor + timedelta(minutes=duration_min) <= day_end:
      slots.append({
        "date": day.strftime("%Y-%m-%d"),
        "start": cursor.strftime("%H:%M"),
        "end": day_end.strftime("%H:%M"),
        "duration_min": int((day_end - cursor).total_seconds() / 60),
      })

  return slots


def generate_ics(summary, start, end, organizer, attendees,
                 description="", meet_url=None, uid=None):
  """Generate .ics calendar invite content (RFC 5545).
  start/end: ISO 8601 with timezone (e.g. 2026-04-08T14:00:00+08:00)
  attendees: comma-separated emails
  Returns: ics content string
  """
  uid = uid or f"{int(time.time())}@calendar-skill"

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
    # Fold long lines per RFC 5545
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
  return "\r\n".join(lines)


# --- Commands ---

def cmd_read_events(days=7):
  """Read calendar events. Mac: osascript, Windows: .ics URL."""
  env = load_env()
  platform = env.get("platform", detect_platform())

  if platform == "mac":
    calendar_name = env.get("calendar_name", "Calendar")
    events = read_events_osascript(calendar_name, days)
  else:
    ics_url = env.get("ics_url", "")
    if not ics_url:
      print(json.dumps({"error": "No ics_url in env.md. Run setup."}))
      return
    events = read_events_ics_url(ics_url, days)

  print(json.dumps(events, indent=2, ensure_ascii=False))


def cmd_find_slots(days=7, duration_min=60):
  """Find available time slots."""
  env = load_env()
  platform = env.get("platform", detect_platform())

  if platform == "mac":
    calendar_name = env.get("calendar_name", "Calendar")
    events = read_events_osascript(calendar_name, days)
  else:
    ics_url = env.get("ics_url", "")
    if not ics_url:
      print(json.dumps({"error": "No ics_url in env.md. Run setup."}))
      return
    events = read_events_ics_url(ics_url, days)

  slots = find_slots(events, days, duration_min)
  print(json.dumps(slots, indent=2, ensure_ascii=False))


def cmd_create_event(summary, start, end, description="", location=""):
  """Create event. Mac: Apple Calendar, Windows: export .ics file."""
  env = load_env()
  platform = env.get("platform", detect_platform())

  if platform == "mac":
    calendar_name = env.get("calendar_name", "Calendar")
    result = create_event_osascript(calendar_name, summary, start, end, description, location)
  else:
    # Windows: generate .ics for user to import
    organizer = env.get("organizer_email", "user@example.com")
    ics_content = generate_ics(summary, start, end, organizer, "", description, location)
    output_path = f"/tmp/event-{int(time.time())}.ics"
    with open(output_path, "w") as f:
      f.write(ics_content)
    result = {"status": "created", "method": "ics_file", "path": output_path,
              "message": "Double-click the .ics file to import into your calendar."}

  print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_generate_ics(summary, start, end, organizer, attendees,
                     description="", meet_url=None, output_path=None):
  """Generate .ics invite file for email attachment."""
  env = load_env()
  if not meet_url:
    meet_url = env.get("meet_url", "")

  ics_content = generate_ics(summary, start, end, organizer, attendees, description, meet_url)

  if not output_path:
    output_path = f"/tmp/invite-{int(time.time())}.ics"

  with open(output_path, "w") as f:
    f.write(ics_content)

  print(json.dumps({"status": "ok", "path": output_path}, ensure_ascii=False))


# --- CLI ---

if __name__ == "__main__":
  if len(sys.argv) < 2:
    print("Usage: calendar_ops.py <command> [args]")
    print("Commands: read_events, find_slots, create_event, generate_ics, detect_platform")
    sys.exit(1)

  cmd = sys.argv[1]

  if cmd == "read_events":
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    cmd_read_events(days)

  elif cmd == "find_slots":
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    cmd_find_slots(days, duration)

  elif cmd == "create_event":
    # Usage: calendar_ops.py create_event "summary" "start" "end" ["description"] ["location"]
    summary = sys.argv[2]
    start = sys.argv[3]
    end = sys.argv[4]
    description = sys.argv[5] if len(sys.argv) > 5 else ""
    location = sys.argv[6] if len(sys.argv) > 6 else ""
    cmd_create_event(summary, start, end, description, location)

  elif cmd == "generate_ics":
    # Usage: calendar_ops.py generate_ics "summary" "start" "end" "organizer" "attendees" ["description"] ["meet_url"] ["output_path"]
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
    print(f"Unknown command: {cmd}")
    sys.exit(1)
