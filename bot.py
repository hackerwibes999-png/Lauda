import os
import sys
import uuid
import shutil
import asyncio
import signal
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ContextTypes, filters
)

from config import (
    BOT_TOKEN, ADMIN_IDS, UPLOAD_DIR, BOTS_DIR, LOGS_DIR, 
    MAX_FILE_SIZE, SUPPORTED_EXTENSIONS
)
from database import (
    init_db, add_bot, update_bot_status, get_user_bots, 
    get_bot, delete_bot, get_user_bot_count, get_user_max_bots,
    create_or_update_user
)
from manager import BotManager

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
init_db()
bot_manager = BotManager()

# User states
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = update.effective_user.id
    create_or_update_user(user_id)
    
    welcome_text = (
        "🤖 Welcome to Bot Hosting Service!\n\n"
        "I can host your Telegram bots written in Python.\n\n"
        "Commands:\n"
        "/deploy - Upload and deploy a new bot\n"
        "/list - List your deployed bots\n"
        "/help - Show this message\n\n"
        "How to deploy:\n"
        "1. Send me a .zip file or .py file\n"
        "2. Include requirements.txt\n"
        "3. Make sure your bot uses long polling (not webhooks)\n"
        "4. Your bot should read token from environment variable BOT_TOKEN\n\n"
        "Limits:\n"
        "- Max 5 bots per user\n"
        "- Max file size: 10MB\n"
        "- Python 3.11+\n"
        "- Supports python-telegram-bot library"
    )
    await update.message.reply_text(welcome_text)

