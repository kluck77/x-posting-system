# Recovery Playbook

Short operator guide for diagnosing and recovering system state after a restart or anomaly.

---

## Quick Check

Send `/recover` in Telegram at any time.  
Returns a live report of all four persistent state files.

---

## State Files (`data/`)

| File | What it holds | If deleted |
|------|--------------|------------|
| `post_queue.json` | Queued posts waiting for approval | Queue starts empty |
| `processed_replies.json` | X reply IDs already handled | All replies treated as new (harmless duplicates) |
| `activity.json` | Last pipeline activity timestamp | Idle reminder resets; no alerts for 48 h |
| `monitor_state.json` | Reply monitor on/off state | Monitor defaults to ON |

All files are re-created automatically on the next write. Deleting a corrupt file is always safe.

---

## Common Scenarios

### App restarted — pending news alerts lost
`_pending_articles` is in-memory only. News alerts sent before restart cannot be re-drafted via button.  
**Fix:** Use `/draft <url>` to start fresh from the article URL.

### `processed_replies.json` is corrupt
`/recover` shows ❌ for "처리된 답글 ID".  
**Fix:** Delete `data/processed_replies.json`. The monitor will re-scan and may re-surface old replies once; mark them skip.

### Post queue shows wrong count
`/queue` lists all pending posts. If `/recover` and `/queue` disagree, the queue file may be stale.  
**Fix:** Delete `data/post_queue.json`. Re-add posts with `/queue <text>`.

### Reply monitor stuck OFF after restart
`/recover` shows "답글 모니터: 정지".  
**Fix:** `/monitor on`

### No activity recorded (idle reminder fires immediately)
`activity.json` missing or empty.  
**Fix:** Run any pipeline action (`/draft`, `/queue`). This resets the clock.

---

## Startup Log

On every startup the system logs a one-line state summary:

```
[Startup] 상태 파일 점검 완료 — post_queue: N개 대기 / M개 전체, processed_replies: K개 처리 완료 ID, ...
```

If any file is corrupt:
```
[Startup] 상태 파일 손상 감지: ['post_queue'] — 해당 파일을 삭제하면 자동 재생성됩니다.
```

---

## Data Directory Permissions

If the app cannot write to `data/`, all state persistence silently fails.

```bash
ls -la data/
chmod 755 data/
```
