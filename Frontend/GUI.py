"""
gui.py — Jarvis AI Frontend
===========================
Changes vs original:
  • The 📷 camera button now shows an INLINE virtual keyboard inside the
    main window (index 2 of the root QStackedWidget) instead of launching
    a separate subprocess window.
  • CameraKeyboardWidget (CameraKeyboardWidget.py) must sit next to this file.
  • Key-presses and ⏎ from the camera keyboard are wired to the same
    SetUserQuery / SetMicrophoneStatus pipeline as the text field and mic button.
"""

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QStackedWidget, QWidget,
    QLineEdit, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QLabel, QSizePolicy
)
from PyQt5.QtGui import (
    QIcon, QPainter, QMovie, QColor, QTextCharFormat,
    QFont, QPixmap, QTextBlockFormat
)
from PyQt5.QtCore import Qt, QSize, QTimer
from dotenv import dotenv_values
import sys
import os

# ── Resolve paths relative to this file so the app works regardless of cwd ───
_GUI_DIR     = os.path.dirname(os.path.abspath(__file__))          # Frontend/
_ROOT_DIR    = os.path.abspath(os.path.join(_GUI_DIR, ".."))       # project root
_BACKEND_DIR = os.path.join(_ROOT_DIR, "Backend")                  # Backend/

