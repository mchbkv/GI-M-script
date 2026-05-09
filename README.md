# 📅 Telegram Scheduled Message Userbot

A lightweight Telegram userbot built with [Pyrogram](https://docs.pyrogram.org/) that lets you **bulk-schedule messages** and **clear all scheduled messages** in any chat — directly from your own account.

---

## ✨ Features

| Command | Description |
|---|---|
| `.send <interval> <count>` | Schedules `count` copies of the replied-to message at the given interval |
| `.clear` | Deletes **all** scheduled messages in the current chat |

- Supports text, media, and **media group** (album) messages
- Automatically pauses every 20 messages to avoid Telegram flood-wait
- Stops gracefully when Telegram's 100-message schedule limit is reached
- All status reports are sent privately to **Saved Messages**

---

## ⚙️ Requirements

- Python **3.10+**
- A Telegram account with API credentials from [my.telegram.org](https://my.telegram.org)

---

## 🚀 Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/gi-m-script.git
cd gi-m-script
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

Progress updates are sent to your **Saved Messages**.

---

### `.clear`

Run in any chat to immediately delete **all** scheduled messages in that chat.

```
.clear
```

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

## 📄 License

This project is released under the [MIT License](LICENSE).
