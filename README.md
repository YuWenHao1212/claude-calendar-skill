# Claude Calendar Skill

> Part of the [Enterprise AI Breakpoint Framework](https://github.com/YuWenHao1212?tab=repositories&q=bp&type=&language=&sort=) — 9 universal patterns for AI-powered enterprise workflows.

Let Claude scan your calendar for availability, create events, generate .ics invites, and send meeting notifications — all in one conversation.

**Mac + Windows supported. Google Calendar + Outlook + iCloud supported.**

## Prerequisites

Install [claude-email-skill](https://github.com/YuWenHao1212/claude-email-skill) first — this skill uses it to send meeting notifications.

## Install

> **若已安裝過 calendar skill**：先備份舊版 `mv ~/.claude/skills/calendar ~/.claude/skills/calendar.bak.$(date +%s)`

```bash
git clone https://github.com/YuWenHao1212/claude-calendar-skill.git /tmp/claude-calendar-skill && rm -rf ~/.claude/skills/calendar && mkdir -p ~/.claude/skills && cp -r /tmp/claude-calendar-skill/calendar ~/.claude/skills/calendar
```

## Setup

Open Claude Code and say:

> "建一個會議"

Claude will auto-detect your platform and guide you through setup:
- **Mac**: Which calendar to read from (Apple Calendar)
- **Windows**: Your .ics subscription URL (Google/Outlook/iCloud)
- **Optional**: Your default meeting link (Meet/Zoom/Teams)

## What It Can Do

| Feature | Mac | Windows |
|---------|-----|---------|
| Scan calendar & find availability | ✅ Apple Calendar | ✅ .ics URL |
| Suggest meeting times | ✅ | ✅ |
| Create events locally | ✅ Apple Calendar | ⚠️ .ics export → manual import |
| Generate .ics invites | ✅ | ✅ |
| Send meeting notifications + .ics | ✅ via email skill | ✅ via email skill |
| Discuss & write agenda | ✅ | ✅ |

## One-Sentence Workflow

> "Schedule a meeting with Peggy next Tuesday to discuss May courses."

Claude will:
1. Check your calendar for Tuesday availability
2. Help you write an agenda
3. Create the event in your calendar
4. Draft a notification email with .ics attached
5. You review and hit send

## Security

| Rule | How it's enforced |
|------|-------------------|
| Never sends invites automatically | All notifications go to Drafts folder (code-level, via email skill) |
| Never adds attendees to calendar | Only generates .ics for recipients to import themselves |
| Protects .ics URL | Skill instructs Claude not to display subscription URLs |

## Enterprise AI Breakpoint Framework

| BP | Pattern | Repo |
|----|---------|------|
| 1 | Email Workflow | [claude-email-skill](https://github.com/YuWenHao1212/claude-email-skill) |
| **2** | **Calendar & Meeting** | **this repo** |
| 3 | Cross-source Data Consolidation | Gamma only |
| 7 | Document Comparison | Gamma only |
| More coming soon... | | |

## License

MIT