for _p in (_ROOT_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Inline camera keyboard ────────────────────────────────────────────────────
from CameraKeyboardWidget import CameraKeyboardWidget
from YouTubeGestureController import YouTubeGestureWidget

# Load .env from project root (works regardless of cwd)
_ENV_PATH = os.path.join(_ROOT_DIR, ".env")
env_vars = dotenv_values(_ENV_PATH)
Assistantname = env_vars.get("Assistantname", "Jarvis")
old_chat_message = ""
TempDirPath     = os.path.join(_ROOT_DIR, "Frontend", "Files")
GraphicsDirPath = os.path.join(_ROOT_DIR, "Frontend", "Graphics")

# Ensure required temp files exist
for _fname in ("Mic.data", "Status.data", "Responses.data",
               "Database.data", "UserQuery.data"):
    _fpath = os.path.join(TempDirPath, _fname)
    if not os.path.exists(_fpath):
        open(_fpath, "w", encoding="utf-8").close()

TOP_BAR_HEIGHT = 50  # Must match CustomTopBar.setFixedHeight

# ─────────────────────────────────────────────────────────────────────────────
#  Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def AnswerModifier(Answer):
    lines = Answer.split('\n')
    non_empty_lines = [line for line in lines if line.strip()]
    return '\n'.join(non_empty_lines)

def QueryModifier(Query):
    new_query = Query.lower().strip()
    query_words = new_query.split()
    if not query_words:
        return ""
    question_words = ["how", "what", "who", "where", "when", "why", "which",
                      "whose", "whom", "can you", "what's", "where's", "how's"]
    if any(word + " " in new_query for word in question_words):
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "?"
        else:
            new_query += "?"
    else:
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "."
        else:
            new_query += "."
    return new_query.capitalize()

def SetMicrophoneStatus(Command):
    with open(rf'{TempDirPath}\Mic.data', "w", encoding='utf-8') as file:
        file.write(Command)

def GetMicrophoneStatus():
    with open(rf'{TempDirPath}\Mic.data', "r", encoding='utf-8') as file:
        return file.read()

def SetAssistantStatus(Status):
    with open(rf'{TempDirPath}\Status.data', "w", encoding='utf-8') as file:
        file.write(Status)

def GetAssistantStatus():
    with open(rf'{TempDirPath}\Status.data', "r", encoding='utf-8') as file:
        return file.read()

def MicButtonInitialed():
    SetMicrophoneStatus("False")

def MicButtonClosed():
    SetMicrophoneStatus("True")

def GraphicsDirectoryPath(Filename):
    return rf'{GraphicsDirPath}\{Filename}'

def TempDirectoryPath(Filename):
    return rf'{TempDirPath}\{Filename}'

def ShowTextToScreen(Text):
    with open(rf'{TempDirPath}\Responses.data', "w", encoding='utf-8') as file:
        file.write(Text)

def SetUserQuery(query):
    with open(TempDirectoryPath('UserQuery.data'), "w", encoding='utf-8') as file:
        file.write(query)


INPUT_ROW_HEIGHT  = 52
INPUT_ROW_PADDING = 18
INPUT_CONTAINER_H = INPUT_ROW_HEIGHT + INPUT_ROW_PADDING  # 70 px


# ─────────────────────────────────────────────────────────────────────────────
#  ChatSection  (page index 1 inside MessageScreen's stacked widget)
# ─────────────────────────────────────────────────────────────────────────────

class ChatSection(QWidget):

    def __init__(self):
        super().__init__()

        desktop  = QApplication.desktop()
        screen_h = desktop.screenGeometry().height()
        usable_h = screen_h - TOP_BAR_HEIGHT
        self.setFixedHeight(usable_h)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 20, 10)
        layout.setSpacing(8)

        # Chat display
        self.chat_text_edit = QTextEdit()
        self.chat_text_edit.setReadOnly(True)
        self.chat_text_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.chat_text_edit.setFrameStyle(QFrame.NoFrame)
        self.chat_text_edit.setStyleSheet("background-color: transparent; color: white;")
        font = QFont()
        font.setPointSize(13)
        self.chat_text_edit.setFont(font)
        layout.addWidget(self.chat_text_edit, stretch=1)

        # GIF + status
        gif_row = QHBoxLayout()
        gif_row.setAlignment(Qt.AlignRight)
        self.gif_label = QLabel()
        self.gif_label.setStyleSheet("border: none;")
        movie = QMovie(GraphicsDirectoryPath('Jarvis.gif'))
        movie.setScaledSize(QSize(300, 169))
        self.gif_label.setFixedSize(300, 169)
        self.gif_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.gif_label.setMovie(movie)
        movie.start()
        gif_col = QVBoxLayout()
        gif_col.setSpacing(4)
        self.label = QLabel("")
        self.label.setStyleSheet("color: #00BFFF; font-size: 15px; border: none;")
        self.label.setAlignment(Qt.AlignRight)
        gif_col.addWidget(self.label)
        gif_col.addWidget(self.gif_label)
        gif_row.addLayout(gif_col)
        layout.addLayout(gif_row, stretch=0)

        # Input row
        input_container = QWidget()
        input_container.setFixedHeight(INPUT_CONTAINER_H)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, INPUT_ROW_PADDING // 2,
                                        0, INPUT_ROW_PADDING // 2)
        input_layout.setSpacing(8)

        self.text_field = QLineEdit()
        self.text_field.setPlaceholderText("Type your message or click 🎤 to speak…")
        self.text_field.setFixedHeight(INPUT_ROW_HEIGHT)
        self.text_field.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a2e;
                color: white; font-size: 16px;
                border: 2px solid #00BFFF;
                border-radius: 26px; padding: 0px 18px;
            }
            QLineEdit:focus {
                border: 2px solid #7B2FBE;
                background-color: #16213e;
            }
        """)
        self.text_field.returnPressed.connect(self.onTextSubmit)
        self.text_field.mousePressEvent = self.onTextFieldClick
        input_layout.addWidget(self.text_field, stretch=5)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedSize(80, INPUT_ROW_HEIGHT)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #7B2FBE, stop:1 #00BFFF);
                color: white; font-size: 15px; font-weight: bold;
                border-radius: 26px; border: none;
            }
            QPushButton:hover   { background: #00BFFF; }
            QPushButton:pressed { background: #7B2FBE; }
        """)
        self.send_btn.clicked.connect(self.onTextSubmit)
        input_layout.addWidget(self.send_btn)

        self.mic_toggled = False
        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(INPUT_ROW_HEIGHT, INPUT_ROW_HEIGHT)
        self.mic_btn.setToolTip("Toggle voice input")
        self.mic_btn.setStyleSheet(self._mic_btn_style(False))
        self.mic_btn.clicked.connect(self.toggleMic)
        input_layout.addWidget(self.mic_btn)

        self.cam_btn = QPushButton("📷")
        self.cam_btn.setFixedSize(INPUT_ROW_HEIGHT, INPUT_ROW_HEIGHT)
        self.cam_btn.setToolTip("Open virtual camera keyboard")
        self.cam_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: white; font-size: 22px;
                border: 2px solid #00BFFF; border-radius: 26px;
            }
            QPushButton:hover { background-color: #16213e; border-color: #7B2FBE; }
        """)
        # ── KEY CHANGE: signal parent MessageScreen to show camera keyboard ──
        self.cam_btn.clicked.connect(self._requestCameraKeyboard)
        input_layout.addWidget(self.cam_btn)

        self.yt_btn = QPushButton("▶")
        self.yt_btn.setFixedSize(INPUT_ROW_HEIGHT, INPUT_ROW_HEIGHT)
        self.yt_btn.setToolTip("Open YouTube Gesture Controller")
        self.yt_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #FF0000; font-size: 20px;
                border: 2px solid #FF0000; border-radius: 26px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a0000; border-color: #FF4444; }
        """)
        self.yt_btn.clicked.connect(self._requestYouTubeController)
        input_layout.addWidget(self.yt_btn)

        layout.addWidget(input_container, stretch=0)

        self.setStyleSheet("""
            background-color: #0a0a1a;
            QScrollBar:vertical {
                border: none; background: #0a0a1a; width: 8px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #00BFFF; min-height: 20px; border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none; height: 0;
            }
        """)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.loadMessages)
        self.timer.timeout.connect(self.RefreshStatus)
        self.timer.start(100)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _mic_btn_style(self, active):
        if active:
            return """
                QPushButton {
                    background-color: #c0392b; color: white; font-size: 22px;
                    border-radius: 26px; border: none;
                }
                QPushButton:hover { background-color: #e74c3c; }
            """
        return """
            QPushButton {
                background-color: #1a1a2e; color: white; font-size: 22px;
                border: 2px solid #00BFFF; border-radius: 26px;
            }
            QPushButton:hover { background-color: #7B2FBE; border-color: #7B2FBE; }
        """

    def onTextFieldClick(self, event):
        QLineEdit.mousePressEvent(self.text_field, event)

    def onTextSubmit(self):
        query = self.text_field.text().strip()
        if not query:
            return
        self.text_field.clear()
        SetUserQuery(query)
        SetMicrophoneStatus("True")

    def toggleMic(self):
        self.mic_toggled = not self.mic_toggled
        self.mic_btn.setStyleSheet(self._mic_btn_style(self.mic_toggled))
        if self.mic_toggled:
            MicButtonClosed()
        else:
            MicButtonInitialed()

    def _requestCameraKeyboard(self):
        """Walk up to MessageScreen and ask it to show the camera keyboard page."""
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MessageScreen):
                parent.showCameraKeyboard()
                return
            parent = parent.parent()

    def _requestYouTubeController(self):
        """Walk up to MessageScreen and ask it to show the YouTube gesture controller."""
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MessageScreen):
                parent.showYouTubeController()
                return
            parent = parent.parent()

    def loadMessages(self):
        global old_chat_message
        try:
            with open(TempDirectoryPath('Responses.data'), "r", encoding='utf-8') as f:
                messages = f.read()
            if messages and len(messages) > 1 and str(old_chat_message) != str(messages):
                self.addMessage(message=messages, color='White')
                old_chat_message = messages
        except Exception:
            pass

    def RefreshStatus(self):
        try:
            with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as f:
                self.label.setText(f.read())
        except Exception:
            pass

    def addMessage(self, message, color):
        cursor = self.chat_text_edit.textCursor()
        fmt    = QTextCharFormat()
        fmtb   = QTextBlockFormat()
        fmtb.setTopMargin(10)
        fmtb.setLeftMargin(10)
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.setBlockFormat(fmtb)
        cursor.insertText(message + "\n")
        self.chat_text_edit.setTextCursor(cursor)
        self.chat_text_edit.ensureCursorVisible()