async def deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deploy command - ask for bot token first"""
    user_id = update.effective_user.id
    
    # Check bot count limit
    count = get_user_bot_count(user_id)
    max_bots = get_user_max_bots(user_id)
    
    if count >= max_bots:
        await update.message.reply_text(
            f"❌ You've reached the maximum limit of {max_bots} bots.\n"
            "Delete some bots to deploy new ones."
        )
        return
    
    await update.message.reply_text(
        "📤 Send me your bot's Telegram token first.\n\n"
        "Get it from @BotFather.\n"
        "Format: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    )
    user_states[user_id] = {'step': 'awaiting_token'}

async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot token input"""
    user_id = update.effective_user.id
    
    # Check if user is in deployment process
    if user_id not in user_states or user_states[user_id].get('step') != 'awaiting_token':
        await update.message.reply_text(
            "Please use /deploy command first to start the deployment process."
        )
        return
    
    token = update.message.text.strip()
    
    # Validate token format
    if not token or ':' not in token:
        await update.message.reply_text(
            "❌ Invalid token format. Please send the token in this format:\n"
            "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        )
        return
    
    # Verify token
    is_valid, username = bot_manager.verify_bot_token(token)
    if not is_valid:
        await update.message.reply_text(
            "❌ Invalid bot token. Please check and try again."
        )
        return
    
    await update.message.reply_text(
        f"✅ Token verified! Bot: @{username}\n\n"
        "Now send me your bot code file:\n"
        "- Python: .py file or .zip with requirements.txt\n\n"
        "Make sure your bot uses long polling (not webhooks)!"
    )
    user_states[user_id] = {'step': 'awaiting_file', 'token': token}

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded bot code file"""
    user_id = update.effective_user.id
    
    if user_id not in user_states or user_states[user_id].get('step') != 'awaiting_file':
        await update.message.reply_text(
            "Please use /deploy command first to start the deployment process."
        )
        return
    
    document = update.message.document
    if not document:
        await update.message.reply_text("❌ Please send a file.")
        return
    
    # Check file size
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ File too large! Max size: {MAX_FILE_SIZE//1024//1024}MB"
        )
        return
    
    # Check file extension
    file_name = document.file_name
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS and not file_name.endswith('.zip'):
        await update.message.reply_text(
            f"❌ Unsupported file type. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
        return
    
    # Download file
    try:
        file = await document.get_file()
        bot_id = f"bot_{uuid.uuid4().hex[:8]}"
        file_path = os.path.join(UPLOAD_DIR, f"{bot_id}_{file_name}")
        await file.download_to_drive(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to download file: {str(e)}")
        return
    
    # Processing message
    status_msg = await update.message.reply_text(
        "🔄 Processing your bot...\n"
        "⏳ Extracting and installing dependencies..."
    )
    
    # Extract and prepare
    success, bot_type, main_file = bot_manager.extract_and_prepare(file_path, bot_id)
    
    if not success:
        await status_msg.edit_text(f"❌ Failed to prepare bot: {main_file}")
        return
    
    await status_msg.edit_text(
        f"✅ Code extracted!\n"
        f"📁 Type: {bot_type}\n"
        f"📄 Main file: {os.path.basename(main_file)}\n"
        "⏳ Starting bot..."
    )
    
    # Start the bot
    token = user_states[user_id]['token']
    success, process_id, error = bot_manager.start_bot(bot_id, bot_type, main_file, token)
    
    if not success:
        await status_msg.edit_text(f"❌ Failed to start bot: {error}")
        # Clean up user state
        del user_states[user_id]
        return
    
    # Save to database
    add_bot(bot_id, user_id, token, bot_type, main_file)
    update_bot_status(bot_id, 'running', process_id)
    
    # Clean up
    try:
        os.remove(file_path)
    except:
        pass
    del user_states[user_id]
    
    await status_msg.edit_text(
        f"✅ Bot Deployed Successfully!\n\n"
        f"🆔 ID: {bot_id}\n"
        f"📁 Type: {bot_type}\n"
        f"🔢 Process ID: {process_id}\n"
        f"📊 Status: Running\n\n"
        "Use /list to see all your bots\n"
        "Use /logs id to view logs"
    )

async def list_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all bots for the user"""
    user_id = update.effective_user.id
    bots = get_user_bots(user_id)
    
    if not bots:
        await update.message.reply_text(
            "📭 You have no bots deployed.\n"
            "Use /deploy to deploy your first bot!"
        )
        return
    
    # Get current status for each bot
    status_text = "📋 Your Deployed Bots\n\n"
    
    for i, bot in enumerate(bots, 1):
        bot_id = bot['id']
        # Get live status
        live_status = bot_manager.get_bot_status(bot_id)
        status_emoji = "🟢" if live_status == 'online' else "🔴"
        
        status_text += f"{i}. {status_emoji} {bot_id}\n"
        status_text += f"   Type: {bot['bot_type']}\n"
        status_text += f"   Status: {live_status}\n"
        status_text += f"   Created: {bot['created_at'][:16]}\n\n"
    
    # Add control buttons
    keyboard = []
    for bot in bots[:5]:  # Show first 5 in buttons
        keyboard.append([
            InlineKeyboardButton(f"📊 {bot['id']}", callback_data=f"bot_{bot['id']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        status_text,
        reply_markup=reply_markup
    )

async def bot_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot action buttons"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith('bot_'):
        bot_id = data.replace('bot_', '')
        bot = get_bot(bot_id)
        
        if not bot or bot['user_id'] != user_id:
            await query.edit_message_text("❌ Bot not found or access denied.")
            return
        
        # Get live status
        live_status = bot_manager.get_bot_status(bot_id)
        
        keyboard = [
            [
                InlineKeyboardButton("▶️ Start", callback_data=f"start_{bot_id}"),
                InlineKeyboardButton("⏹ Stop", callback_data=f"stop_{bot_id}")
            ],
            [
                InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{bot_id}"),
                InlineKeyboardButton("📋 Logs", callback_data=f"logs_{bot_id}")
            ],
            [
                InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{bot_id}")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="back_list")
            ]
        ]
        
        status_emoji = "🟢" if live_status == 'online' else "🔴"
        status_text = (
            f"🤖 Bot Details\n\n"
            f"🆔 ID: {bot_id}\n"
            f"📁 Type: {bot['bot_type']}\n"
            f"📊 Status: {status_emoji} {live_status}\n"
            f"📄 Main: {os.path.basename(bot['main_file'])}\n"
            f"📅 Created: {bot['created_at'][:16]}\n\n"
            "Controls:"
        )
        await query.edit_message_text(
            status_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith('start_'):
        bot_id = data.replace('start_', '')
        bot = get_bot(bot_id)
        if bot and bot['user_id'] == user_id:
            success, error = bot_manager.restart_bot(bot_id)
            if success:
                update_bot_status(bot_id, 'running')
                await query.edit_message_text(f"✅ Bot {bot_id} started!")
            else:
                await query.edit_message_text(f"❌ Failed to start: {error}")
    
    elif data.startswith('stop_'):
        bot_id = data.replace('stop_', '')
        bot = get_bot(bot_id)
        if bot and bot['user_id'] == user_id:
            success, error = bot_manager.stop_bot(bot_id)
            if success:
                update_bot_status(bot_id, 'stopped')
                await query.edit_message_text(f"✅ Bot {bot_id} stopped!")
            else:
                await query.edit_message_text(f"❌ Failed to stop: {error}")
    
    elif data.startswith('restart_'):
        bot_id = data.replace('restart_', '')
        bot = get_bot(bot_id)
        if bot and bot['user_id'] == user_id:
            success, error = bot_manager.restart_bot(bot_id)
            if success:
                update_bot_status(bot_id, 'running')
                await query.edit_message_text(f"✅ Bot {bot_id} restarted!")
            else:
                await query.edit_message_text(f"❌ Failed to restart: {error}")
    
    elif data.startswith('logs_'):
        bot_id = data.replace('logs_', '')
        bot = get_bot(bot_id)
        if bot and bot['user_id'] == user_id:
            logs = bot_manager.get_logs(bot_id, 50)
            # Truncate if too long
            if len(logs) > 4000:
                logs = logs[-4000:] + "\n\n... (truncated)"
            await query.edit_message_text(
                f"📋 Logs for {bot_id}\n\n{logs}"
            )
    
    elif data.startswith('delete_'):
        bot_id = data.replace('delete_', '')
        bot = get_bot(bot_id)
        if bot and bot['user_id'] == user_id:
            success, error = bot_manager.delete_bot(bot_id)
            if success:
                delete_bot(bot_id)
                await query.edit_message_text(f"✅ Bot {bot_id} deleted!")
            else:
                await query.edit_message_text(f"❌ Failed to delete: {error}")
    
    elif data == 'back_list':
        # Re-display the list
        await list_bots(update, context)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get logs for a specific bot"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /logs <bot_id>\n\n"
            "Example: /logs bot_abc123"
        )
        return
    
    bot_id = context.args[0]
    bot = get_bot(bot_id)
    
    if not bot:
        await update.message.reply_text(
            f"❌ Bot '{bot_id}' not found in database.\n"
            "Use /list to see your deployed bots."
        )
        return
    
    if bot['user_id'] != user_id:
        await update.message.reply_text("❌ Access denied. This bot belongs to another user.")
        return
    
    logs = bot_manager.get_logs(bot_id, 50)
    if len(logs) > 4000:
        logs = logs[-4000:] + "\n\n... (truncated)"
    
    await update.message.reply_text(
        f"📋 Logs for {bot_id}\n\n{logs}"
    )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop a bot"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /stop <bot_id>")
        return
    
    bot_id = context.args[0]
    bot = get_bot(bot_id)
    
    if not bot or bot['user_id'] != user_id:
        await update.message.reply_text("❌ Bot not found or access denied.")
        return
    
    success, error = bot_manager.stop_bot(bot_id)
    if success:
        update_bot_status(bot_id, 'stopped')
        await update.message.reply_text(f"✅ Bot {bot_id} stopped!")
    else:
        await update.message.reply_text(f"❌ Failed to stop: {error}")

async def start_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a bot"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /startbot <bot_id>")
        return
    
    bot_id = context.args[0]
    bot = get_bot(bot_id)
    
    if not bot or bot['user_id'] != user_id:
        await update.message.reply_text("❌ Bot not found or access denied.")
        return
    
    success, error = bot_manager.restart_bot(bot_id)
    if success:
        update_bot_status(bot_id, 'running')
        await update.message.reply_text(f"✅ Bot {bot_id} started!")
    else:
        await update.message.reply_text(f"❌ Failed to start: {error}")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a bot"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /delete <bot_id>")
        return
    
    bot_id = context.args[0]
    bot = get_bot(bot_id)
    
    if not bot or bot['user_id'] != user_id:
        await update.message.reply_text("❌ Bot not found or access denied.")
        return
    
    success, error = bot_manager.delete_bot(bot_id)
    if success:
        delete_bot(bot_id)
        await update.message.reply_text(f"✅ Bot {bot_id} deleted!")
    else:
        await update.message.reply_text(f"❌ Failed to delete: {error}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = (
        "🤖 Bot Hosting Service Help\n\n"
        "Deployment Process:\n"
        "1. /deploy - Start deployment\n"
        "2. Send your bot token (from @BotFather)\n"
        "3. Send your bot code (.py or .zip)\n\n"
        "Requirements:\n"
        "- Python bots using python-telegram-bot library\n"
        "- Bot must use long polling (not webhooks)\n"
        "- Bot should read token from BOT_TOKEN environment variable\n\n"
        "Commands:\n"
        "/deploy - Deploy a new bot\n"
        "/list - List your bots\n"
        "/startbot <id> - Start a bot\n"
        "/stop <id> - Stop a bot\n"
        "/logs <id> - View bot logs\n"
        "/delete <id> - Delete a bot\n"
        "/help - Show this message"
    )
    await update.message.reply_text(help_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    error_msg = str(context.error)
    if len(error_msg) > 200:
        error_msg = error_msg[:200] + "..."
    
    logger.error(f"Error: {error_msg}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            f"❌ An error occurred: {error_msg}"
        )

def shutdown_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("🛑 Shutting down bot...")
    # Clean up any running processes
    for bot_id in list(bot_manager.processes.keys()):
        try:
            bot_manager.stop_bot(bot_id)
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id}: {e}")
    sys.exit(0)

def main():
    """Main function"""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("deploy", deploy))
    app.add_handler(CommandHandler("list", list_bots))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("startbot", start_bot_command))
    app.add_handler(CommandHandler("delete", delete_command))
    
    # Add message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # Add callback query handler for inline buttons
    app.add_handler(CallbackQueryHandler(bot_action))
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    logger.info("🤖 Bot Hosting Service Started!")
    logger.info(f"Bot token: {BOT_TOKEN[:10]}...")
    logger.info("📁 Directories created:")
    logger.info(f"   - Uploads: {UPLOAD_DIR}")
    logger.info(f"   - Bots: {BOTS_DIR}")
    logger.info(f"   - Logs: {LOGS_DIR}")
    logger.info("✅ Ready to host bots!")
    
    # Start the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
