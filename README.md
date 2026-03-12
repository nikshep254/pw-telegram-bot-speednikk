# 🎓 Physics Wallah Telegram Bot

Extract your Physics Wallah batch content, browse videos inline, and download full course JSON — deployed on **Railway** for free.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔐 OTP Login | Login with your PW mobile number + OTP |
| 📦 Batch Browser | Browse all enrolled batches inline |
| 📚 Subject/Topic Nav | Navigate subjects → topics → videos via inline keyboard |
| ▶️ Video URL | Auto-resolves YouTube, Brightcove HLS, or direct CDN links |
| 📥 JSON Export | Export one batch or ALL batches to structured JSON |
| 🚀 Railway Deploy | No credit card, free tier, persistent worker |

---

## 🚀 Deploy on Railway (free)

### 1. Create the bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. `/newbot` → give it a name and username
3. Copy the **API token**

### 2. Deploy to Railway
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. **New Project → Deploy from GitHub repo** (push this repo to GitHub first)
3. Railway auto-detects `nixpacks.toml` — no extra config needed
4. Add environment variable:
   ```
   TELEGRAM_BOT_TOKEN = <your bot token from BotFather>
   ```
5. Deploy! The worker starts automatically.

### 3. Manual local run
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your_token_here"
python bot.py
```

---

## 📖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Login with mobile + OTP |
| `/batches` | List enrolled PW batches |
| `/extract` | Extract batch(es) to JSON |
| `/logout` | Clear session |
| `/help` | Show help |

---

## 📂 JSON Output Structure

```json
{
  "batch_id": "...",
  "batch_name": "JEE 2025 Full Course",
  "subjects": [
    {
      "subject_name": "Physics",
      "topics": [
        {
          "topic_name": "Kinematics",
          "videos": [
            {
              "id": "...",
              "title": "Motion in 1D",
              "duration_sec": 3540,
              "brightcove_id": "123456789",
              "youtube_id": "abc123",
              "direct_url": "https://...",
              "is_drm": false,
              "created_at": "2024-01-15T..."
            }
          ],
          "notes": [...],
          "dpp": [...]
        }
      ]
    }
  ]
}
```

---

## ▶️ Playing Videos

| Source | How to play |
|---|---|
| YouTube | Opens directly in YouTube |
| HLS (m3u8) | Copy link → **VLC** or **MX Player** |
| DRM protected | Token is appended — use in-app player or premium downloader |

---

## ⚙️ Tech Stack

- **Python 3.11**
- **python-telegram-bot 20.7** (async)
- **aiohttp** for API calls
- **Railway** for hosting (free worker dyno)
- PW API via reverse-engineered endpoints

---

## ⚠️ Disclaimer

This project is for **personal educational use only**. It uses the publicly accessible Physics Wallah mobile API. Do not redistribute downloaded content. Respect PW's terms of service.
