# Telegram Alert Setup Guide

**Last updated:** 2026-05-04
**Estimated time:** 10–15 minutes

---

## What You Get

Once set up, Oracle will send you real-time Telegram messages whenever it detects:

- **Pre-News Volume Anomalies** — Stocks showing unusual volume before news breaks
- **Agentic Catalyst Alerts** — Stocks with strong momentum and ideal entry timing

Each message includes scores, entry zones, stop levels, and profit targets.

---

## Step 1: Create a Telegram Bot

1. **Open Telegram** on your phone or desktop
2. **Search for** `@BotFather` (the official bot for creating bots)
3. **Start a chat** with BotFather and tap `/start`
4. **Send the command:** `/newbot`
5. **Give your bot a name** (e.g., `Oracle Alerts`)
6. **Give it a username** ending in `bot` (e.g., `oracle_alerts_bot`)
7. **Copy the bot token** BotFather gives you — it looks like this:
   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
   ```

> Save this token somewhere safe. Anyone with it can control your bot.

---

## Step 2: Get Your Chat ID

You need to tell the bot where to send messages (your Telegram account).

### Option A: Use Your Own Bot (Quickest)

1. Search for your bot in Telegram (by the username you picked)
2. Tap `/start` to open a chat
3. **Send any message** to the bot (e.g., "hello")
4. Visit this URL in your browser:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
   (Replace `<YOUR_BOT_TOKEN>` with the actual token from Step 1)
5. Look for `"chat":{"id":123456789` in the JSON response
6. **Copy that number** — that's your `chat_id`

### Option B: Use @userinfobot

1. Search for `@userinfobot` in Telegram
2. Tap `/start`
3. It will reply with your info including your `Id:` — copy that number

---

## Step 3: Add to Oracle's Environment

Open your `.env` file in the project root and add these two lines:

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
TELEGRAM_CHAT_ID=123456789
```

Replace the values with your actual token and chat ID.

> The `.env` file is already in `.gitignore` so it won't be committed.

---

## Step 4: Test It

Run this quick test from your project directory:

```bash
Set-Location "c:\Users\Husna\OneDrive\Desktop\Oracle project1"
python -c "
import asyncio
from src.services.telegram_service import send_telegram_alert
async def test():
    ok = await send_telegram_alert('Oracle Telegram test — setup successful!')
    print('Sent!' if ok else 'Failed — check your token and chat ID')
asyncio.run(test())
"
```

You should receive a message on Telegram within seconds.

### Common Issues

| Problem | Fix |
|---------|-----|
| "Telegram not configured" | Make sure `.env` is in the project root and values have no quotes |
| "Chat not found" | Double-check `chat_id` — make sure you messaged the bot first |
| "Unauthorized" | Your bot token is wrong or expired — regenerate with BotFather via `/revoke` then `/newbot` |
| No message arrives | BotFather shows your bot as running? Try `/setprivacy` → `Disable` |

---

## Step 5: How Alerts Work in Oracle

The system sends alerts from **two places** automatically — no extra setup needed beyond the env vars.

### Pre-News Volume Alerts
- **When:** Every 15 minutes during the scan loop
- **What triggers it:** EXTREME suspicion score anomalies (score ≥ 90) with strong volume patterns
- **Cooldown:** 30 minutes per ticker — won't spam you for the same stock
- **Format example:**
  ```
  🚨 AAPL | Pre-News Volume Anomaly | Score: 88/100
  RVOL: 4.2x | Volume Accel: +180% | VWAP: +2.1%
  Smart-money: 82/100 | Buy pressure: 71/100
  News: None detected yet
  ```

### Agentic Catalyst Alerts
- **When:** When the orchestrator pipeline finds an ideal entry setup
- **What triggers it:** Final probability ≥ 70%, ideal entry timing, no trap risk, momentum alive
- **Cooldown:** 5 minutes per ticker
- **Format example:**
  ```
  🎯 TSLA | Probability 78.5%
  Timing: IDEAL_ENTRY | Score: 85/100
  Zone $245.30–$251.20 | R:R 2.8:1
  Stop $238.50 → Target 1 $268.00
  Target 2 $275.50
  ```

---

## Step 6: Running Without Telegram

If you ever want to pause alerts **without touching code**, just rename or remove the env vars:

```bash
# In .env, comment them out:
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

The system continues scanning and tracking everything — it just won't send messages. No errors, no crashes.

---

## Optional: Add a Second Recipient

Want alerts to go to your phone **and** a teammate's?

1. Get their `chat_id` (they must message the bot first)
2. In `src/services/telegram_service.py`, change `_get_config()` to support a comma-separated list:
   ```python
   chat_ids = [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
   ```
3. Loop through all IDs in `send_telegram_alert()`

Or keep it simple — just forward the bot chat to a Telegram group once it's working.

---

## Quick Checklist

- [ ] Created bot with BotFather
- [ ] Saved the bot token
- [ ] Messaged the bot to get chat ID
- [ ] Added `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env`
- [ ] Ran the test command and received a message
- [ ] Started Oracle backend — alerts now flow automatically

---

*Setup complete. Oracle will now text you whenever it spots actionable setups.*
