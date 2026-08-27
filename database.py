import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"):
    DB_PATH = os.path.join("/tmp", "bots.db")
else:
    DB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "bots.db"
    )


# ============================================================
# DEFAULT SETTINGS
# ============================================================

# Normal users get 30 bots by default.
DEFAULT_MAX_BOTS = 30


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db():
    """Get database connection."""
    try:
        conn = sqlite3.connect(
            DB_PATH,
            timeout=30
        )

        conn.row_factory = sqlite3.Row

        return conn

    except Exception as e:
        logger.error(
            f"Database connection error: {e}"
        )
        return None


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def init_db():
    """Initialize database tables."""

    try:
        conn = get_db()

        if not conn:
            logger.error(
                "Failed to connect to database"
            )
            return False

        c = conn.cursor()

        # ----------------------------------------------------
        # Bots table
        # ----------------------------------------------------

        c.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                bot_token TEXT,
                bot_type TEXT,
                main_file TEXT,
                status TEXT DEFAULT 'stopped',
                process_id TEXT,
                created_at TIMESTAMP,
                last_started TIMESTAMP,
                last_stopped TIMESTAMP,
                error_message TEXT
            )
        """)

        # ----------------------------------------------------
        # Users table
        # ----------------------------------------------------

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                max_bots INTEGER DEFAULT 30,
                created_at TIMESTAMP
            )
        """)

        # ----------------------------------------------------
        # Indexes
        # ----------------------------------------------------

        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_bots_user_id
            ON bots(user_id)
        """)

        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_bots_status
            ON bots(status)
        """)

        conn.commit()

        # ----------------------------------------------------
        # Database migration
        # ----------------------------------------------------

        migrate_database(conn)

        conn.close()

        logger.info(
            "✅ Database initialized successfully"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Database init error: {e}"
        )
        return False


# ============================================================
# DATABASE MIGRATION
# ============================================================

def migrate_database(conn=None):
    """
    Update old installations.

    Existing users that previously had the default limit of
    5 are changed to the new default of 30.

    Custom limits are preserved where possible.
    """

    close_connection = False

    try:
        if conn is None:
            conn = get_db()
            close_connection = True

        if not conn:
            return False

        c = conn.cursor()

        # ----------------------------------------------------
        # Check users table
        # ----------------------------------------------------

        c.execute(
            "PRAGMA table_info(users)"
        )

        columns = [
            row["name"]
            for row in c.fetchall()
        ]

        if "max_bots" not in columns:
            c.execute("""
                ALTER TABLE users
                ADD COLUMN max_bots INTEGER DEFAULT 30
            """)

        # ----------------------------------------------------
        # Upgrade old default 5 → 30
        # ----------------------------------------------------

        c.execute("""
            UPDATE users
            SET max_bots = ?
            WHERE max_bots = 5
        """, (DEFAULT_MAX_BOTS,))

        conn.commit()

        if close_connection:
            conn.close()

        logger.info(
            "✅ Database migration completed"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Database migration error: {e}"
        )

        if close_connection and conn:
            try:
                conn.close()
            except Exception:
                pass

        return False


# ============================================================
# BOT MANAGEMENT
# ============================================================

def add_bot(
    bot_id: str,
    user_id: int,
    bot_token: str,
    bot_type: str,
    main_file: str
):
    """Add a new bot to the database."""

    try:
        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        now = datetime.now()

        c.execute("""
            INSERT INTO bots (
                id,
                user_id,
                bot_token,
                bot_type,
                main_file,
                status,
                process_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bot_id,
            user_id,
            bot_token,
            bot_type,
            main_file,
            "stopped",
            None,
            now
        ))

        conn.commit()
        conn.close()

        logger.info(
            f"✅ Bot {bot_id} added to database"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Failed to add bot: {e}"
        )
        return False


def update_bot_status(
    bot_id: str,
    status: str,
    process_id: str = None,
    error: str = None
):
    """Update bot status."""

    try:
        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        updates = []
        params = []

        # Status
        updates.append("status = ?")
        params.append(status)

        # Process ID
        if process_id is not None:
            updates.append("process_id = ?")
            params.append(str(process_id))

        # Error
        if error is not None:
            updates.append("error_message = ?")
            params.append(str(error))

        # Started
        if status in ("running", "online"):
            updates.append("last_started = ?")
            params.append(datetime.now())

        # Stopped
        elif status == "stopped":
            updates.append("last_stopped = ?")
            params.append(datetime.now())

        params.append(bot_id)

        query = f"""
            UPDATE bots
            SET {', '.join(updates)}
            WHERE id = ?
        """

        c.execute(
            query,
            params
        )

        conn.commit()
        conn.close()

        logger.info(
            f"✅ Bot {bot_id} status updated to {status}"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Failed to update status: {e}"
        )
        return False


def get_bot(
    bot_id: str
) -> Optional[Dict]:
    """Get a bot by ID."""

    try:
        conn = get_db()

        if not conn:
            return None

        c = conn.cursor()

        c.execute(
            """
            SELECT *
            FROM bots
            WHERE id = ?
            """,
            (bot_id,)
        )

        row = c.fetchone()

        conn.close()

        if row:
            return dict(row)

        return None

    except Exception as e:
        logger.error(
            f"❌ Failed to get bot: {e}"
        )
        return None


def get_user_bots(
    user_id: int
) -> List[Dict]:
    """Get all bots belonging to a user."""

    try:
        conn = get_db()

        if not conn:
            return []

        c = conn.cursor()

        c.execute(
            """
            SELECT *
            FROM bots
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,)
        )

        bots = [
            dict(row)
            for row in c.fetchall()
        ]

        conn.close()

        return bots

    except Exception as e:
        logger.error(
            f"❌ Failed to get user bots: {e}"
        )
        return []


