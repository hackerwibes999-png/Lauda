import os
import sys
import uuid
import signal
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    UPLOAD_DIR,
    BOTS_DIR,
    LOGS_DIR,
    MAX_FILE_SIZE,
    SUPPORTED_EXTENSIONS,
)

from database import (
    init_db,
    add_bot,
    update_bot_status,
    get_user_bots,
    get_bot,
    delete_bot,
    get_user_bot_count,
    get_user_max_bots,
    create_or_update_user,
)

from manager import BotManager


# ============================================================
# CONFIGURATION
# ============================================================

# Normal users can host up to 30 bots.
MAX_BOTS_PER_USER = 30

# Admins have unlimited bots.
ADMIN_UNLIMITED = True

# Additional extensions accepted by this bot.py.
# Actual execution is handled by manager.py.
EXTRA_SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".php",
    ".zip",
}

# Maximum Telegram message size we try to use for logs.
MAX_MESSAGE_LENGTH = 4000


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# INITIALIZATION
# ============================================================

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

init_db()

bot_manager = BotManager()

# Deployment state:
#
# user_states[user_id] = {
#     "step": "awaiting_token",
#     "token": "...",
# }
#
# or
#
# user_states[user_id] = {
#     "step": "awaiting_file",
#     "token": "...",
# }
user_states = {}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_admin(user_id: int) -> bool:
    """Return True if the user is an administrator."""
    try:
        return int(user_id) in [int(x) for x in ADMIN_IDS]
    except Exception:
        return False


def get_max_bots_for_user(user_id: int) -> int:
    """
    Return maximum bots allowed for a user.

    Admins have unlimited hosting.
    Normal users have a hard limit of 30.
    """
    if is_admin(user_id) and ADMIN_UNLIMITED:
        return 999999999

    return MAX_BOTS_PER_USER


def is_supported_file(filename: str) -> bool:
    """Check whether a file extension is supported."""
    if not filename:
        return False

    extension = Path(filename).suffix.lower()

    configured_extensions = set()

    try:
        configured_extensions = {
            str(ext).lower()
            for ext in SUPPORTED_EXTENSIONS
        }
    except Exception:
        pass

    supported = configured_extensions | EXTRA_SUPPORTED_EXTENSIONS

    return extension in supported


def get_runtime_from_filename(filename: str) -> str:
    """Determine the likely runtime from the uploaded filename."""
    extension = Path(filename).suffix.lower()

    if extension == ".py":
        return "Python"

    if extension == ".js":
        return "Node.js"

    if extension == ".php":
        return "PHP"

    if extension == ".zip":
        return "Auto-detect"

    return "Unknown"


