# Calendar 工作流 — 測試指令

設定完成後，依序執行以下指令驗證功能。

> Mac 用 `python3`，Windows 用 `python`。

## Step 1：偵測平台

```bash
python3 calendar_ops.py detect_platform
```

預期：`{"platform": "mac"}` 或 `{"platform": "windows"}`

## Step 2：讀取事件

```bash
python3 calendar_ops.py read_events 7
```

預期：列出未來 7 天的行事曆事件（JSON 格式）。

如果回傳空陣列 `[]`，可能是：
- 日曆名稱不對（Mac）→ 打開行事曆 app 確認名稱
- .ics URL 不對（Windows）→ 確認 URL 可以在瀏覽器開啟

## Step 3：找空檔

```bash
python3 calendar_ops.py find_slots 7 60
```

預期：列出未來 7 天工作時間（9:00-18:00）內的 60 分鐘空檔。

## Step 4：建測試事件（Mac only）

```bash
python3 calendar_ops.py create_event "測試事件" "2026-04-08 14:00" "2026-04-08 15:00" "這是測試，可以刪除"
```

去行事曆 app 確認事件有出現。測試後手動刪除。

## Step 5：產 .ics 檔

```bash
python3 calendar_ops.py generate_ics "Q2 課程討論" "2026-04-08T14:00:00+08:00" "2026-04-08T15:00:00+08:00" "you@email.com" "colleague@email.com" "議題：1. 五月排程 2. 講師確認"
```

預期：產出 `/tmp/invite-xxx.ics`。雙擊確認能開啟。

## 常見錯誤

| 錯誤 | 原因 | 解法 |
|------|------|------|
| `env.md not found` | 未完成設定 | 說「設定行事曆」讓 Claude 引導 |
| `calendar not found`（Mac） | 日曆名稱不對 | 打開行事曆 app 確認側欄名稱 |
| `Failed to fetch .ics URL`（Windows） | URL 不對或過期 | 重新取得 .ics URL |
| `osascript timed out`（Mac） | 行事曆 app 沒開或權限問題 | 先手動開一次行事曆 app |
| 空事件列表 | 該日期範圍沒有事件 | 正常，嘗試更大的天數範圍 |
