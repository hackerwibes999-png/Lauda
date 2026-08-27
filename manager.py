import os
import sys
import subprocess
import shutil
import zipfile
import time
import signal
import requests
import logging
from pathlib import Path
from typing import Tuple, Optional

from config import (
    BOTS_DIR,
    LOGS_DIR,
    PYTHON_COMMAND,
    NODE_COMMAND,
    PHP_COMMAND,
    ALLOW_PYTHON,
    ALLOW_NODEJS,
    ALLOW_PHP,
)

logger = logging.getLogger(__name__)


class BotManager:
    """
    Manage hosted Python, Node.js and PHP bots.
    """

    def __init__(self):
        self.bots_dir = BOTS_DIR
        self.logs_dir = LOGS_DIR

        # Running processes
        self.processes = {}

        os.makedirs(
            self.bots_dir,
            exist_ok=True
        )

        os.makedirs(
            self.logs_dir,
            exist_ok=True
        )

    # ========================================================
    # PREPARE BOT
    # ========================================================

    def extract_and_prepare(
        self,
        file_path: str,
        bot_id: str
    ) -> Tuple[bool, str, str]:

        bot_folder = os.path.join(
            self.bots_dir,
            bot_id
        )

        try:
            os.makedirs(
                bot_folder,
                exist_ok=True
            )

            file_name = os.path.basename(
                file_path
            )

            # ------------------------------------------------
            # ZIP PROJECT
            # ------------------------------------------------

            if file_name.lower().endswith(".zip"):

                if not self._safe_extract_zip(
                    file_path,
                    bot_folder
                ):
                    self._remove_directory(
                        bot_folder
                    )

                    return (
                        False,
                        "",
                        "Unsafe or invalid ZIP file."
                    )

            # ------------------------------------------------
            # DIRECT SOURCE FILE
            # ------------------------------------------------

            else:

                destination = os.path.join(
                    bot_folder,
                    file_name
                )

                shutil.copy2(
                    file_path,
                    destination
                )

            # ------------------------------------------------
            # Detect project root
            # ------------------------------------------------

            project_root = self._find_project_root(
                bot_folder
            )

            # ------------------------------------------------
            # Detect runtime
            # ------------------------------------------------

            bot_type = self._detect_bot_type(
                project_root
            )

            if not bot_type:
                self._remove_directory(
                    bot_folder
                )

                return (
                    False,
                    "",
                    "Could not detect supported bot type. "
                    "Supported: Python, Node.js and PHP."
                )

            # ------------------------------------------------
            # Check runtime enabled
            # ------------------------------------------------

            if bot_type == "python" and not ALLOW_PYTHON:
                return (
                    False,
                    "",
                    "Python hosting is disabled."
                )

            if bot_type == "nodejs" and not ALLOW_NODEJS:
                return (
                    False,
                    "",
                    "Node.js hosting is disabled."
                )

            if bot_type == "php" and not ALLOW_PHP:
                return (
                    False,
                    "",
                    "PHP hosting is disabled."
                )

            # ------------------------------------------------
            # Detect main file
            # ------------------------------------------------

            main_file = self._detect_main_file(
                project_root,
                bot_type
            )

            if not main_file:

                self._remove_directory(
                    bot_folder
                )

                return (
                    False,
                    "",
                    f"No main {bot_type} file found."
                )

            # ------------------------------------------------
            # Install dependencies
            # ------------------------------------------------

            success, error = self._install_dependencies(
                project_root,
                bot_type
            )

            if not success:

                self._remove_directory(
                    bot_folder
                )

                return (
                    False,
                    "",
                    f"Failed to install dependencies: {error}"
                )

            logger.info(
                "Prepared %s as %s",
                bot_id,
                bot_type
            )

            return (
                True,
                bot_type,
                main_file
            )

        except Exception as e:

            logger.exception(
                "Failed to prepare bot %s",
                bot_id
            )

            return (
                False,
                "",
                str(e)
            )

    # ========================================================
    # ZIP EXTRACTION
    # ========================================================

    def _safe_extract_zip(
        self,
        zip_path: str,
        destination: str
    ) -> bool:

        try:

            with zipfile.ZipFile(
                zip_path,
                "r"
            ) as zip_ref:

                destination_path = os.path.realpath(
                    destination
                )

                for member in zip_ref.infolist():

                    member_path = os.path.realpath(
                        os.path.join(
                            destination,
                            member.filename
                        )
                    )

                    # Prevent ZIP path traversal
                    if not (
                        member_path == destination_path
                        or member_path.startswith(
                            destination_path + os.sep
                        )
                    ):
                        logger.warning(
                            "Blocked unsafe ZIP entry: %s",
                            member.filename
                        )
                        return False

                zip_ref.extractall(
                    destination
                )

            return True

        except zipfile.BadZipFile:
            logger.error(
                "Invalid ZIP file: %s",
                zip_path
            )
            return False

        except Exception as e:
            logger.error(
                "ZIP extraction error: %s",
                e
            )
            return False

    # ========================================================
    # PROJECT ROOT
    # ========================================================

    def _find_project_root(
        self,
        folder: str
    ) -> str:

        try:

            entries = [
                x for x in os.listdir(folder)
                if x not in (
                    ".",
                    ".."
                )
            ]

            # If source files are directly inside folder
            for entry in entries:

                path = os.path.join(
                    folder,
                    entry
                )

                if os.path.isfile(path):
                    return folder

            # If ZIP created a single directory
            directories = []

            for entry in entries:

                path = os.path.join(
                    folder,
                    entry
                )

                if os.path.isdir(path):
                    directories.append(path)

            if len(directories) == 1:

                root = directories[0]

                # Make sure it contains project files
                if any(
                    os.path.isfile(
                        os.path.join(root, x)
                    )
                    for x in os.listdir(root)
                ):
                    return root

            return folder

        except Exception:
            return folder

    # ========================================================
    # DETECT BOT TYPE
    # ========================================================

    def _detect_bot_type(
        self,
        folder: str
    ) -> Optional[str]:

        # Python
        python_files = [
            "bot.py",
            "main.py",
            "app.py",
            "run.py"
        ]

        for filename in python_files:

            if os.path.isfile(
                os.path.join(
                    folder,
                    filename
                )
            ):
                return "python"

        # Node.js
        node_files = [
            "index.js",
            "bot.js",
            "main.js",
            "app.js",
            "server.js"
        ]

        for filename in node_files:

            if os.path.isfile(
                os.path.join(
                    folder,
                    filename
                )
            ):
                return "nodejs"

        # package.json
        if os.path.isfile(
            os.path.join(
                folder,
                "package.json"
            )
        ):
            return "nodejs"

        # PHP
        php_files = [
            "index.php",
            "bot.php",
            "main.php",
            "app.php"
        ]

        for filename in php_files:

            if os.path.isfile(
                os.path.join(
                    folder,
                    filename
                )
            ):
                return "php"

        return None

    # ========================================================
    # DETECT MAIN FILE
    # ========================================================

    def _detect_main_file(
        self,
        folder: str,
        bot_type: str
    ) -> Optional[str]:

        if bot_type == "python":

            possible_files = [
                "bot.py",
                "main.py",
                "app.py",
                "run.py"
            ]

            extension = ".py"

        elif bot_type == "nodejs":

            possible_files = [
                "index.js",
                "bot.js",
                "main.js",
                "app.js",
                "server.js"
            ]

            extension = ".js"

        elif bot_type == "php":

            possible_files = [
                "index.php",
                "bot.php",
                "main.php",
                "app.php"
            ]

            extension = ".php"

        else:
            return None

        # First check known filenames
        for filename in possible_files:

            path = os.path.join(
                folder,
                filename
            )

            if os.path.isfile(path):
                return path

        # ----------------------------------------------------
        # package.json main
        # ----------------------------------------------------

        if bot_type == "nodejs":

            package_json = os.path.join(
                folder,
                "package.json"
            )

            if os.path.isfile(package_json):

                try:

                    import json

                    with open(
                        package_json,
                        "r",
                        encoding="utf-8"
                    ) as f:

                        package_data = json.load(f)

                    main = package_data.get(
                        "main"
                    )

                    if main:

                        main_path = os.path.join(
                            folder,
                            main
                        )

                        if os.path.isfile(
                            main_path
                        ):
                            return main_path

                except Exception as e:

                    logger.warning(
                        "Could not read package.json: %s",
                        e
                    )

        # ----------------------------------------------------
        # Search recursively
        # ----------------------------------------------------

        for root, dirs, files in os.walk(folder):

            # Don't scan dependency folders
            dirs[:] = [
                d for d in dirs
                if d not in (
                    "node_modules",
                    ".git",
                    "__pycache__",
                    "vendor"
                )
            ]

            for filename in files:

                if filename.lower().endswith(
                    extension
                ):

                    return os.path.join(
                        root,
                        filename
                    )

        return None

    # ========================================================
    # DEPENDENCIES
    # ========================================================

    def _install_dependencies(
        self,
        folder: str,
        bot_type: str
    ) -> Tuple[bool, str]:

        try:

            # ------------------------------------------------
            # PYTHON
            # ------------------------------------------------

            if bot_type == "python":

                req_file = os.path.join(
                    folder,
                    "requirements.txt"
                )

                if os.path.isfile(req_file):

                    logger.info(
                        "Installing Python dependencies..."
                    )

                    result = subprocess.run(
                        [
                            PYTHON_COMMAND,
                            "-m",
                            "pip",
                            "install",
                            "-r",
                            req_file,
                            "--quiet"
                        ],
                        cwd=folder,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )

                    if result.returncode != 0:

                        return (
                            False,
                            result.stderr[-4000:]
                        )

            # ------------------------------------------------
            # NODE.JS
            # ------------------------------------------------

            elif bot_type == "nodejs":

                package_json = os.path.join(
                    folder,
                    "package.json"
                )

                if os.path.isfile(package_json):

                    logger.info(
                        "Installing Node.js dependencies..."
                    )

                    npm_command = (
                        "npm.cmd"
                        if os.name == "nt"
                        else "npm"
                    )

                    result = subprocess.run(
                        [
                            npm_command,
                            "install",
                            "--no-audit",
                            "--no-fund"
                        ],
                        cwd=folder,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                    if result.returncode != 0:

                        return (
                            False,
                            result.stderr[-4000:]
                        )

            # ------------------------------------------------
            # PHP
            # ------------------------------------------------

            elif bot_type == "php":

                composer_json = os.path.join(
                    folder,
                    "composer.json"
                )

                if os.path.isfile(
                    composer_json
                ):

                    logger.info(
                        "Installing PHP dependencies..."
                    )

                    composer_command = (
                        "composer.bat"
                        if os.name == "nt"
                        else "composer"
                    )

                    result = subprocess.run(
                        [
                            composer_command,
                            "install",
                            "--no-interaction",
                            "--no-progress"
                        ],
                        cwd=folder,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                    if result.returncode != 0:

                        return (
                            False,
                            result.stderr[-4000:]
                        )

            return True, ""

        except subprocess.TimeoutExpired:

            return (
                False,
                "Dependency installation timed out."
            )

        except FileNotFoundError as e:

            return (
                False,
                f"Required runtime/package manager not found: {e}"
            )

        except Exception as e:

            logger.exception(
                "Dependency installation failed"
            )

            return (
                False,
                str(e)
            )

    # ========================================================
    # START BOT
    # ========================================================

    def start_bot(
        self,
        bot_id: str,
        bot_type: str,
        main_file: str,
        bot_token: str
    ) -> Tuple[bool, str, str]:

        bot_folder = os.path.join(
            self.bots_dir,
            bot_id
        )

        log_file = os.path.join(
            self.logs_dir,
            f"{bot_id}.log"
        )

        if not os.path.isdir(bot_folder):

            return (
                False,
                "",
                "Bot directory does not exist."
            )

        if not os.path.isfile(main_file):

            return (
                False,
                "",
                "Main file does not exist."
            )

        # Stop existing process first
        if bot_id in self.processes:

            try:
                if self.processes[
                    bot_id
                ]["process"].poll() is None:

                    return (
                        False,
                        "",
                        "Bot is already running."
                    )

            except Exception:
                pass

        # ----------------------------------------------------
        # Environment
        # ----------------------------------------------------

        env = os.environ.copy()

        env["BOT_TOKEN"] = bot_token

        env["BOT_ID"] = bot_id

        env["PYTHONUNBUFFERED"] = "1"

        # ----------------------------------------------------
        # Runtime command
        # ----------------------------------------------------

        if bot_type == "python":

            command = [
                PYTHON_COMMAND,
                main_file
            ]

        elif bot_type == "nodejs":

            command = [
                NODE_COMMAND,
                main_file
            ]

        elif bot_type == "php":

            command = [
                PHP_COMMAND,
                main_file
            ]

        else:

            return (
                False,
                "",
                f"Unsupported bot type: {bot_type}"
            )

        # ----------------------------------------------------
        # Start
        # ----------------------------------------------------

        log_f = None

        try:

            log_f = open(
                log_file,
                "a",
                encoding="utf-8",
                buffering=1
            )

            log_f.write(
                "\n\n"
                + "=" * 60
                + "\n"
                + f"Bot started: {time.ctime()}\n"
                + f"Runtime: {bot_type}\n"
                + f"Command: {' '.join(command)}\n"
                + "=" * 60
                + "\n"
            )

            process = subprocess.Popen(
                command,
                cwd=bot_folder,
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )

            # Give process a moment to fail immediately
            time.sleep(1)

            if process.poll() is not None:

                return_code = process.returncode

                log_f.flush()
                log_f.close()

                return (
                    False,
                    "",
                    f"Bot exited immediately with code {return_code}. "
                    f"Check /logs {bot_id}."
                )

            self.processes[bot_id] = {
                "process": process,
                "pid": str(process.pid),
                "log_file": log_f
            }

            # PID file
            pid_file = os.path.join(
                bot_folder,
                ".pid"
            )

            with open(
                pid_file,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(
                    str(process.pid)
                )

            logger.info(
                "✅ Started bot %s with PID %s",
                bot_id,
                process.pid
            )

            return (
                True,
                str(process.pid),
                ""
            )

        except Exception as e:

            if log_f:

                try:
                    log_f.close()
                except Exception:
                    pass

            logger.exception(
                "Failed to start bot %s",
                bot_id
            )

            return (
                False,
                "",
                str(e)
            )

    # ========================================================
    # STOP BOT
    # ========================================================

    def stop_bot(
        self,
        bot_id: str
    ) -> Tuple[bool, str]:

        try:

            # ------------------------------------------------
            # In-memory process
            # ------------------------------------------------

            if bot_id in self.processes:

                process_info = self.processes[
                    bot_id
                ]

                process = process_info[
                    "process"
                ]

                log_file = process_info.get(
                    "log_file"
                )

                try:

                    if process.poll() is None:

                        process.terminate()

                        try:
                            process.wait(
                                timeout=5
                            )
                        except subprocess.TimeoutExpired:

                            process.kill()

                            try:
                                process.wait(
                                    timeout=3
                                )
                            except Exception:
                                pass

                except Exception as e:

                    logger.warning(
                        "Process termination error: %s",
                        e
                    )

                if log_file:

                    try:
                        log_file.write(
                            "\n"
                            + "=" * 60
                            + "\n"
                            + f"Bot stopped: {time.ctime()}\n"
                            + "=" * 60
                            + "\n"
                        )

                        log_file.close()

                    except Exception:
                        pass

                del self.processes[
                    bot_id
                ]

                self._remove_pid_file(
                    bot_id
                )

                return (
                    True,
                    ""
                )

            # ------------------------------------------------
            # PID file
            # ------------------------------------------------

            pid = self._read_pid(
                bot_id
            )

            if pid:

                try:

                    os.kill(
                        pid,
                        signal.SIGTERM
                    )

                    # Wait
                    for _ in range(20):

                        try:
                            os.kill(
                                pid,
                                0
                            )
                            time.sleep(0.25)

                        except ProcessLookupError:
                            break

                        except PermissionError:
                            break

                    # Force kill if still alive
                    try:

                        os.kill(
                            pid,
                            signal.SIGKILL
                        )

                    except Exception:
                        pass

                except ProcessLookupError:
                    pass

                except Exception as e:

                    logger.warning(
                        "PID stop error: %s",
                        e
                    )

                self._remove_pid_file(
                    bot_id
                )

                return (
                    True,
                    ""
                )

            return (
                False,
                "Bot not running."
            )

        except Exception as e:

            logger.exception(
                "Failed to stop bot %s",
                bot_id
            )

            return (
                False,
                str(e)
            )

    # ========================================================
    # RESTART BOT
    # ========================================================

    def restart_bot(
        self,
        bot_id: str
    ) -> Tuple[bool, str]:

        from database import get_bot

        bot = get_bot(
            bot_id
        )

        if not bot:

            return (
                False,
                "Bot not found."
            )

        self.stop_bot(
            bot_id
        )

        return self.start_bot(
            bot_id,
            bot["bot_type"],
            bot["main_file"],
            bot["bot_token"]
        )[0:2]

    # ========================================================
    # DELETE BOT
    # ========================================================

    def delete_bot(
        self,
        bot_id: str
    ) -> Tuple[bool, str]:

        try:

            # Stop process
            self.stop_bot(
                bot_id
            )

            # Remove bot directory
            bot_folder = os.path.join(
                self.bots_dir,
                bot_id
            )

            if os.path.exists(
                bot_folder
            ):

                shutil.rmtree(
                    bot_folder
                )

            # Remove logs
            log_file = os.path.join(
                self.logs_dir,
                f"{bot_id}.log"
            )

            if os.path.exists(
                log_file
            ):

                os.remove(
                    log_file
                )

            logger.info(
                "✅ Deleted bot %s",
                bot_id
            )

            return (
                True,
                ""
            )

        except Exception as e:

            logger.exception(
                "Failed to delete bot %s",
                bot_id
            )

            return (
                False,
                str(e)
            )

    # ========================================================
    # LOGS
    # ========================================================

    def get_logs(
        self,
        bot_id: str,
        lines: int = 50
    ) -> str:

        log_file = os.path.join(
            self.logs_dir,
            f"{bot_id}.log"
        )

        if not os.path.isfile(
            log_file
        ):

            return "No logs found."

        try:

            with open(
                log_file,
                "r",
                encoding="utf-8",
                errors="replace"
            ) as f:

                content = f.readlines()

            if not content:

                return "No logs found."

            return "".join(
                content[-lines:]
            )

        except Exception as e:

            return (
                f"Error reading logs: {e}"
            )

    # ========================================================
    # STATUS
    # ========================================================

    def get_bot_status(
        self,
        bot_id: str
    ) -> str:

        try:

            # First check in-memory process
            if bot_id in self.processes:

                process = self.processes[
                    bot_id
                ]["process"]

                if process.poll() is None:
                    return "online"

                return "stopped"

            # Check PID file
            pid = self._read_pid(
                bot_id
            )

            if not pid:
                return "stopped"

            try:

                os.kill(
                    pid,
                    0
                )

                return "online"

            except ProcessLookupError:

                self._remove_pid_file(
                    bot_id
                )

                return "stopped"

            except PermissionError:

                return "online"

            except Exception:

                return "stopped"

        except Exception as e:

            logger.error(
                "Status check error for %s: %s",
                bot_id,
                e
            )

            return "unknown"

    # ========================================================
    # TOKEN VERIFICATION
    # ========================================================

    def verify_bot_token(
        self,
        bot_token: str
    ) -> Tuple[bool, str]:

        try:

            bot_token = bot_token.strip()

            if not bot_token:
                return False, ""

            # Basic Telegram token format check
            if ":" not in bot_token:
                return False, ""

            url = (
                "https://api.telegram.org/"
                f"bot{bot_token}/getMe"
            )

            response = requests.get(
                url,
                timeout=10
            )

            if response.status_code != 200:
                return False, ""

            data = response.json()

            if data.get("ok"):

                username = (
                    data.get(
                        "result",
                        {}
                    ).get(
                        "username",
                        "Unknown"
                    )
                )

                return (
                    True,
                    username
                )

            return False, ""

        except requests.RequestException as e:

            logger.error(
                "Telegram API verification error: %s",
                e
            )

            return False, ""

        except Exception as e:

            logger.error(
                "Token verification error: %s",
                e
            )

            return False, ""

    # ========================================================
    # PID HELPERS
    # ========================================================

    def _read_pid(
        self,
        bot_id: str
    ) -> Optional[int]:

        try:

            pid_file = os.path.join(
                self.bots_dir,
                bot_id,
                ".pid"
            )

            if not os.path.isfile(
                pid_file
            ):
                return None

            with open(
                pid_file,
                "r",
                encoding="utf-8"
            ) as f:

                value = f.read().strip()

            pid = int(value)

            if pid <= 0:
                return None

            return pid

        except Exception:

            return None

    def _remove_pid_file(
        self,
        bot_id: str
    ):

        try:

            pid_file = os.path.join(
                self.bots_dir,
                bot_id,
                ".pid"
            )

            if os.path.exists(
                pid_file
            ):

                os.remove(
                    pid_file
                )

        except Exception:
            pass

    # ========================================================
    # CLEANUP
    # ========================================================

    def cleanup_processes(self):

        for bot_id in list(
            self.processes.keys()
        ):

            try:

                self.stop_bot(
                    bot_id
                )

            except Exception as e:

                logger.error(
                    "Error stopping %s: %s",
                    bot_id,
                    e
                )

        self.processes.clear()

    # ========================================================
    # REMOVE DIRECTORY
    # ========================================================

    @staticmethod
    def _remove_directory(
        path: str
    ):

        try:

            if os.path.exists(
                path
            ):
                shutil.rmtree(
                    path
                )

        except Exception as e:

            logger.error(
                "Failed to remove directory %s: %s",
                path,
                e
            )
