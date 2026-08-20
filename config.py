import os
from dotenv import load_dotenv
import logging

# Load .env file if exists (for local development)
load_dotenv()

# Get token from environment variable
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")

# Get admin IDs from environment
ADMIN_IDS = []
admin_ids_str = os.getenv('ADMIN_IDS', '')
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]

# Paths - Use /tmp for Railway
if os.getenv('RAILWAY_ENVIRONMENT'):
    BASE_DIR = '/tmp'
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
BOTS_DIR = os.path.join(BASE_DIR, "bots")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Create directories
for dir_path in [UPLOAD_DIR, BOTS_DIR, LOGS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
SUPPORTED_EXTENSIONS = ['.py', '.zip']

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