def truncate_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate text safely for Telegram."""
    if not text:
        return "No logs available."

    if len(text) <= max_length:
        return text

    return text[-max_length:] + "\n\n... (truncated)"


def get_live_status(bot_id: str) -> str:
    """Get the current BotManager status safely."""
    try:
        status = bot_manager.get_bot_status(bot_id)

        if status:
            return status

        return "unknown"

    except Exception as e:
        logger.error(
            "Failed to get status for %s: %s",
            bot_id,
            e,
        )
        return "unknown"


def admin_keyboard() -> InlineKeyboardMarkup:
    """Build the admin panel keyboard."""
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="admin_stats",
            ),
            InlineKeyboardButton(
                "👥 Users",
                callback_data="admin_users",
            ),
        ],
        [
            InlineKeyboardButton(
                "🤖 All Bots",
                callback_data="admin_bots",
            ),
            InlineKeyboardButton(
                "🟢 Running",
                callback_data="admin_running",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔴 Stopped",
                callback_data="admin_stopped",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 Close",
                callback_data="admin_close",
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    try:
        create_or_update_user(user_id)
    except Exception as e:
        logger.error("Failed to create/update user: %s", e)

    admin_text = ""

    if is_admin(user_id):
        admin_text = (
            "\n\n👑 You are an administrator.\n"
            "You have unlimited bot hosting.\n"
            "Use /admin to open the admin panel."
        )

    welcome_text = (
        "🤖 Welcome to Bot Hosting Service!By @Hackerwibes\n\n"
        "I can host your Telegram bots.\n\n"
        "Commands:\n"
        "/deploy - Upload and deploy a new bot\n"
        "/list - List your deployed bots\n"
        "/help - Show help\n\n"
        "Supported runtimes:\n"
        "🐍 Python (.py)\n"
        "🟨 JavaScript / Node.js (.js)\n"
        "🐘 PHP (.php)\n"
        "📦 ZIP projects (.zip)\n\n"
        "Deployment:\n"
        "1. Send /deploy\n"
        "2. Send your bot token\n"
        "3. Send your code file\n\n"
        f"👤 User limit: {MAX_BOTS_PER_USER} bots"
        f"{admin_text}"
    )

    await update.message.reply_text(welcome_text)


# ============================================================
# DEPLOY
# ============================================================

async def deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start deployment process."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    try:
        count = get_user_bot_count(user_id)
    except Exception as e:
        logger.error("Failed to get bot count: %s", e)
        count = 0

    max_bots = get_max_bots_for_user(user_id)

    if not is_admin(user_id) and count >= max_bots:
        await update.message.reply_text(
            "❌ Hosting limit reached.\n\n"
            f"You currently have {count} bots.\n"
            f"Your maximum is {MAX_BOTS_PER_USER} bots.\n\n"
            "Delete an existing bot before deploying another one."
        )
        return

    if is_admin(user_id):
        limit_text = "♾️ Unlimited hosting"
    else:
        limit_text = f"📊 {count}/{MAX_BOTS_PER_USER} bots used"

    await update.message.reply_text(
        "📤 Send me your bot's Telegram token first.\n\n"
        "Get it from @BotFather.\n\n"
        "Format:\n"
        "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n\n"
        f"{limit_text}"
    )

    user_states[user_id] = {
        "step": "awaiting_token"
    }


# ============================================================
# TOKEN HANDLER
# ============================================================

async def handle_token(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle bot token input."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    state = user_states.get(user_id)

    if not state or state.get("step") != "awaiting_token":
        await update.message.reply_text(
            "Please use /deploy first."
        )
        return

    token = (update.message.text or "").strip()

    if not token or ":" not in token:
        await update.message.reply_text(
            "❌ Invalid token format.\n\n"
            "Please send the Telegram bot token received from @BotFather."
        )
        return

    # Basic token validation.
    token_parts = token.split(":", 1)

    if len(token_parts) != 2:
        await update.message.reply_text(
            "❌ Invalid bot token."
        )
        return

    if not token_parts[0].isdigit() or len(token_parts[1]) < 10:
        await update.message.reply_text(
            "❌ Invalid bot token format."
        )
        return

    # Verify token with BotManager.
    try:
        is_valid, username = bot_manager.verify_bot_token(token)
    except Exception as e:
        logger.error("Token verification failed: %s", e)

        await update.message.reply_text(
            "❌ Could not verify the bot token.\n"
            "Please try again."
        )
        return

    if not is_valid:
        await update.message.reply_text(
            "❌ Invalid bot token.\n"
            "Please check the token and try again."
        )
        return

    user_states[user_id] = {
        "step": "awaiting_file",
        "token": token,
    }

    await update.message.reply_text(
        f"✅ Token verified!\n"
        f"🤖 Bot: @{username}\n\n"
        "Now send your bot code file.\n\n"
        "Supported:\n"
        "🐍 Python: .py\n"
        "🟨 Node.js: .js\n"
        "🐘 PHP: .php\n"
        "📦 Project: .zip\n\n"
        "For ZIP projects, include the appropriate dependency file "
        "such as requirements.txt, package.json, or composer.json."
    )


# ============================================================
# FILE HANDLER
# ============================================================

async def handle_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle uploaded bot files."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    state = user_states.get(user_id)

    if not state or state.get("step") != "awaiting_file":
        await update.message.reply_text(
            "Please use /deploy first."
        )
        return

    document = update.message.document

    if not document:
        await update.message.reply_text(
            "❌ Please send a file."
        )
        return

    file_name = document.file_name or "uploaded_file"

    # --------------------------------------------------------
    # File size
    # --------------------------------------------------------

    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ File too large!\n\n"
            f"Maximum allowed size: "
            f"{MAX_FILE_SIZE // 1024 // 1024}MB"
        )
        return

    # --------------------------------------------------------
    # File extension
    # --------------------------------------------------------

    if not is_supported_file(file_name):
        await update.message.reply_text(
            "❌ Unsupported file type.\n\n"
            "Supported files:\n"
            "🐍 .py\n"
            "🟨 .js\n"
            "🐘 .php\n"
            "📦 .zip"
        )
        return

    runtime = get_runtime_from_filename(file_name)

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    bot_id = f"bot_{uuid.uuid4().hex[:8]}"

    safe_filename = Path(file_name).name

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{bot_id}_{safe_filename}",
    )

    try:
        telegram_file = await document.get_file()

        await telegram_file.download_to_drive(
            custom_path=file_path
        )

    except Exception as e:
        logger.error(
            "Failed to download file for %s: %s",
            bot_id,
            e,
        )

        await update.message.reply_text(
            f"❌ Failed to download file:\n{e}"
        )
        return

    status_msg = await update.message.reply_text(
        "🔄 Processing your bot...\n\n"
        f"🆔 ID: {bot_id}\n"
        f"⚙️ Runtime: {runtime}\n"
        "⏳ Preparing files..."
    )

    # --------------------------------------------------------
    # Extract / prepare
    # --------------------------------------------------------

    try:
        success, bot_type, main_file = (
            bot_manager.extract_and_prepare(
                file_path,
                bot_id,
            )
        )

    except Exception as e:
        logger.exception(
            "Preparation failed for %s",
            bot_id,
        )

        try:
            os.remove(file_path)
        except Exception:
            pass

        await status_msg.edit_text(
            f"❌ Failed to prepare bot:\n{e}"
        )
        return

    if not success:
        try:
            os.remove(file_path)
        except Exception:
            pass

        await status_msg.edit_text(
            f"❌ Failed to prepare bot:\n{main_file}"
        )
        return

    await status_msg.edit_text(
        "✅ Code prepared!\n\n"
        f"🆔 ID: {bot_id}\n"
        f"⚙️ Detected type: {bot_type}\n"
        f"📄 Main file: {os.path.basename(main_file)}\n\n"
        "⏳ Starting bot..."
    )

    # --------------------------------------------------------
    # Start
    # --------------------------------------------------------

    token = state.get("token")

    try:
        success, process_id, error = (
            bot_manager.start_bot(
                bot_id,
                bot_type,
                main_file,
                token,
            )
        )

    except Exception as e:
        logger.exception(
            "Failed to start bot %s",
            bot_id,
        )

        success = False
        process_id = None
        error = str(e)

    if not success:
        try:
            os.remove(file_path)
        except Exception:
            pass

        user_states.pop(user_id, None)

        await status_msg.edit_text(
            "❌ Failed to start bot.\n\n"
            f"Error:\n{error}\n\n"
            f"Detected runtime: {runtime}\n"
            f"Bot type: {bot_type}"
        )
        return

    # --------------------------------------------------------
    # Save to database
    # --------------------------------------------------------

    try:
        add_bot(
            bot_id,
            user_id,
            token,
            bot_type,
            main_file,
        )

        update_bot_status(
            bot_id,
            "running",
            process_id,
        )

    except Exception as e:
        logger.exception(
            "Database error while saving %s",
            bot_id,
        )

        # Try to stop the process if database saving failed.
        try:
            bot_manager.stop_bot(bot_id)
        except Exception:
            pass

        user_states.pop(user_id, None)

        await status_msg.edit_text(
            f"❌ Database error:\n{e}"
        )
        return

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    try:
        os.remove(file_path)
    except Exception:
        pass

    user_states.pop(user_id, None)

    if is_admin(user_id):
        limit_text = "♾️ Unlimited"
    else:
        try:
            new_count = get_user_bot_count(user_id)
        except Exception:
            new_count = "?"

        limit_text = f"{new_count}/{MAX_BOTS_PER_USER}"

    await status_msg.edit_text(
        "✅ Bot Deployed Successfully!\n\n"
        f"🆔 ID: {bot_id}\n"
        f"⚙️ Type: {bot_type}\n"
        f"📄 Main: {os.path.basename(main_file)}\n"
        f"🔢 Process ID: {process_id}\n"
        "📊 Status: 🟢 Running\n"
        f"👤 Hosting: {limit_text}\n\n"
        "Use /list to manage your bots.\n"
        f"Use /logs {bot_id} to view logs."
    )


# ============================================================
# LIST USER BOTS
# ============================================================

async def list_bots(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """List bots belonging to the current user."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    try:
        bots = get_user_bots(user_id)
    except Exception as e:
        logger.error("Failed to get user bots: %s", e)

        await update.message.reply_text(
            "❌ Failed to load your bots."
        )
        return

    if not bots:
        await update.message.reply_text(
            "📭 You have no bots deployed.\n\n"
            "Use /deploy to deploy your first bot."
        )
        return

    if is_admin(user_id):
        limit_text = "♾️ Unlimited"
    else:
        limit_text = f"{len(bots)}/{MAX_BOTS_PER_USER}"

    status_text = (
        "📋 Your Deployed Bots\n\n"
        f"📊 Hosting: {limit_text}\n\n"
    )

    keyboard = []

    for i, bot in enumerate(bots, 1):
        bot_id = bot["id"]

        live_status = get_live_status(bot_id)

        if live_status in ("online", "running"):
            status_emoji = "🟢"
        else:
            status_emoji = "🔴"

        status_text += (
            f"{i}. {status_emoji} {bot_id}\n"
            f"   Type: {bot['bot_type']}\n"
            f"   Status: {live_status}\n"
            f"   Created: {bot['created_at'][:16]}\n\n"
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📊 {bot_id}",
                    callback_data=f"bot_{bot_id}",
                )
            ]
        )

    await update.message.reply_text(
        status_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# BOT ACTIONS
# ============================================================

async def bot_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle inline bot-management buttons."""
    query = update.callback_query

    if not query:
        return

    await query.answer()

    if not update.effective_user:
        return

    user_id = update.effective_user.id
    data = query.data or ""

    # ========================================================
    # ADMIN PANEL
    # ========================================================

    if data.startswith("admin_"):
        await handle_admin_callback(
            query,
            user_id,
            data,
        )
        return

    # ========================================================
    # BOT DETAILS
    # ========================================================

    if data.startswith("bot_"):
        bot_id = data[len("bot_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        # Owner OR admin.
        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        live_status = get_live_status(bot_id)

        status_emoji = (
            "🟢"
            if live_status in ("online", "running")
            else "🔴"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "▶️ Start",
                    callback_data=f"start_{bot_id}",
                ),
                InlineKeyboardButton(
                    "⏹ Stop",
                    callback_data=f"stop_{bot_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔄 Restart",
                    callback_data=f"restart_{bot_id}",
                ),
                InlineKeyboardButton(
                    "📋 Logs",
                    callback_data=f"logs_{bot_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑 Delete",
                    callback_data=f"delete_{bot_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="back_list",
                ),
            ],
        ]

        owner_text = ""

        if is_admin(user_id):
            owner_text = (
                f"👤 Owner ID: {bot['user_id']}\n"
            )

        status_text = (
            "🤖 Bot Details\n\n"
            f"🆔 ID: {bot_id}\n"
            f"{owner_text}"
            f"📁 Type: {bot['bot_type']}\n"
            f"📊 Status: {status_emoji} {live_status}\n"
            f"📄 Main: {os.path.basename(bot['main_file'])}\n"
            f"📅 Created: {bot['created_at'][:16]}\n\n"
            "Controls:"
        )

        await query.edit_message_text(
            status_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # ========================================================
    # START
    # ========================================================

    if data.startswith("start_"):
        bot_id = data[len("start_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        try:
            success, error = bot_manager.restart_bot(bot_id)

            if success:
                update_bot_status(
                    bot_id,
                    "running",
                )

                await query.edit_message_text(
                    f"✅ Bot `{bot_id}` started!",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to start:\n{error}"
                )

        except Exception as e:
            await query.edit_message_text(
                f"❌ Failed to start:\n{e}"
            )

        return

    # ========================================================
    # STOP
    # ========================================================

    if data.startswith("stop_"):
        bot_id = data[len("stop_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        try:
            success, error = bot_manager.stop_bot(bot_id)

            if success:
                update_bot_status(
                    bot_id,
                    "stopped",
                )

                await query.edit_message_text(
                    f"✅ Bot `{bot_id}` stopped!",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to stop:\n{error}"
                )

        except Exception as e:
            await query.edit_message_text(
                f"❌ Failed to stop:\n{e}"
            )

        return

    # ========================================================
    # RESTART
    # ========================================================

    if data.startswith("restart_"):
        bot_id = data[len("restart_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        try:
            success, error = bot_manager.restart_bot(bot_id)

            if success:
                update_bot_status(
                    bot_id,
                    "running",
                )

                await query.edit_message_text(
                    f"✅ Bot `{bot_id}` restarted!",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to restart:\n{error}"
                )

        except Exception as e:
            await query.edit_message_text(
                f"❌ Failed to restart:\n{e}"
            )

        return

    # ========================================================
    # LOGS
    # ========================================================

    if data.startswith("logs_"):
        bot_id = data[len("logs_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        try:
            logs = bot_manager.get_logs(
                bot_id,
                50,
            )
        except Exception as e:
            logs = f"Failed to read logs: {e}"

        logs = truncate_text(logs)

        await query.edit_message_text(
            f"📋 Logs for {bot_id}\n\n"
            f"{logs}"
        )

        return

    # ========================================================
    # DELETE
    # ========================================================

    if data.startswith("delete_"):
        bot_id = data[len("delete_"):]

        bot = get_bot(bot_id)

        if not bot:
            await query.edit_message_text(
                "❌ Bot not found."
            )
            return

        if bot["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text(
                "❌ Access denied."
            )
            return

        try:
            success, error = bot_manager.delete_bot(
                bot_id
            )

            if success:
                delete_bot(bot_id)

                await query.edit_message_text(
                    f"✅ Bot `{bot_id}` deleted!",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to delete:\n{error}"
                )

        except Exception as e:
            await query.edit_message_text(
                f"❌ Failed to delete:\n{e}"
            )

        return

    # ========================================================
    # BACK TO USER LIST
    # ========================================================

    if data == "back_list":
        try:
            bots = get_user_bots(user_id)
        except Exception:
            bots = []

        if not bots:
            await query.edit_message_text(
                "📭 You have no deployed bots."
            )
            return

        status_text = "📋 Your Deployed Bots\n\n"

        keyboard = []

        for bot in bots:
            bot_id = bot["id"]
            status = get_live_status(bot_id)

            emoji = (
                "🟢"
                if status in ("online", "running")
                else "🔴"
            )

            status_text += (
                f"{emoji} {bot_id}\n"
                f"Type: {bot['bot_type']}\n"
                f"Status: {status}\n\n"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📊 {bot_id}",
                        callback_data=f"bot_{bot_id}",
                    )
                ]
            )

        await query.edit_message_text(
            status_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# ============================================================
# ADMIN PANEL
# ============================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Open admin panel."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ Access denied.\n\n"
            "This command is for administrators only."
        )
        return

    await update.message.reply_text(
        "👑 ADMIN PANEL\n\n"
        "Select an option:",
        reply_markup=admin_keyboard(),
    )


async def handle_admin_callback(
    query,
    user_id: int,
    data: str,
):
    """Handle admin panel callbacks."""

    if not is_admin(user_id):
        await query.edit_message_text(
            "❌ Access denied."
        )
        return

    # ========================================================
    # ADMIN HOME
    # ========================================================

    if data == "admin_home":
        await query.edit_message_text(
            "👑 ADMIN PANEL\n\n"
            "Select an option:",
            reply_markup=admin_keyboard(),
        )
        return

    # ========================================================
    # CLOSE
    # ========================================================

    if data == "admin_close":
        await query.edit_message_text(
            "👑 Admin panel closed."
        )
        return

    # ========================================================
    # STATISTICS
    # ========================================================

    if data == "admin_stats":
        await show_admin_statistics(query)
        return

    # ========================================================
    # USERS
    # ========================================================

    if data == "admin_users":
        await show_admin_users(query)
        return

    # ========================================================
    # ALL BOTS
    # ========================================================

    if data == "admin_bots":
        await show_admin_bots(
            query,
            mode="all",
        )
        return

    # ========================================================
    # RUNNING
    # ========================================================

    if data == "admin_running":
        await show_admin_bots(
            query,
            mode="running",
        )
        return

    # ========================================================
    # STOPPED
    # ========================================================

    if data == "admin_stopped":
        await show_admin_bots(
            query,
            mode="stopped",
        )
        return


async def show_admin_statistics(query):
    """Show hosting statistics to admins."""

    # The existing database API does not expose a global
    # get_all_users/get_all_bots function, so we calculate
    # what is available through BotManager where possible.

    try:
        process_count = len(
            bot_manager.processes
        )
    except Exception:
        process_count = 0

    try:
        all_processes = list(
            bot_manager.processes.keys()
        )
    except Exception:
        all_processes = []

    running_count = 0

    for bot_id in all_processes:
        status = get_live_status(bot_id)

        if status in ("online", "running"):
            running_count += 1

    await query.edit_message_text(
        "📊 ADMIN STATISTICS\n\n"
        f"🟢 Active processes: {process_count}\n"
        f"🟢 Online bots: {running_count}\n"
        f"👑 Admin hosting: Unlimited\n"
        f"👤 User limit: {MAX_BOTS_PER_USER} bots\n\n"
        "Use the buttons below to inspect bots/users.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🤖 All Bots",
                        callback_data="admin_bots",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin_home",
                    )
                ],
            ]
        ),
    )


async def show_admin_users(query):
    """
    Show users when the database module exposes a compatible
    user-listing function.

    Because your current database.py was not changed, this
    function gracefully handles databases without that API.
    """

    await query.edit_message_text(
        "👥 USER MANAGEMENT\n\n"
        "Your current database.py interface does not expose "
        "a get_all_users() function.\n\n"
        "The admin panel can still manage bots globally, "
        "but a complete user list requires that function "
        "to exist in database.py.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🤖 All Bots",
                        callback_data="admin_bots",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin_home",
                    )
                ],
            ]
        ),
    )


async def show_admin_bots(
    query,
    mode: str = "all",
):
    """
    Display bots known to BotManager.

    This works for currently loaded/running processes.
    Full historical all-user bot listing requires a
    get_all_bots() function in database.py.
    """

    try:
        process_ids = list(
            bot_manager.processes.keys()
        )
    except Exception:
        process_ids = []

    filtered = []

    for bot_id in process_ids:
        status = get_live_status(bot_id)

        if mode == "running":
            if status not in ("online", "running"):
                continue

        elif mode == "stopped":
            if status in ("online", "running"):
                continue

        filtered.append(
            (bot_id, status)
        )

    title = {
        "all": "🤖 ALL BOTS",
        "running": "🟢 RUNNING BOTS",
        "stopped": "🔴 STOPPED BOTS",
    }.get(mode, "🤖 BOTS")

    if not filtered:
        text = (
            f"{title}\n\n"
            "No matching bots are currently loaded."
        )
    else:
        lines = [
            f"{title}\n"
        ]

        for bot_id, status in filtered[:50]:
            lines.append(
                f"🤖 {bot_id}\n"
                f"   Status: {status}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📊 Statistics",
                        callback_data="admin_stats",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin_home",
                    )
                ],
            ]
        ),
    )


# ============================================================
# LOGS COMMAND
# ============================================================

async def logs_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Get logs for a specific bot."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/logs <bot_id>\n\n"
            "Example:\n"
            "/logs bot_abc123"
        )
        return

    bot_id = context.args[0]

    bot = get_bot(bot_id)

    if not bot:
        await update.message.reply_text(
            f"❌ Bot '{bot_id}' not found."
        )
        return

    if bot["user_id"] != user_id and not is_admin(user_id):
        await update.message.reply_text(
            "❌ Access denied."
        )
        return

    try:
        logs = bot_manager.get_logs(
            bot_id,
            50,
        )
    except Exception as e:
        logs = f"Failed to read logs: {e}"

    logs = truncate_text(logs)

    await update.message.reply_text(
        f"📋 Logs for {bot_id}\n\n"
        f"{logs}"
    )


# ============================================================
# STOP COMMAND
# ============================================================

async def stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Stop a bot."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage: /stop <bot_id>"
        )
        return

    bot_id = context.args[0]

    bot = get_bot(bot_id)

    if not bot:
        await update.message.reply_text(
            "❌ Bot not found."
        )
        return

    if bot["user_id"] != user_id and not is_admin(user_id):
        await update.message.reply_text(
            "❌ Access denied."
        )
        return

    try:
        success, error = bot_manager.stop_bot(
            bot_id
        )

        if success:
            update_bot_status(
                bot_id,
                "stopped",
            )

            await update.message.reply_text(
                f"✅ Bot {bot_id} stopped!"
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to stop:\n{error}"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to stop:\n{e}"
        )


# ============================================================
# STARTBOT COMMAND
# ============================================================

async def start_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Start a bot."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage: /startbot <bot_id>"
        )
        return

    bot_id = context.args[0]

    bot = get_bot(bot_id)

    if not bot:
        await update.message.reply_text(
            "❌ Bot not found."
        )
        return

    if bot["user_id"] != user_id and not is_admin(user_id):
        await update.message.reply_text(
            "❌ Access denied."
        )
        return

    try:
        success, error = bot_manager.restart_bot(
            bot_id
        )

        if success:
            update_bot_status(
                bot_id,
                "running",
            )

            await update.message.reply_text(
                f"✅ Bot {bot_id} started!"
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to start:\n{error}"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to start:\n{e}"
        )


# ============================================================
# DELETE COMMAND
# ============================================================

async def delete_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Delete a bot."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage: /delete <bot_id>"
        )
        return

    bot_id = context.args[0]

    bot = get_bot(bot_id)

    if not bot:
        await update.message.reply_text(
            "❌ Bot not found."
        )
        return

    if bot["user_id"] != user_id and not is_admin(user_id):
        await update.message.reply_text(
            "❌ Access denied."
        )
        return

    try:
        success, error = bot_manager.delete_bot(
            bot_id
        )

        if success:
            delete_bot(bot_id)

            await update.message.reply_text(
                f"✅ Bot {bot_id} deleted!"
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to delete:\n{error}"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to delete:\n{e}"
        )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Help command."""
    if not update.message:
        return

    user_id = (
        update.effective_user.id
        if update.effective_user
        else 0
    )

    admin_section = ""

    if is_admin(user_id):
        admin_section = (
            "\n\n👑 ADMIN COMMANDS\n"
            "/admin - Open admin panel\n"
            "Admins have unlimited hosting."
        )

    help_text = (
        "🤖 Bot Hosting Service Help\n\n"
        "Deployment:\n"
        "1. /deploy\n"
        "2. Send your bot token\n"
        "3. Send your code file\n\n"
        "Supported runtimes:\n"
        "🐍 Python (.py)\n"
        "🟨 JavaScript / Node.js (.js)\n"
        "🐘 PHP (.php)\n"
        "📦 ZIP projects (.zip)\n\n"
        "Requirements:\n"
        "- Bot should use long polling\n"
        "- Python projects can use requirements.txt\n"
        "- Node.js projects can use package.json\n"
        "- PHP projects can use composer.json\n\n"
        f"User limit: {MAX_BOTS_PER_USER} bots\n"
        "Admin limit: Unlimited\n\n"
        "COMMANDS\n"
        "/deploy - Deploy a new bot\n"
        "/list - List your bots\n"
        "/startbot <id> - Start a bot\n"
        "/stop <id> - Stop a bot\n"
        "/logs <id> - View logs\n"
        "/delete <id> - Delete a bot\n"
        "/help - Show this message"
        f"{admin_section}"
    )

    await update.message.reply_text(
        help_text
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle application errors."""
    error_msg = str(context.error)

    if len(error_msg) > 500:
        error_msg = error_msg[:500] + "..."

    logger.error(
        "Telegram bot error: %s",
        error_msg,
        exc_info=context.error,
    )

    try:
        if update and hasattr(
            update,
            "effective_message",
        ):
            message = update.effective_message

            if message:
                await message.reply_text(
                    "❌ An internal error occurred.\n"
                    "Please try again later."
                )

    except Exception as e:
        logger.error(
            "Could not send error message: %s",
            e,
        )


# ============================================================
# SHUTDOWN
# ============================================================

def shutdown_handler(
    signum,
    frame,
):
    """Handle shutdown signals."""
    logger.info(
        "🛑 Shutting down hosting service..."
    )

    try:
        for bot_id in list(
            bot_manager.processes.keys()
        ):
            try:
                bot_manager.stop_bot(
                    bot_id
                )
            except Exception as e:
                logger.error(
                    "Error stopping %s: %s",
                    bot_id,
                    e,
                )

    except Exception as e:
        logger.error(
            "Shutdown cleanup error: %s",
            e,
        )

    logger.info(
        "✅ Shutdown complete."
    )

    sys.exit(0)


# ============================================================
# MAIN
# ============================================================

def main():
    """Main application entry point."""

    # --------------------------------------------------------
    # Signal handlers
    # --------------------------------------------------------

    signal.signal(
        signal.SIGINT,
        shutdown_handler,
    )

    signal.signal(
        signal.SIGTERM,
        shutdown_handler,
    )

    # --------------------------------------------------------
    # Telegram application
    # --------------------------------------------------------

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commands
    # --------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "deploy",
            deploy,
        )
    )

    app.add_handler(
        CommandHandler(
            "list",
            list_bots,
        )
    )

    app.add_handler(
        CommandHandler(
            "logs",
            logs_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "stop",
            stop_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "startbot",
            start_bot_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "delete",
            delete_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    # --------------------------------------------------------
    # Token messages
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_token,
        )
    )

    # --------------------------------------------------------
    # File uploads
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_file,
        )
    )

    # --------------------------------------------------------
    # Inline buttons
    # --------------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            bot_action,
        )
    )

    # --------------------------------------------------------
    # Errors
    # --------------------------------------------------------

    app.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # Startup logs
    # --------------------------------------------------------

    logger.info(
        "🤖 Bot Hosting Service Started!"
    )

    logger.info(
        "👤 Normal user limit: %s bots",
        MAX_BOTS_PER_USER,
    )

    logger.info(
        "👑 Admin hosting: UNLIMITED"
    )

    logger.info(
        "📁 Uploads: %s",
        UPLOAD_DIR,
    )

    logger.info(
        "📁 Bots: %s",
        BOTS_DIR,
    )

    logger.info(
        "📁 Logs: %s",
        LOGS_DIR,
    )

    logger.info(
        "🟢 Supported uploads: .py, .js, .php, .zip"
    )

    logger.info(
        "✅ Ready to host bots!"
    )

    # --------------------------------------------------------
    # Polling
    # --------------------------------------------------------

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
