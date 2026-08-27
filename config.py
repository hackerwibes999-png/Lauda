import os
import logging
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

# Load .env file if it exists.
# Useful for local development and Termux.
load_dotenv()


# ============================================================
# BOT TOKEN
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN environment variable is required!"
    )


# ============================================================
# ADMIN IDS
# ============================================================

ADMIN_IDS = []

admin_ids_str = os.getenv(
    "ADMIN_IDS",
    ""
).strip()

if admin_ids_str:
    for admin_id in admin_ids_str.split(","):
        admin_id = admin_id.strip()

        if not admin_id:
            continue

        try:
            ADMIN_IDS.append(int(admin_id))
        except ValueError:
            logging.warning(
                "Invalid ADMIN_IDS value ignored: %s",
                admin_id
            )


# ============================================================
# HOSTING LIMITS
# ============================================================

# Normal users can host up to 30 bots.
MAX_BOTS_PER_USER = int(
    os.getenv(
        "MAX_BOTS_PER_USER",
        "30"
    )
)

# Admins are unlimited.
ADMIN_UNLIMITED = os.getenv(
    "ADMIN_UNLIMITED",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)


# ============================================================
# BASE DIRECTORY
# ============================================================

# Railway provides RAILWAY_ENVIRONMENT.
#
# For Railway:
#     /tmp
#
# For Termux/local:
#     directory containing this config.py
#
# NOTE:
# /tmp storage on many hosting platforms is temporary.
# For permanent bot data, use persistent storage/volume.
#
if os.getenv("RAILWAY_ENVIRONMENT"):
    BASE_DIR = "/tmp"
else:
    BASE_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )


# ============================================================
# HOSTING DIRECTORIES
# ============================================================

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "uploads"
)

BOTS_DIR = os.path.join(
    BASE_DIR,
    "bots"
)

LOGS_DIR = os.path.join(
    BASE_DIR,
    "logs"
)


# ============================================================
# CREATE DIRECTORIES
# ============================================================

for directory in (
    UPLOAD_DIR,
    BOTS_DIR,
    LOGS_DIR,
):
    os.makedirs(
        directory,
        exist_ok=True
    )


# ============================================================
# FILE UPLOAD SETTINGS
# ============================================================

# Maximum upload size: 10 MB.
MAX_FILE_SIZE = 10 * 1024 * 1024


# Supported bot/project files.
#
# .py   = Python
# .js   = JavaScript / Node.js
# .php  = PHP
# .zip  = Complete project
#
SUPPORTED_EXTENSIONS = [
    ".py",
    ".js",
    ".php",
    ".zip",
]


# ============================================================
# RUNTIME SETTINGS
# ============================================================

# These are the supported runtimes advertised by the hosting
# service.
#
# Actual execution is performed by manager.py.

SUPPORTED_RUNTIMES = [
    "python",
    "nodejs",
    "php",
]


# Runtime executable names.
#
# manager.py can use these values when launching processes.

PYTHON_COMMAND = os.getenv(
    "PYTHON_COMMAND",
    "python3"
)

NODE_COMMAND = os.getenv(
    "NODE_COMMAND",
    "node"
)

PHP_COMMAND = os.getenv(
    "PHP_COMMAND",
    "php"
)


# ============================================================
# DEPENDENCY FILES
# ============================================================

# Python
PYTHON_DEPENDENCY_FILE = "requirements.txt"

# Node.js
NODE_DEPENDENCY_FILE = "package.json"

# PHP
PHP_DEPENDENCY_FILE = "composer.json"


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO"
).upper()


# Configure basic logging.
logging.basicConfig(
    level=getattr(
        logging,
        LOG_LEVEL,
        logging.INFO
    ),
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
)


# ============================================================
# DISPLAY / INFORMATION
# ============================================================

SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "Telegram Bot Hosting Service"
)

SERVICE_VERSION = os.getenv(
    "SERVICE_VERSION",
    "2.0.0"
)


# ============================================================
# SECURITY / PROCESS SETTINGS
# ============================================================

# Whether users are allowed to upload ZIP projects.
ALLOW_ZIP_UPLOADS = os.getenv(
    "ALLOW_ZIP_UPLOADS",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)

# Whether Python projects are allowed.
ALLOW_PYTHON = os.getenv(
    "ALLOW_PYTHON",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)

# Whether Node.js projects are allowed.
ALLOW_NODEJS = os.getenv(
    "ALLOW_NODEJS",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)

# Whether PHP projects are allowed.
ALLOW_PHP = os.getenv(
    "ALLOW_PHP",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)


# ============================================================
# STARTUP INFORMATION
# ============================================================

logging.info(
    "Hosting configuration loaded."
)

logging.info(
    "Normal user bot limit: %s",
    MAX_BOTS_PER_USER
)

logging.info(
    "Admin unlimited hosting: %s",
    ADMIN_UNLIMITED
)

logging.info(
    "Maximum file size: %s MB",
    MAX_FILE_SIZE // 1024 // 1024
)

logging.info(
    "Supported extensions: %s",
    ", ".join(SUPPORTED_EXTENSIONS)
)

logging.info(
    "Python command: %s",
    PYTHON_COMMAND
)

logging.info(
    "Node.js command: %s",
    NODE_COMMAND
)

logging.info(
    "PHP command: %s",
    PHP_COMMAND
)