def get_all_bots() -> List[Dict]:
    """Get every bot in the database."""

    try:
        conn = get_db()

        if not conn:
            return []

        c = conn.cursor()

        c.execute("""
            SELECT *
            FROM bots
            ORDER BY created_at DESC
        """)

        bots = [
            dict(row)
            for row in c.fetchall()
        ]

        conn.close()

        return bots

    except Exception as e:
        logger.error(
            f"❌ Failed to get all bots: {e}"
        )
        return []


def get_bots_by_status(
    status: str
) -> List[Dict]:
    """Get bots by status."""

    try:
        conn = get_db()

        if not conn:
            return []

        c = conn.cursor()

        c.execute(
            """
            SELECT *
            FROM bots
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status,)
        )

        bots = [
            dict(row)
            for row in c.fetchall()
        ]

        conn.close()

        return bots

    except Exception as e:
        logger.error(
            f"❌ Failed to get bots by status: {e}"
        )
        return []


def delete_bot(
    bot_id: str
):
    """Delete bot from database."""

    try:
        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        c.execute(
            """
            DELETE FROM bots
            WHERE id = ?
            """,
            (bot_id,)
        )

        deleted = c.rowcount > 0

        conn.commit()
        conn.close()

        if deleted:
            logger.info(
                f"✅ Bot {bot_id} deleted from database"
            )

        return deleted

    except Exception as e:
        logger.error(
            f"❌ Failed to delete bot: {e}"
        )
        return False


# ============================================================
# BOT COUNTS
# ============================================================

def get_user_bot_count(
    user_id: int
) -> int:
    """Get number of bots belonging to a user."""

    try:
        conn = get_db()

        if not conn:
            return 0

        c = conn.cursor()

        c.execute(
            """
            SELECT COUNT(*) AS count
            FROM bots
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = c.fetchone()

        conn.close()

        if result:
            return int(result["count"])

        return 0

    except Exception as e:
        logger.error(
            f"❌ Failed to get bot count: {e}"
        )
        return 0


def get_total_bot_count() -> int:
    """Get total number of hosted bots."""

    try:
        conn = get_db()

        if not conn:
            return 0

        c = conn.cursor()

        c.execute(
            "SELECT COUNT(*) AS count FROM bots"
        )

        result = c.fetchone()

        conn.close()

        return (
            int(result["count"])
            if result
            else 0
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to get total bot count: {e}"
        )
        return 0


def get_running_bot_count() -> int:
    """Get number of running bots."""

    try:
        conn = get_db()

        if not conn:
            return 0

        c = conn.cursor()

        c.execute("""
            SELECT COUNT(*) AS count
            FROM bots
            WHERE status IN ('running', 'online')
        """)

        result = c.fetchone()

        conn.close()

        return (
            int(result["count"])
            if result
            else 0
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to get running bot count: {e}"
        )
        return 0


def get_stopped_bot_count() -> int:
    """Get number of stopped bots."""

    try:
        conn = get_db()

        if not conn:
            return 0

        c = conn.cursor()

        c.execute("""
            SELECT COUNT(*) AS count
            FROM bots
            WHERE status = 'stopped'
        """)

        result = c.fetchone()

        conn.close()

        return (
            int(result["count"])
            if result
            else 0
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to get stopped bot count: {e}"
        )
        return 0


# ============================================================
# USER MANAGEMENT
# ============================================================

def create_or_update_user(
    user_id: int,
    max_bots: int = DEFAULT_MAX_BOTS
):
    """
    Create a user if they don't exist.

    Existing users keep their configured limit.
    New users receive the default 30-bot limit.
    """

    try:
        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        # Check existing user.
        c.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        existing = c.fetchone()

        if existing:
            # Do NOT reset a user's custom quota.
            conn.close()

            logger.info(
                f"✅ User {user_id} already exists"
            )

            return True

        # Create new user.
        c.execute(
            """
            INSERT INTO users (
                user_id,
                max_bots,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                max_bots,
                datetime.now()
            )
        )

        conn.commit()
        conn.close()

        logger.info(
            f"✅ User {user_id} created "
            f"with {max_bots} bot limit"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Failed to create/update user: {e}"
        )
        return False


def get_user(
    user_id: int
) -> Optional[Dict]:
    """Get user information."""

    try:
        conn = get_db()

        if not conn:
            return None

        c = conn.cursor()

        c.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        row = c.fetchone()

        conn.close()

        if row:
            return dict(row)

        return None

    except Exception as e:
        logger.error(
            f"❌ Failed to get user: {e}"
        )
        return None


def get_all_users() -> List[Dict]:
    """Get all registered users."""

    try:
        conn = get_db()

        if not conn:
            return []

        c = conn.cursor()

        c.execute("""
            SELECT *
            FROM users
            ORDER BY created_at DESC
        """)

        users = [
            dict(row)
            for row in c.fetchall()
        ]

        conn.close()

        return users

    except Exception as e:
        logger.error(
            f"❌ Failed to get all users: {e}"
        )
        return []


def get_user_count() -> int:
    """Get total number of users."""

    try:
        conn = get_db()

        if not conn:
            return 0

        c = conn.cursor()

        c.execute(
            "SELECT COUNT(*) AS count FROM users"
        )

        result = c.fetchone()

        conn.close()

        return (
            int(result["count"])
            if result
            else 0
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to get user count: {e}"
        )
        return 0


def get_user_max_bots(
    user_id: int
) -> int:
    """Get maximum bots allowed for a user."""

    try:
        conn = get_db()

        if not conn:
            return DEFAULT_MAX_BOTS

        c = conn.cursor()

        c.execute(
            """
            SELECT max_bots
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = c.fetchone()

        conn.close()

        if result:
            return int(result["max_bots"])

        # User may not exist yet.
        return DEFAULT_MAX_BOTS

    except Exception as e:
        logger.error(
            f"❌ Failed to get max bots: {e}"
        )
        return DEFAULT_MAX_BOTS


def set_user_max_bots(
    user_id: int,
    max_bots: int
):
    """Change a user's hosting limit."""

    try:
        max_bots = int(max_bots)

        if max_bots < 0:
            return False

        # Make sure user exists.
        create_or_update_user(
            user_id
        )

        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        c.execute(
            """
            UPDATE users
            SET max_bots = ?
            WHERE user_id = ?
            """,
            (
                max_bots,
                user_id
            )
        )

        conn.commit()
        conn.close()

        logger.info(
            f"✅ User {user_id} limit "
            f"changed to {max_bots}"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Failed to set user limit: {e}"
        )
        return False


# ============================================================
# ADMIN STATISTICS
# ============================================================

def get_statistics() -> Dict:
    """Return general hosting statistics."""

    return {
        "users": get_user_count(),
        "bots": get_total_bot_count(),
        "running": get_running_bot_count(),
        "stopped": get_stopped_bot_count(),
    }


# ============================================================
# CLEANUP
# ============================================================

def cleanup_stale_processes():
    """
    Mark bots that were running before a restart as stopped.

    The actual processes disappear when the hosting service
    shuts down/restarts.
    """

    try:
        conn = get_db()

        if not conn:
            return False

        c = conn.cursor()

        c.execute("""
            UPDATE bots
            SET
                status = 'stopped',
                process_id = NULL
            WHERE status IN ('running', 'online')
        """)

        affected = c.rowcount

        conn.commit()
        conn.close()

        logger.info(
            f"✅ Cleaned up {affected} stale processes"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ Failed to cleanup processes: {e}"
        )
        return False


# ============================================================
# DATABASE STARTUP
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s - "
            "%(levelname)s - "
            "%(message)s"
        )
    )

    if init_db():
        print("✅ Database ready.")
        print(
            f"👤 Default user limit: "
            f"{DEFAULT_MAX_BOTS}"
      )
