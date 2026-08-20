import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

# Use /tmp for Railway, local directory for development
if os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('RENDER'):
    DB_PATH = os.path.join('/tmp', 'bots.db')
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bots.db")

def get_db():
    """Get database connection"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_db():
    """Initialize database tables"""
    try:
        conn = get_db()
        if not conn:
            logger.error("Failed to connect to database")
            return
        
        c = conn.cursor()
        
        # Bots table
        c.execute('''
            CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                bot_token TEXT,
                bot_type TEXT,
                main_file TEXT,
                status TEXT,
                process_id TEXT,
                created_at TIMESTAMP,
                last_started TIMESTAMP,
                last_stopped TIMESTAMP,
                error_message TEXT
            )
        ''')
        
        # Users table for quotas
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                max_bots INTEGER DEFAULT 5,
                created_at TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database init error: {e}")

def add_bot(bot_id: str, user_id: int, bot_token: str, bot_type: str, main_file: str):
    """Add new bot to database"""
    try:
        conn = get_db()
        if not conn:
            return False
        
        c = conn.cursor()
        c.execute('''
            INSERT INTO bots (id, user_id, bot_token, bot_type, main_file, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (bot_id, user_id, bot_token, bot_type, main_file, 'stopped', datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"✅ Bot {bot_id} added to database")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to add bot: {e}")
        return False

def update_bot_status(bot_id: str, status: str, process_id: str = None, error: str = None):
    """Update bot status"""
    try:
        conn = get_db()
        if not conn:
            return
        
        c = conn.cursor()
        
        updates = []
        params = []
        
        updates.append("status = ?")
        params.append(status)
        
        if process_id is not None:
            updates.append("process_id = ?")
            params.append(process_id)
        
        if error is not None:
            updates.append("error_message = ?")
            params.append(error)
        
        if status == 'running':
            updates.append("last_started = ?")
            params.append(datetime.now())
        elif status == 'stopped':
            updates.append("last_stopped = ?")
            params.append(datetime.now())
        
        params.append(bot_id)
        
        query = f"UPDATE bots SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
        conn.commit()
        conn.close()
        logger.info(f"✅ Bot {bot_id} status updated to {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update status: {e}")

def get_user_bots(user_id: int) -> List[Dict]:
    """Get all bots for a user"""
    try:
        conn = get_db()
        if not conn:
            return []
        
        c = conn.cursor()
        c.execute("SELECT * FROM bots WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        bots = [dict(row) for row in c.fetchall()]
        conn.close()
        return bots
    except Exception as e:
        logger.error(f"❌ Failed to get user bots: {e}")
        return []

def get_bot(bot_id: str) -> Optional[Dict]:
    """Get bot by ID"""
    try:
        conn = get_db()
        if not conn:
            return None
        
        c = conn.cursor()
        c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
        bot = c.fetchone()
        conn.close()
        if bot:
            return dict(bot)
        return None
    except Exception as e:
        logger.error(f"❌ Failed to get bot: {e}")
        return None

def delete_bot(bot_id: str):
    """Delete bot from database"""
    try:
        conn = get_db()
        if not conn:
            return
        
        c = conn.cursor()
        c.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        conn.commit()
        conn.close()
        logger.info(f"✅ Bot {bot_id} deleted from database")
    except Exception as e:
        logger.error(f"❌ Failed to delete bot: {e}")

def get_user_bot_count(user_id: int) -> int:
    """Get number of bots a user has"""
    try:
        conn = get_db()
        if not conn:
            return 0
        
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as count FROM bots WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result['count'] if result else 0
    except Exception as e:
        logger.error(f"❌ Failed to get bot count: {e}")
        return 0

def get_user_max_bots(user_id: int) -> int:
    """Get max bots allowed for user"""
    try:
        conn = get_db()
        if not conn:
            return 5
        
        c = conn.cursor()
        c.execute("SELECT max_bots FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result['max_bots'] if result else 5
    except Exception as e:
        logger.error(f"❌ Failed to get max bots: {e}")
        return 5

def create_or_update_user(user_id: int, max_bots: int = 5):
    """Create or update user"""
    try:
        conn = get_db()
        if not conn:
            return
        
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO users (user_id, max_bots, created_at)
            VALUES (?, ?, COALESCE((SELECT created_at FROM users WHERE user_id = ?), ?))
        ''', (user_id, max_bots, user_id, datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"✅ User {user_id} created/updated")
    except Exception as e:
        logger.error(f"❌ Failed to create/update user: {e}")

def cleanup_stale_processes():
    """Clean up stale processes from database"""
    try:
        conn = get_db()
        if not conn:
            return
        
        c = conn.cursor()
        # Mark all running bots as stopped (they will be restarted if needed)
        c.execute("UPDATE bots SET status = 'stopped' WHERE status = 'running'")
        conn.commit()
        conn.close()
        logger.info("✅ Cleaned up stale processes")
    except Exception as e:
        logger.error(f"❌ Failed to cleanup processes: {e}")
