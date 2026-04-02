#!/usr/bin/env python3
"""Unit tests for calendar_ops.py — covers date parsing, slot calculation, security, and RFC 5545."""

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "calendar", "scripts"))
from calendar_ops import (
  safe_int, sanitize_ics_text, fold_ics_line, parse_ics_datetime,
  validate_ics_url, detect_platform, find_slots, generate_ics,
  safe_output_path, utc_to_local, TZID_OFFSETS
)


class TestSafeInt(unittest.TestCase):
  def test_valid(self):
    self.assertEqual(safe_int("5", 7), 5)
    self.assertEqual(safe_int("0", 7), 0)
    self.assertEqual(safe_int("-3", 7), -3)

  def test_invalid(self):
    self.assertEqual(safe_int("abc", 7), 7)
    self.assertEqual(safe_int(None, 7), 7)
    self.assertEqual(safe_int("", 7), 7)
    self.assertEqual(safe_int("3.5", 7), 7)


class TestSanitizeIcsText(unittest.TestCase):
  def test_strips_crlf(self):
    self.assertEqual(sanitize_ics_text("hello\r\nworld"), "hello  world")
    self.assertEqual(sanitize_ics_text("a\nb"), "a b")

  def test_strips_control_chars(self):
    self.assertEqual(sanitize_ics_text("a\x00b\x07c"), "a b c")

  def test_normal_text(self):
    self.assertEqual(sanitize_ics_text("normal text"), "normal text")
    self.assertEqual(sanitize_ics_text("中文測試"), "中文測試")

  def test_empty(self):
    self.assertEqual(sanitize_ics_text(""), "")
    self.assertEqual(sanitize_ics_text(None), "")


class TestFoldIcsLine(unittest.TestCase):
  def test_short_line(self):
    self.assertEqual(fold_ics_line("SHORT"), "SHORT")

  def test_exactly_75(self):
    line = "A" * 75
    self.assertEqual(fold_ics_line(line), line)

  def test_long_line_folds(self):
    line = "DESCRIPTION:" + "A" * 100
    folded = fold_ics_line(line)
    self.assertIn("\r\n ", folded)

  def test_multibyte_no_split(self):
    # Chinese characters are 3 bytes each in UTF-8
    line = "SUMMARY:" + "中" * 30  # 8 + 90 bytes
    folded = fold_ics_line(line)
    # Verify it can round-trip decode
    unfolded = folded.replace("\r\n ", "")
    self.assertEqual(unfolded, line)


class TestParseIcsDatetime(unittest.TestCase):
  def test_utc_z(self):
    dt = parse_ics_datetime("20260408T060000Z")
    self.assertIsNotNone(dt)
    self.assertEqual(dt.year, 2026)
    self.assertEqual(dt.month, 4)
    self.assertEqual(dt.hour, 6)
    self.assertEqual(dt.tzinfo, timezone.utc)

  def test_no_timezone(self):
    dt = parse_ics_datetime("20260408T140000")
    self.assertIsNotNone(dt)
    # Should be interpreted as local time, converted to UTC
    self.assertIsNotNone(dt.tzinfo)

  def test_with_tzid(self):
    dt = parse_ics_datetime("20260408T140000", tzid="America/New_York")
    self.assertIsNotNone(dt)
    # 14:00 EDT (UTC-5) = 19:00 UTC
    self.assertEqual(dt.hour, 19)
    self.assertEqual(dt.tzinfo, timezone.utc)

  def test_with_tzid_asia(self):
    dt = parse_ics_datetime("20260408T140000", tzid="Asia/Taipei")
    self.assertIsNotNone(dt)
    # 14:00 CST (UTC+8) = 06:00 UTC
    self.assertEqual(dt.hour, 6)

  def test_unknown_tzid_uses_local(self):
    dt = parse_ics_datetime("20260408T140000", tzid="Mars/Olympus")
    self.assertIsNotNone(dt)
    # Should still return something (uses local tz)

  def test_allday(self):
    dt = parse_ics_datetime("20260408")
    self.assertIsNotNone(dt)
    self.assertEqual(dt.year, 2026)
    self.assertEqual(dt.month, 4)
    self.assertEqual(dt.day, 8)

  def test_empty(self):
    self.assertIsNone(parse_ics_datetime(""))
    self.assertIsNone(parse_ics_datetime(None))

  def test_garbage(self):
    self.assertIsNone(parse_ics_datetime("not-a-date"))


class TestValidateIcsUrl(unittest.TestCase):
  def test_valid_https(self):
    self.assertTrue(validate_ics_url("https://calendar.google.com/ics"))

  def test_valid_http(self):
    self.assertTrue(validate_ics_url("http://example.com/cal.ics"))

  def test_file_blocked(self):
    self.assertFalse(validate_ics_url("file:///etc/passwd"))

  def test_internal_ips_blocked(self):
    self.assertFalse(validate_ics_url("http://169.254.169.254/metadata"))
    self.assertFalse(validate_ics_url("http://10.0.0.1/cal"))
    self.assertFalse(validate_ics_url("http://192.168.1.1/cal"))
    self.assertFalse(validate_ics_url("http://172.16.0.1/cal"))

  def test_localhost_blocked(self):
    self.assertFalse(validate_ics_url("http://localhost/cal"))

  def test_ipv6_loopback_blocked(self):
    self.assertFalse(validate_ics_url("http://[::1]/cal"))

  def test_empty(self):
    self.assertFalse(validate_ics_url(""))
    self.assertFalse(validate_ics_url(None))


