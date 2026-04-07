---
name: calendar
description: Calendar assistant — scan availability, create events, generate .ics invites, send meeting notifications via email. Supports Mac (Apple Calendar) and Windows (.ics URL). This skill should be used when the user wants to create meetings, check availability, schedule events, or send meeting invitations. Triggers on "建會議", "排會議", "會議邀請", "create meeting", "schedule meeting", "我下週有空嗎", "find available time", or any calendar/meeting-related request.
---

# 行事曆工作流

## 前置條件

此 skill 依賴 email skill（用來寄會議通知信）。
確認 `~/.claude/skills/email/env.md` 存在。如果不存在，告訴使用者先安裝 email skill。

## 環境設定

讀取同目錄下的 `env.md`。如果存在，跳到「工具指令」開始工作。
如果不存在，執行下方的「首次設定」。

---

## 首次設定（僅在 env.md 不存在時執行）

### Step 1：確認 Python 和 calendar_ops.py

確認 `python3 --version`（或 `python --version`）。
calendar_ops.py 在此 SKILL.md 同目錄下的 `scripts/calendar_ops.py`。

### Step 2：確認 email skill

檢查 `~/.claude/skills/email/env.md` 是否存在。
如果不存在，告訴使用者：「需要先安裝 email skill。請參考 github.com/YuWenHao1212/claude-email-skill」

### Step 3：偵測平台

執行 `{python} {calendar_ops_path} detect_platform`。

### Step 4：平台設定

**Mac：**
- 問使用者：「你的行事曆 app 裡，工作用的日曆叫什麼名字？」
  （打開行事曆 app，左邊側欄的日曆名稱，例如「工作」「iCloud」）
- 測試：`{python} {calendar_ops_path} read_events 7`
- 確認能讀到事件

**Windows：**
- 引導使用者取得 .ics 訂閱 URL：
  - Google Calendar：設定 → 日曆設定 → 「ICAL 格式的祕密地址」
  - Outlook：設定 → 共享行事曆 → ICS 連結
  - iCloud（網頁版）：分享日曆 → 公開日曆 → 複製 URL
- **安全規則：.ics URL 可能包含私密 token，不要在對話中顯示完整 URL。引導使用者自己貼到 env.md。**
- 測試：`{python} {calendar_ops_path} read_events 7`

### Step 5：會議連結（可選）

問使用者：「你有固定的線上會議連結嗎？（Google Meet / Zoom / Teams）」
如果有，記下來。沒有也沒關係。

### Step 6：產出 env.md

在此 SKILL.md 同目錄下建立 `env.md`：

Mac 版：
```
python: {python 指令}
calendar_ops: {calendar_ops.py 絕對路徑}
platform: mac
calendar_name: {日曆名稱}
meet_url: {會議連結，可選}
```

Windows 版：
```
python: {python 指令}
calendar_ops: {calendar_ops.py 絕對路徑}
platform: windows
ics_url: {.ics 訂閱 URL}
meet_url: {會議連結，可選}
```

完成後讀取 email skill 的 env.md，記下 email_ops 路徑和帳號。

告訴使用者：「行事曆設定完成。說『建一個會議』或『我下週有空嗎』就能開始。」

---

## 工具指令

讀取 `env.md` 取得 python、calendar_ops 路徑。
讀取 `~/.claude/skills/email/env.md` 取得 email_ops 路徑和帳號。

### 指令速查

| 指令 | 用途 |
|------|------|
| `read_events [days]` | 讀未來 N 天事件（預設 7） |
| `find_slots [days] [duration_min]` | 找空檔時段（預設 7 天、60 分鐘） |
| `create_event "標題" "開始" "結束" ["描述"] ["地點"]` | 建事件到本地行事曆 |
| `generate_ics "標題" "開始" "結束" "organizer" "attendees" ["描述"] ["meet_url"] ["output_path"]` | 產 .ics 邀請檔 |
| `detect_platform` | 偵測 Mac 或 Windows |

## 安全規則

- **不自動寄邀請**：所有通知信先存草稿匣，使用者確認後寄出
- **不洩漏 .ics URL**：Windows 的 .ics 訂閱 URL 可能含私密 token
- **不自動加 attendee 到 Calendar**：只產 .ics 附件讓收件人自己加入

## 工作流程

### 建會議（完整流程）

使用者說「建一個會議」或「排一個會議」時：

1. **確認基本資訊**
   - 什麼主題？
   - 跟誰開？（名字 + email）
   - 什麼時候？多久？

2. **如果使用者不確定時間**
   - `{python} {calendar_ops} read_events 7` → 列出未來一週事件
   - `{python} {calendar_ops} find_slots 7 60` → 找空檔
   - 建議 2-3 個空檔時段讓使用者選

3. **討論 Agenda**
   - 根據主題和與會者產 agenda 大綱
   - 使用者確認 / 修改

4. **三件事同時產出**
   a. `{python} {calendar_ops} create_event` → 建事件到本地行事曆（自己的提醒）
   b. `{python} {calendar_ops} generate_ics` → 產 .ics（LOCATION 放會議連結，DESCRIPTION 放純文字 agenda）
   c. `{python} {email_ops} draft {account} "{to}" "{subject}" "{html_body}" --html --attach {ics_path}` → 通知信（HTML 完整 agenda）+ 附 .ics

5. **回報**
   - ✅ 行事曆事件已建立
   - ✅ 通知信草稿已存（含 .ics + Agenda）
   - 請到草稿匣確認後寄出

### 查行程 / 找空檔

使用者問「我下週有空嗎」或「找一個大家都有空的時間」時：

1. `{python} {calendar_ops} read_events 7`
2. 列出未來一週所有事件
3. `{python} {calendar_ops} find_slots 7 60`
4. 列出空檔時段

### 寄會議通知（不建事件）

使用者只想寄通知不建事件時：

1. 確認資訊（主題、時間、與會者）
2. `{python} {calendar_ops} generate_ics` → 產 .ics
3. `{python} {email_ops} draft --html --attach` → 通知信 + .ics
4. 使用者確認後寄出
