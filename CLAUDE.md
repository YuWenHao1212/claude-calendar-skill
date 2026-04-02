# BP2 Calendar Skill — 安裝指南

這個 repo 是 calendar skill 的安裝源。

## 前置條件

需要先安裝 BP1 email skill：https://github.com/YuWenHao1212/bp1-email

## 安裝

當使用者說「安裝 calendar skill」、「install calendar」或任何安裝相關的請求時：

1. 確認 BP1 email skill 已安裝：
   ```bash
   ls ~/.claude/skills/email/env.md
   ```
   如果不存在，告訴使用者先安裝 BP1 email skill。

2. 把本 repo 下的 `calendar/` 資料夾整個複製到 `~/.claude/skills/calendar/`：
   ```bash
   cp -r calendar/ ~/.claude/skills/calendar/
   ```

3. 確認複製成功：
   ```bash
   ls ~/.claude/skills/calendar/SKILL.md
   ```

4. 告訴使用者：
   ```
   Calendar skill 已安裝完成。

   接下來說「建一個會議」或「我下週有空嗎」，
   第一次使用時我會引導你完成行事曆設定。
   ```

## 注意

- 如果 `~/.claude/skills/calendar/` 已存在，詢問使用者是否要覆蓋
- 安裝完成後，這個 repo 資料夾可以刪除
- Skill 安裝到全域（`~/.claude/skills/`），在任何目錄都能使用
- 此 skill 依賴 BP1 email skill（寄會議通知用）
