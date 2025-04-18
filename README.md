# Telegram Trends Casino Bot 🇮🇳

This bot tracks trending online casino queries in India using Google Trends and sends notifications via Telegram.

## Features
- Google Trends tracking via pytrends
- Brand detection via custom keyword filters
- Persistent keyword base management
- Telegram webhook support (via Flask)
- Export to Excel (.xlsx)

## Deploy on Railway

1. Fork the repository or upload this folder to GitHub
2. Go to [https://railway.app](https://railway.app)
3. Create a new project → Deploy from GitHub
4. Add these environment variables:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Deploy!

