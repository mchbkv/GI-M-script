![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
# 📅 Telegram Scheduled Message Userbot

A lightweight Telegram userbot built with [Pyrogram](https://docs.pyrogram.org/) that lets you **bulk-schedule messages** and **clear all scheduled messages** in any chat — directly from your own account.

---

## ✨ Features

| Command | Description |
|---|---|
| `.send <interval> <count>` | Schedules `count` copies of the replied-to message at the given interval |
| `.update` | Clears current scheduled messages and recreates the last saved `.send` schedule in the current chat/topic |
| `.clear` | Deletes **all** scheduled messages in the current chat |

- 💎 **Perfect formatting retention:** Copies complex entities (Quotes, custom Dates, Premium emojis) flawlessly using Telegram's server-side Forward API.
- 🖼️ Supports text, single media, and **media group** (album) messages.
- 🔁 Remembers the last `.send` settings per chat/topic and can refresh them with `.update`.
- ♻️ Can auto-clear old scheduled messages, fill the schedule up to Telegram's limit, and auto-refresh empty schedules.
- 🛡️ Automatically pauses every 20 messages to avoid Telegram flood-wait limits.
- 🛑 Stops gracefully when Telegram's 100-message schedule limit is reached.
- 📝 All status reports are sent privately to your **Saved Messages** (`me`).

---

## ⚙️ Requirements

- Python **3.10+** (Includes a manual event-loop fix for full **Python 3.14** compatibility).
- A Telegram account with API credentials from [my.telegram.org](https://my.telegram.org).

---

## 🚀 Setup

### 1. Clone the repository

```bash
git clone https://github.com/mchbkv/GI-M-script.git
cd GI-M-script
```
### 2. Create a virtual environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```
### 3. Install dependencies
```bash
pip install -r requirements.txt
```
> **Note:** `TgCrypto` is optional but strongly recommended — it significantly speeds up Pyrogram's encryption.

### 4. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
API_ID=your_api_id
API_HASH=your_api_hash
```

Get your `API_ID` and `API_HASH` from [my.telegram.org → App configuration](https://my.telegram.org/apps).

### 5. Run the userbot

```bash
python script.py
```

On first launch, Pyrogram will ask you to log in with your phone number and a one-time code from Telegram. A session file (`my_account.session`) will be created automatically and reused on subsequent runs.

---

## 📖 Usage

### `.send <interval> <count>`

Reply to any message and run this command to schedule `count` copies of it at the specified interval.

**Interval format:** combine `d` (days), `h` (hours), `m` (minutes).

```
.send 1h 5          → 5 messages, one per hour
.send 30m 10        → 10 messages, every 30 minutes
.send 1d 3          → 3 messages, one per day
.send 2h30m 4       → 4 messages, every 2 hours 30 minutes
```

Progress updates are sent to your **Saved Messages**. By default, `.send` first clears old scheduled messages in the same chat/topic and fills the schedule up to Telegram's 100 scheduled-message limit.

The latest `.send` settings are saved locally in `schedule_state.json` so `.update` and auto-refresh can reuse the same message, interval, and count later. This file is ignored by Git.

---

### `.update`

Run in a chat or forum topic where `.send` was used before. The command deletes current scheduled messages in that chat, then schedules the saved message again from the current moment using the saved interval and count.

```
.update
```

If Telegram returns an error during update, the script sends manual scheduling details to your **Saved Messages**: the message link or id, full chat/topic name, interval, count, and error text.

When `AUTO_REFRESH_ENABLED` is enabled in `script.py`, the userbot periodically checks saved schedules. If a saved chat/topic has no scheduled messages left, it recreates the schedule automatically. If Telegram reports that sending is forbidden in a chat, auto-refresh is disabled for that chat/topic.

---

### `.clear`

Run in any chat to immediately delete scheduled messages in that chat/topic and disable the saved auto-refresh settings for it.

```
.clear
```

If `.clear` is run outside a forum topic, it removes saved auto-refresh settings for the whole chat.

---

## 🔧 Automation Settings

These toggles are available near the top of `script.py`:

```python
AUTO_CLEAR_BEFORE_SEND = True
AUTO_FILL_TO_LIMIT = True
AUTO_REFRESH_ENABLED = True
AUTO_REFRESH_INTERVAL_SECONDS = 300
```

`AUTO_CLEAR_BEFORE_SEND` clears old scheduled messages before each `.send`.
`AUTO_FILL_TO_LIMIT` schedules as many batches as Telegram's 100 scheduled-message limit allows.
`AUTO_REFRESH_ENABLED` keeps saved schedules alive when their scheduled queue becomes empty.

---

## 🔒 Security Notes

- **Never commit your `.env` file.** It contains sensitive API credentials. It is excluded by `.gitignore`.
- **Never share your `.session` file.** It provides full access to your Telegram account. It is also excluded by `.gitignore`.
- This script runs as a **userbot** (on your personal account), not a bot account. Use responsibly and in accordance with [Telegram's Terms of Service](https://telegram.org/tos).

---

## 🛠 Troubleshooting

| Problem | Solution |
|---|---|
| `RuntimeError: There is no current event loop` | Make sure you are using **Python 3.10+**. The script handles this automatically for Windows. |
| `TgCrypto is missing` warning | Install it with `pip install TgCrypto` for better performance (optional). |
| `SCHEDULE_TOO_MUCH` error | Telegram allows max **100 scheduled messages** per chat. The script will stop and notify you. |
| Session expired / login required | Delete `my_account.session` and re-run the script to log in again. |

---
## 🐛 Feedback & Issues
Found a bug or have a feature request? Please open an issue in the [Issues tab](https://github.com/mchbkv/GI-M-script/issues).

## 📄 License

This project is released under the [MIT License](LICENSE).