# ─────────────────────────────────────────────────────────────────────────────
#  MessageScreen — owns BOTH the chat page AND the camera keyboard page
# ─────────────────────────────────────────────────────────────────────────────

class MessageScreen(QWidget):
    """
    Internal layout:
        QVBoxLayout
          └── QStackedWidget
                index 0 → ChatSection       (normal chat + input bar)
                index 1 → CameraKeyboardWidget (inline camera keyboard)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        desktop      = QApplication.desktop()
        screen_width = desktop.screenGeometry().width()
        screen_height= desktop.screenGeometry().height()

        usable_h = screen_height - TOP_BAR_HEIGHT
        self.setFixedSize(screen_width, usable_h)
        self.setStyleSheet("background-color: #0a0a1a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._pages = QStackedWidget()

        # Page 0 — normal chat
        self._chat_section = ChatSection()
        self._pages.addWidget(self._chat_section)

        # Page 1 — inline camera keyboard
        self._cam_kb = CameraKeyboardWidget()
        self._cam_kb.query_submitted.connect(self._onCamQuery)
        self._cam_kb.closed.connect(self.hideCameraKeyboard)
        self._pages.addWidget(self._cam_kb)

        # Page 2 — YouTube gesture controller
        self._yt_ctrl = YouTubeGestureWidget()
        self._yt_ctrl.closed.connect(self.hideYouTubeController)
        self._pages.addWidget(self._yt_ctrl)

        layout.addWidget(self._pages)

    # ── Public helpers called by ChatSection ──────────────────────────────────

    def showCameraKeyboard(self):
        self._pages.setCurrentIndex(1)
        self._cam_kb.start()

    def hideCameraKeyboard(self):
        self._cam_kb.stop()
        self._pages.setCurrentIndex(0)

    def showYouTubeController(self):
        self._pages.setCurrentIndex(2)
        self._yt_ctrl.start()

    def hideYouTubeController(self):
        self._yt_ctrl.stop()
        self._pages.setCurrentIndex(0)

    # ── Route camera-keyboard query into the same pipeline ────────────────────

    def _onCamQuery(self, text: str):
        """Receives typed text from CameraKeyboardWidget when ⏎ is pressed."""
        SetUserQuery(text)
        SetMicrophoneStatus("True")
        # Also echo it into the chat display so the user can see it
        self._chat_section.addMessage(f"[Camera Keyboard] {text}", "#00FFB4")
        # Return to chat view automatically after submit
        self.hideCameraKeyboard()


# ─────────────────────────────────────────────────────────────────────────────
#  Initial / Home screen (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class initialScreen(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        desktop       = QApplication.desktop()
        screen_width  = desktop.screenGeometry().width()
        screen_height = desktop.screenGeometry().height()

        usable_h = screen_height - TOP_BAR_HEIGHT
        self.setFixedSize(screen_width, usable_h)
        self.setStyleSheet("background-color: #0a0a1a;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        group = QWidget()
        group.setStyleSheet("background-color: transparent;")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(10)
        group_layout.setAlignment(Qt.AlignCenter)

        gif_h = int(usable_h * 0.55)
        gif_w = min(int(gif_h / 9 * 16), screen_width)
        gif_h = int(gif_w / 16 * 9)

        gif_label = QLabel()
        movie = QMovie(GraphicsDirectoryPath('Jarvis.gif'))
        movie.setScaledSize(QSize(gif_w, gif_h))
        gif_label.setMovie(movie)
        gif_label.setFixedSize(gif_w, gif_h)
        gif_label.setAlignment(Qt.AlignCenter)
        movie.start()

        self.label = QLabel("")
        self.label.setStyleSheet("color: #00BFFF; font-size: 16px; background: transparent;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFixedHeight(26)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        self.icon_label.setCursor(Qt.PointingHandCursor)
        self.toggled = True
        self.toggle_icon()
        self.icon_label.mousePressEvent = self.toggle_icon

        group_layout.addWidget(gif_label,       alignment=Qt.AlignCenter)
        group_layout.addWidget(self.label,      alignment=Qt.AlignCenter)
        group_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)

        outer.addStretch(1)
        outer.addWidget(group, alignment=Qt.AlignCenter)
        outer.addStretch(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.RefreshStatus)
        self.timer.start(100)

    def RefreshStatus(self):
        try:
            with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as f:
                self.label.setText(f.read())
        except Exception:
            pass

    def load_icon(self, path, width=60, height=60):
        pixmap = QPixmap(path).scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon_label.setPixmap(pixmap)

    def toggle_icon(self, event=None):
        if self.toggled:
            self.load_icon(GraphicsDirectoryPath('Mic_on.png'),  60, 60)
            MicButtonInitialed()
        else:
            self.load_icon(GraphicsDirectoryPath('Mic_off.png'), 60, 60)
            MicButtonClosed()
        self.toggled = not self.toggled


# ─────────────────────────────────────────────────────────────────────────────
#  Top bar + Main window (unchanged except stacked widget usage)
# ─────────────────────────────────────────────────────────────────────────────

class CustomTopBar(QWidget):

    def __init__(self, parent, stacked_widget):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.initUI()

    def initUI(self):
        self.setFixedHeight(TOP_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)

        title_label = QLabel(f"  {str(Assistantname).capitalize()} AI  ")
        title_label.setStyleSheet(
            "color: #00BFFF; font-size: 18px; font-weight: bold; background-color: transparent;")

        home_button = QPushButton()
        home_button.setIcon(QIcon(GraphicsDirectoryPath("Home.png")))
        home_button.setText("  Home")
        home_button.setStyleSheet(
            "height:40px; background-color: #1a1a2e; color: white;"
            " border: 1px solid #00BFFF; border-radius:5px; padding: 0 10px;")

        message_button = QPushButton()
        message_button.setIcon(QIcon(GraphicsDirectoryPath("Chats.png")))
        message_button.setText("  Chat")
        message_button.setStyleSheet(
            "height:40px; background-color: #1a1a2e; color: white;"
            " border: 1px solid #00BFFF; border-radius:5px; padding: 0 10px;")

        minimize_button = QPushButton("—")
        minimize_button.setFixedSize(36, 36)
        minimize_button.setStyleSheet(
            "background-color:#1a1a2e; color:white; border:none; font-size:18px; border-radius:4px;")
        minimize_button.clicked.connect(self.minimizeWindow)

        self.maximize_button = QPushButton("□")
        self.maximize_button.setFixedSize(36, 36)
        self.maximize_button.setStyleSheet(
            "background-color:#1a1a2e; color:white; border:none; font-size:18px; border-radius:4px;")
        self.maximize_button.clicked.connect(self.maximizeWindow)

        close_button = QPushButton("✕")
        close_button.setFixedSize(36, 36)
        close_button.setStyleSheet(
            "background-color:#c0392b; color:white; border:none; font-size:16px; border-radius:4px;")
        close_button.clicked.connect(self.closeWindow)

        home_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        message_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(home_button)
        layout.addWidget(message_button)
        layout.addStretch(1)
        layout.addWidget(minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(close_button)

        self.draggable = True
        self.offset    = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d0d1f"))
        super().paintEvent(event)

    def minimizeWindow(self):  self.parent().showMinimized()
    def closeWindow(self):     self.parent().close()

    def maximizeWindow(self):
        if self.parent().isMaximized():
            self.parent().showNormal()
        else:
            self.parent().showMaximized()

    def mousePressEvent(self, event):
        if self.draggable:
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.draggable and self.offset:
            self.parent().move(event.globalPos() - self.offset)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.initUI()

    def initUI(self):
        desktop       = QApplication.desktop()
        screen_width  = desktop.screenGeometry().width()
        screen_height = desktop.screenGeometry().height()

        stacked = QStackedWidget(self)
        stacked.addWidget(initialScreen())
        stacked.addWidget(MessageScreen())

        self.setGeometry(0, 0, screen_width, screen_height)
        self.setStyleSheet("background-color: #0a0a1a;")
        self.setMenuWidget(CustomTopBar(self, stacked))
        self.setCentralWidget(stacked)


def GraphicalUserInterface():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    GraphicalUserInterface()