class TestFindSlots(unittest.TestCase):
  def test_empty_events_all_free(self):
    events = []
    slots = find_slots(events, days=1, duration_min=60)
    # Should have at least one slot (if today is a weekday)
    if datetime.now().weekday() < 5:
      self.assertGreater(len(slots), 0)

  def test_full_day_no_slots(self):
    today = datetime.now().strftime("%Y-%m-%d")
    events = [{"start": "{} 09:00".format(today), "end": "{} 18:00".format(today)}]
    slots = find_slots(events, days=1, duration_min=60)
    # Today should have no slots
    today_slots = [s for s in slots if s["date"] == today]
    self.assertEqual(len(today_slots), 0)

  def test_gap_found(self):
    # Use a future weekday to avoid current-time interference
    future = datetime.now() + timedelta(days=3)
    while future.weekday() >= 5:
      future += timedelta(days=1)
    day_str = future.strftime("%Y-%m-%d")
    events = [
      {"start": "{} 09:00".format(day_str), "end": "{} 10:00".format(day_str)},
      {"start": "{} 14:00".format(day_str), "end": "{} 18:00".format(day_str)},
    ]
    slots = find_slots(events, days=7, duration_min=60)
    day_slots = [s for s in slots if s["date"] == day_str]
    # Should find 10:00-14:00 gap
    found = any(s["start"] == "10:00" for s in day_slots)
    self.assertTrue(found, "Expected 10:00 slot in {}".format(day_slots))

  def test_error_passthrough(self):
    result = find_slots({"error": "test error"})
    self.assertIn("error", result)

  def test_weekend_skipped(self):
    # Create events spanning a full week — weekend slots should not appear
    slots = find_slots([], days=7, duration_min=60)
    for s in slots:
      d = datetime.strptime(s["date"], "%Y-%m-%d")
      self.assertLess(d.weekday(), 5, "Weekend should be skipped: {}".format(s["date"]))


class TestGenerateIcs(unittest.TestCase):
  def test_basic_output(self):
    ics = generate_ics("Test Meeting", "2026-04-08T14:00:00+08:00",
                       "2026-04-08T15:00:00+08:00", "org@test.com", "att@test.com")
    self.assertIn("BEGIN:VCALENDAR", ics)
    self.assertIn("END:VCALENDAR", ics)
    self.assertIn("Test Meeting", ics)
    self.assertIn("att@test.com", ics)

  def test_meet_url_in_location(self):
    ics = generate_ics("Test", "2026-04-08T14:00:00+08:00",
                       "2026-04-08T15:00:00+08:00", "org@test.com", "",
                       meet_url="https://meet.google.com/abc")
    self.assertIn("LOCATION:https://meet.google.com/abc", ics)

  def test_description_escaped(self):
    ics = generate_ics("Test", "2026-04-08T14:00:00+08:00",
                       "2026-04-08T15:00:00+08:00", "org@test.com", "",
                       description="Line1\nLine2, with comma")
    self.assertIn("\\n", ics)
    self.assertIn("\\,", ics)

  def test_crlf_injection_blocked(self):
    ics = generate_ics("Evil\r\nATTENDEE:hacker@evil.com", "2026-04-08T14:00:00+08:00",
                       "2026-04-08T15:00:00+08:00", "org@test.com", "")
    # CRLF should be sanitized — hacker email stays in SUMMARY line, not as separate ATTENDEE
    lines = ics.split("\r\n")
    attendee_lines = [l for l in lines if l.startswith("ATTENDEE")]
    # No injected ATTENDEE line should exist (only legitimate ones)
    for a in attendee_lines:
      self.assertNotIn("hacker@evil.com", a)

  def test_line_folding_applied(self):
    long_desc = "A" * 200
    ics = generate_ics("Test", "2026-04-08T14:00:00+08:00",
                       "2026-04-08T15:00:00+08:00", "org@test.com", "",
                       description=long_desc)
    # Should contain folded lines
    self.assertIn("\r\n ", ics)


class TestSafeOutputPath(unittest.TestCase):
  def test_none_returns_none(self):
    self.assertIsNone(safe_output_path(None))

  def test_empty_returns_none(self):
    self.assertIsNone(safe_output_path(""))

  def test_tmp_allowed(self):
    result = safe_output_path("/tmp/test.ics")
    # On macOS /tmp -> /private/tmp, both should work
    self.assertIsNotNone(result)

  def test_traversal_blocked(self):
    result = safe_output_path("/etc/evil.ics")
    self.assertIsNone(result)

  def test_home_blocked(self):
    result = safe_output_path(os.path.expanduser("~/.ssh/authorized_keys"))
    self.assertIsNone(result)


class TestDetectPlatform(unittest.TestCase):
  def test_returns_valid(self):
    p = detect_platform()
    self.assertIn(p, ("mac", "linux", "windows"))


class TestTzidOffsets(unittest.TestCase):
  def test_common_timezones_present(self):
    for tz in ["Asia/Taipei", "America/New_York", "Europe/London", "Asia/Tokyo"]:
      self.assertIn(tz, TZID_OFFSETS)


if __name__ == "__main__":
  unittest.main()
