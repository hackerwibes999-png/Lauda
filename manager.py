import os
import sys  # Added this import
import subprocess
import shutil
import zipfile
import json
import time
import signal
import requests
import logging
from pathlib import Path
from typing import Tuple, Optional
import uuid

from config import BOTS_DIR, LOGS_DIR

logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.bots_dir = BOTS_DIR
        self.logs_dir = LOGS_DIR
        self.processes = {}  # Store running processes
        
        # Ensure directories exist
        os.makedirs(self.bots_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
    
    def extract_and_prepare(self, file_path: str, bot_id: str) -> Tuple[bool, str, str]:
        """Extract uploaded file and prepare bot environment"""
        bot_folder = os.path.join(self.bots_dir, bot_id)
        os.makedirs(bot_folder, exist_ok=True)
        
        file_name = os.path.basename(file_path)
        dest_file = os.path.join(bot_folder, file_name)
        shutil.copy2(file_path, dest_file)
        
        if file_name.endswith('.zip'):
            try:
                with zipfile.ZipFile(dest_file, 'r') as zip_ref:
                    zip_ref.extractall(bot_folder)
                os.remove(dest_file)
            except Exception as e:
                return False, "", f"Failed to extract zip: {str(e)}"
        
        main_file = self._detect_main_file(bot_folder)
        if not main_file:
            return False, "", "No main file found (bot.py or main.py)"
        
        bot_type = 'python'
        
        success, error = self._install_dependencies(bot_folder)
        if not success:
            return False, "", f"Failed to install dependencies: {error}"
        
        return True, bot_type, main_file
    
    def _detect_main_file(self, folder: str) -> Optional[str]:
        """Detect main bot file"""
        possible_files = ['bot.py', 'main.py', 'app.py']
        for file in possible_files:
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                return file_path
        
        # Look for any .py file
        for file in os.listdir(folder):
            if file.endswith('.py'):
                return os.path.join(folder, file)
        return None
    
    def _install_dependencies(self, folder: str) -> Tuple[bool, str]:
        """Install Python dependencies"""
        try:
            req_file = os.path.join(folder, 'requirements.txt')
            if os.path.isfile(req_file):
                # Use sys.executable to get the current Python interpreter
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '-r', req_file, '--quiet'],
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    return False, result.stderr
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "Dependency installation timed out"
        except Exception as e:
            return False, str(e)
    
    def start_bot(self, bot_id: str, bot_type: str, main_file: str, bot_token: str) -> Tuple[bool, str, str]:
        """Start bot using subprocess"""
        bot_folder = os.path.join(self.bots_dir, bot_id)
        log_file = os.path.join(self.logs_dir, f"{bot_id}.log")
        
        env = os.environ.copy()
        env['BOT_TOKEN'] = bot_token
        
        try:
            # Open log file
            log_f = open(log_file, 'w')
            
            # Start process
            process = subprocess.Popen(
                [sys.executable, main_file],
                cwd=bot_folder,
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL
            )
            
            # Store process info
            self.processes[bot_id] = {
                'process': process,
                'pid': str(process.pid),
                'log_file': log_f
            }
            
            # Save PID to file
            pid_file = os.path.join(bot_folder, '.pid')
            with open(pid_file, 'w') as f:
                f.write(str(process.pid))
            
            return True, str(process.pid), ""
            
        except Exception as e:
            return False, "", str(e)
    
    def stop_bot(self, bot_id: str) -> Tuple[bool, str]:
        """Stop bot using PID"""
        try:
            # Try to stop using stored process
            if bot_id in self.processes:
                process = self.processes[bot_id]['process']
                log_file = self.processes[bot_id]['log_file']
                
                # Send SIGTERM
                try:
                    os.kill(process.pid, signal.SIGTERM)
                except:
                    pass
                
                # Wait for process to end
                try:
                    process.wait(timeout=5)
                except:
                    process.kill()
                
                log_file.close()
                del self.processes[bot_id]
                return True, ""
            
            # Try using PID file
            bot_folder = os.path.join(self.bots_dir, bot_id)
            pid_file = os.path.join(bot_folder, '.pid')
            if os.path.exists(pid_file):
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(1)
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
                
                os.remove(pid_file)
                return True, ""
            
            return False, "Bot not running"
        except Exception as e:
            return False, str(e)
    
    def restart_bot(self, bot_id: str) -> Tuple[bool, str]:
        """Restart bot"""
        from database import get_bot
        bot = get_bot(bot_id)
        if not bot:
            return False, "Bot not found"
        
        # Stop the bot
        self.stop_bot(bot_id)
        
        # Start it again
        return self.start_bot(
            bot_id, 
            bot['bot_type'], 
            bot['main_file'], 
            bot['bot_token']
        )
    
    def delete_bot(self, bot_id: str) -> Tuple[bool, str]:
        """Delete bot"""
        self.stop_bot(bot_id)
        
        bot_folder = os.path.join(self.bots_dir, bot_id)
        if os.path.exists(bot_folder):
            shutil.rmtree(bot_folder)
        
        log_file = os.path.join(self.logs_dir, f"{bot_id}.log")
        if os.path.exists(log_file):
            os.remove(log_file)
        
        return True, ""
    
    def get_logs(self, bot_id: str, lines: int = 50) -> str:
        """Get logs"""
        log_file = os.path.join(self.logs_dir, f"{bot_id}.log")
        if not os.path.exists(log_file):
            return "No logs found"
        
        try:
            with open(log_file, 'r') as f:
                content = f.read()
                lines_list = content.split('\n')
                return '\n'.join(lines_list[-lines:])
        except Exception as e:
            return f"Error reading logs: {str(e)}"
    
    def get_bot_status(self, bot_id: str) -> str:
        """Check if bot is running"""
        try:
            # Check using PID file
            bot_folder = os.path.join(self.bots_dir, bot_id)
            pid_file = os.path.join(bot_folder, '.pid')
            if os.path.exists(pid_file):
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process exists
                try:
                    os.kill(pid, 0)
                    return 'online'
                except:
                    return 'stopped'
            return 'stopped'
        except Exception as e:
            return 'unknown'
    
    def verify_bot_token(self, bot_token: str) -> Tuple[bool, str]:
        """Verify bot token"""
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    return True, data.get('result', {}).get('username', 'Unknown')
            return False, ""
        except Exception as e:
            return False, ""
