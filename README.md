# Telegram Bot Hosting Service

A Telegram bot that allows users to deploy and host their own Telegram bots.

## Features

- Deploy Python Telegram bots via file upload
- Supports .py and .zip files
- Automatic dependency installation
- Bot management (start, stop, restart, delete)
- Log viewing
- User quotas (max 5 bots per user)

## Deployment on Railway

1. Fork this repository
2. Create a new project on Railway
3. Connect your GitHub repository
4. Add environment variables:
   - `BOT_TOKEN` - Your main bot token
   - `ADMIN_IDS` - Comma-separated user IDs for admin access
5. Deploy!

## Local Development

1. Clone the repository
2. Create a virtual environment
3. Install dependencies: `pip install -r requirements.txt`
4. Create `.env` file with your bot token
5. Run: `python bot.py`

## Usage

- `/start` - Start the bot
- `/deploy` - Deploy a new bot
- `/list` - List your bots
- `/logs <id>` - View bot logs
- `/stop <id>` - Stop a bot
- `/startbot <id>` - Start a bot
- `/delete <id>` - Delete a bot
- `/help` - Show help

## Requirements for Deploying Bots

- Python 3.11+
- Uses python-telegram-bot library
- Uses long polling (not webhooks)
- Reads token from BOT_TOKEN environment variable
