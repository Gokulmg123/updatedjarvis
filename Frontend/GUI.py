"""
gui.py — Jarvis AI Frontend  [ULTRA-PREMIUM AI REDESIGN v3]
============================================================
Complete visual overhaul:
  • Deep space black + electric violet + neon cyan palette
  • Immersive full-bleed layout — NO card wrappers
  • Animated neural-net particle canvas (QPainter, QTimer)
  • Asymmetric chat: user queries RIGHT, assistant LEFT only
  • Scanline + hex-grid subtle background texture (QPainter)
  • Glassmorphism input bar with gradient border
  • Animated typing indicator (dot pulse)
  • Thin accent lines, sharp corners with selective radius
  • Holographic top bar with live status segment display

All backend / logic code UNCHANGED.
"""

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QStackedWidget, QWidget,
    QLineEdit, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QLabel, QSizePolicy, QScrollArea, QGraphicsDropShadowEffect,
    QSpacerItem
)
from PyQt5.QtGui import (
    QIcon, QPainter, QColor, QFont, QPixmap,
    QLinearGradient, QBrush, QPen, QRadialGradient, QFontMetrics,
    QPainterPath, QPolygon, QConicalGradient
)
from PyQt5.QtCore import (
    Qt, QSize, QTimer, QRect, QPoint, QRectF, QPointF,
    QPropertyAnimation, QEasingCurve, pyqtSignal
)
from dotenv import dotenv_values
import sys, os, math, random

_GUI_DIR     = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR    = os.path.abspath(os.path.join(_GUI_DIR, ".."))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "Backend")
for _p in (_ROOT_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from CameraKeyboardWidget import CameraKeyboardWidget
from YouTubeGestureController import YouTubeGestureWidget

_ENV_PATH     = os.path.join(_ROOT_DIR, ".env")
env_vars      = dotenv_values(_ENV_PATH)
Assistantname = env_vars.get("Assistantname", "Jarvis")
old_chat_message = ""
TempDirPath      = os.path.join(_ROOT_DIR, "Frontend", "Files")
GraphicsDirPath  = os.path.join(_ROOT_DIR, "Frontend", "Graphics")

for _fname in ("Mic.data", "Status.data", "Responses.data",
               "Database.data", "UserQuery.data"):
    _fpath = os.path.join(TempDirPath, _fname)
    if not os.path.exists(_fpath):
        open(_fpath, "w", encoding="utf-8").close()

TOP_BAR_HEIGHT    = 52
INPUT_ROW_HEIGHT  = 48
INPUT_CONTAINER_H = INPUT_ROW_HEIGHT + 24

# ─────────────────────────────────────────────────────────
#  ULTRA-PREMIUM PALETTE
# ─────────────────────────────────────────────────────────
C_VOID        = "#050508"       # near-black background
C_DEEP        = "#080b14"       # deep navy-black
C_SURFACE     = "#0d1020"       # surface layer
C_ELEVATED    = "#111628"       # elevated panel
C_BORDER      = "#1e2340"       # subtle border
C_BORDER_MED  = "#2a3060"       # medium border

C_VIOLET      = "#7c3aed"       # primary accent – electric violet
C_VIOLET_BRT  = "#a855f7"       # bright violet
C_VIOLET_DIM  = "#4c1d95"       # dim violet
C_CYAN        = "#06b6d4"       # secondary accent – neon cyan
C_CYAN_BRT    = "#22d3ee"       # bright cyan
C_CYAN_DIM    = "#0e7490"       # dim cyan

C_TEXT        = "#e2e8f0"       # primary text
C_TEXT_MED    = "#94a3b8"       # secondary text
C_TEXT_DIM    = "#475569"       # dim text

C_USER_BG     = "#0f1a35"       # user bubble bg
C_BOT_BG      = "#0a0e1a"       # assistant bubble bg

C_USER_TAG    = "#22d3ee"       # user label color
C_BOT_TAG     = "#a855f7"       # assistant label color

C_ACCENT_LINE = "#1e3a5f"       # subtle hr / divider
C_GLOW_V      = "#7c3aed"
C_GLOW_C      = "#06b6d4"


# ─────────────────────────────────────────────────────────
#  Backend helpers  (UNCHANGED)
# ─────────────────────────────────────────────────────────

def AnswerModifier(Answer):
    lines = Answer.split('\n')
    return '\n'.join(line for line in lines if line.strip())

def QueryModifier(Query):
    new_query = Query.lower().strip()
    query_words = new_query.split()
    if not query_words:
        return ""
    question_words = ["how","what","who","where","when","why","which",
                      "whose","whom","can you","what's","where's","how's"]
    if any(word+" " in new_query for word in question_words):
        if query_words[-1][-1] in ['.','?','!']:
            new_query = new_query[:-1]+"?"
        else:
            new_query += "?"
    else:
        if query_words[-1][-1] in ['.','?','!']:
            new_query = new_query[:-1]+"."
        else:
            new_query += "."
    return new_query.capitalize()

def SetMicrophoneStatus(Command):
    with open(rf'{TempDirPath}\Mic.data',"w",encoding='utf-8') as f: f.write(Command)
def GetMicrophoneStatus():
    with open(rf'{TempDirPath}\Mic.data',"r",encoding='utf-8') as f: return f.read()
def SetAssistantStatus(Status):
    with open(rf'{TempDirPath}\Status.data',"w",encoding='utf-8') as f: f.write(Status)
def GetAssistantStatus():
    with open(rf'{TempDirPath}\Status.data',"r",encoding='utf-8') as f: return f.read()
def MicButtonInitialed(): SetMicrophoneStatus("False")
def MicButtonClosed():    SetMicrophoneStatus("True")
def GraphicsDirectoryPath(Filename): return rf'{GraphicsDirPath}\{Filename}'
def TempDirectoryPath(Filename):     return rf'{TempDirPath}\{Filename}'
def ShowTextToScreen(Text):
    with open(rf'{TempDirPath}\Responses.data',"w",encoding='utf-8') as f: f.write(Text)
def SetUserQuery(query):
    with open(TempDirectoryPath('UserQuery.data'),"w",encoding='utf-8') as f: f.write(query)


# ─────────────────────────────────────────────────────────
#  Neural Orb  – pure QPainter, layered rings + nodes
# ─────────────────────────────────────────────────────────
class NeuralOrb(QWidget):
    """
    ULTRA AI CORE ANIMATION:
    - Rotating multi-layer rings
    - Data stream particles flowing inward
    - Pulsing quantum core
    - Premium glow + depth
    """

    def __init__(self, size=260, parent=None):
        super().__init__(parent)
        self._sz = size
        self._t = 0.0

        # particle field (data flow)
        self._particles = [
            {
                "angle": random.uniform(0, 2 * math.pi),
                "dist": random.uniform(0.4, 1.0),
                "speed": random.uniform(0.002, 0.008),
                "size": random.uniform(1.5, 3.5)
            }
            for _ in range(60)
        ]

        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_anim)
        self.timer.start(16)  # smooth ~60fps

    def _update_anim(self):
        self._t += 0.02

        # move particles inward (data ingestion effect)
        for p in self._particles:
            p["dist"] -= p["speed"]
            if p["dist"] < 0.1:
                p["dist"] = 1.0
                p["angle"] = random.uniform(0, 2 * math.pi)

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self._sz / 2
        cy = self._sz / 2

        pulse = 0.9 + 0.1 * math.sin(self._t * 2)

        # ─── CORE GLOW ─────────────────────────────────────
        core_r = self._sz * 0.18 * pulse

        core_grad = QRadialGradient(cx, cy, core_r * 2)
        core_grad.setColorAt(0, QColor(180, 220, 255, 255))
        core_grad.setColorAt(0.3, QColor(124, 58, 237, 220))
        core_grad.setColorAt(0.6, QColor(6, 182, 212, 160))
        core_grad.setColorAt(1, QColor(0, 0, 0, 0))

        p.setBrush(core_grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))

        # ─── ROTATING RINGS (AI LAYERS) ────────────────────
        for i in range(3):
            r = core_r * (2.2 + i * 0.8)
            angle_offset = self._t * (0.5 + i * 0.3)

            pen = QPen(QColor(124, 58, 237, 120 - i * 30), 1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)

            path = QPainterPath()
            for a in range(0, 360, 5):
                rad = math.radians(a)
                wobble = math.sin(rad * 4 + angle_offset) * 4
                x = cx + (r + wobble) * math.cos(rad + angle_offset)
                y = cy + (r + wobble) * math.sin(rad + angle_offset)

                if a == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)

            p.drawPath(path)

        # ─── DATA FLOW PARTICLES ───────────────────────────
        for particle in self._particles:
            angle = particle["angle"]
            dist = particle["dist"]

            r = core_r * 4 * dist

            x = cx + math.cos(angle) * r
            y = cy + math.sin(angle) * r

            glow = QRadialGradient(x, y, particle["size"] * 3)
            glow.setColorAt(0, QColor(6, 182, 212, 200))
            glow.setColorAt(1, QColor(0, 0, 0, 0))

            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(
                x - particle["size"],
                y - particle["size"],
                particle["size"] * 2,
                particle["size"] * 2
            ))

        # ─── OUTER ENERGY FIELD ────────────────────────────
        outer = QRadialGradient(cx, cy, self._sz * 0.5)
        outer.setColorAt(0, QColor(124, 58, 237, 20))
        outer.setColorAt(0.5, QColor(6, 182, 212, 10))
        outer.setColorAt(1, QColor(0, 0, 0, 0))

        p.setBrush(outer)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(0, 0, self._sz, self._sz))

        p.end()
# ─────────────────────────────────────────────────────────
#  Live Pulse Bar  – horizontal equalizer-style indicator
# ─────────────────────────────────────────────────────────

class PulseBar(QWidget):
    """Animated 5-bar audio-equalizer style status indicator."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 18)
        self._phases = [random.uniform(0, 2*math.pi) for _ in range(5)]
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(45)

    def _tick(self):
        for i in range(5):
            self._phases[i] = (self._phases[i] + random.uniform(0.06, 0.14)) % (2*math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bar_w = 3
        gap   = 2
        for i in range(5):
            h  = int(4 + 10 * abs(math.sin(self._phases[i])))
            x  = i * (bar_w + gap)
            y  = (18 - h) // 2
            alpha = int(160 + 80 * abs(math.sin(self._phases[i])))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(6, 182, 212, alpha))
            p.drawRoundedRect(x, y, bar_w, h, 1, 1)
        p.end()


# ─────────────────────────────────────────────────────────
#  HexGrid Background  – tiled hex pattern (subtle)
# ─────────────────────────────────────────────────────────

class HexBackground(QWidget):
    """Draws a faint animated hex-grid across the full background."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._phase = 0.0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(60)

    def _tick(self):
        self._phase = (self._phase + 0.012) % (2 * math.pi)
        self.update()

    def _hex_points(self, cx, cy, r):
        pts = []
        for i in range(6):
            a = math.pi / 3 * i - math.pi / 6
            pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 38
        hr = r * math.sqrt(3) / 2
        pulse = 0.5 + 0.5 * math.sin(self._phase)
        base_alpha = int(6 + 4 * pulse)
        pen = QPen(QColor(C_CYAN_BRT), 0.4)
        pen.setColor(QColor(6, 182, 212, base_alpha))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        col = 0
        x = 0.0
        while x < w + r * 2:
            y_off = hr if col % 2 else 0.0
            y = -hr + y_off
            while y < h + hr:
                pts = self._hex_points(x, y, r * 0.88)
                path = QPainterPath()
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                path.closeSubpath()
                p.drawPath(path)
                y += hr * 2
            x += r * 1.5
            col += 1
        p.end()


# ─────────────────────────────────────────────────────────
#  Gradient accent line widget
# ─────────────────────────────────────────────────────────

class GradientLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0,   QColor(0, 0, 0, 0))
        g.setColorAt(0.2, QColor(124, 58, 237, 140))
        g.setColorAt(0.5, QColor(6, 182, 212, 180))
        g.setColorAt(0.8, QColor(124, 58, 237, 140))
        g.setColorAt(1,   QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g)
        p.end()


# ─────────────────────────────────────────────────────────
#  ChatBubble  – user RIGHT / assistant LEFT
# ─────────────────────────────────────────────────────────

class ChatBubble(QWidget):
    MAX_W_RATIO = 1

    def __init__(self, text: str, is_user: bool, parent_width: int = 720):
        super().__init__()
        self._text    = text
        self._is_user = is_user
        self._pw      = parent_width
        self._build()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 3, 16, 3)
        outer.setSpacing(0)

        max_px = int(self._pw * self.MAX_W_RATIO)

        if self._is_user:
            bubble = QFrame()
            bubble.setObjectName("UB")
            bubble.setStyleSheet(f"""
                #UB {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 #0f1e40, stop:1 #0a1428);
                    border-radius: 16px;
                    border-top-right-radius: 3px;
                    border: 1px solid {C_CYAN_DIM};
                }}
            """)
            bl = QVBoxLayout(bubble)
            bl.setContentsMargins(18, 14, 18, 14)
            bl.setSpacing(4)

            tag = QLabel("You")
            tag.setStyleSheet(f"color:{C_USER_TAG};font-size:18px;font-weight:700;"
                              f"letter-spacing:1px;background:transparent;border:none;")
            bl.addWidget(tag)

            lbl = QLabel(self._text)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl.setStyleSheet(f"color:{C_TEXT};font-size:14px;line-height:1.7;"
                              f"background:transparent;border:none;")
            bl.addWidget(lbl)
            bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

            outer.addStretch(1)
            outer.addWidget(bubble)

        else:
            wrapper = QHBoxLayout()
            wrapper.setSpacing(0)
            wrapper.setContentsMargins(0, 0, 0, 0)

            stripe = QFrame()
            stripe.setFixedWidth(3)
            stripe.setStyleSheet(f"""
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {C_VIOLET_BRT}, stop:1 {C_CYAN});
                border-radius: 2px;
            """)

            bubble = QFrame()
            bubble.setObjectName("AB")
            bubble.setStyleSheet(f"""
                #AB {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 #0b0e1e, stop:1 #070910);
                    border-radius: 16px;
                    border-top-left-radius: 3px;
                    border: 1px solid {C_BORDER_MED};
                    border-left: none;
                }}
            """)
            bl = QVBoxLayout(bubble)
            bl.setContentsMargins(14, 10, 16, 10)
            bl.setSpacing(4)

            tag = QLabel()
            tag.setStyleSheet(f"color:{C_BOT_TAG};font-size:18px;font-weight:700;"
                              f"letter-spacing:2px;background:transparent;border:none;")
            bl.addWidget(tag)

            lbl = QLabel(self._text)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl.setStyleSheet(f"color:{C_TEXT};font-size:20px;line-height:1.5;"
                              f"background:transparent;border:none;")
            bl.addWidget(lbl)
            bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

            wrapper.addWidget(stripe)
            wrapper.addWidget(bubble)
            outer.addLayout(wrapper)
            outer.addStretch(1)


# ─────────────────────────────────────────────────────────
#  ChatScrollArea
# ─────────────────────────────────────────────────────────

class ChatScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {C_VIOLET};
                border-radius: 2px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 16, 0, 16)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setWidget(self._container)

    def addBubble(self, text: str, is_user: bool):
        width = self.viewport().width()
        bubble = ChatBubble(text, is_user, width)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        QTimer.singleShot(50, self._scrollToBottom)

    def _scrollToBottom(self):
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─────────────────────────────────────────────────────────
#  WelcomeBanner  – shown at top of empty chat
# ─────────────────────────────────────────────────────────

class WelcomeBanner(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        orb = NeuralOrb(size=110)
        layout.addWidget(orb, alignment=Qt.AlignCenter)

        name_lbl = QLabel(Assistantname.upper())
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(f"""
            color: {C_CYAN_BRT};
            font-size: 34px;
            font-weight: 800;
            letter-spacing: 10px;
            background: transparent;
        """)
        layout.addWidget(name_lbl)

        sub = QLabel("Artificial Intelligence · Always On")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12px;letter-spacing:3px;"
                          f"background:transparent;")
        layout.addWidget(sub)

        layout.addWidget(GradientLine())


# ─────────────────────────────────────────────────────────
#  ChatSection
# ─────────────────────────────────────────────────────────

class ChatSection(QWidget):
    def __init__(self):
        super().__init__()
        desktop  = QApplication.desktop()
        screen_h = desktop.screenGeometry().height()
        screen_w = desktop.screenGeometry().width()
        usable_h = screen_h - TOP_BAR_HEIGHT
        self.setMinimumSize(screen_w, usable_h)
        self.setStyleSheet(f"background: {C_VOID};")

        self._hex_bg = HexBackground(self)
        self._hex_bg.setGeometry(0, 0, screen_w, usable_h)
        self._hex_bg.lower()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(58)
        header.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C_DEEP}, stop:0.5 #0c1024, stop:1 {C_DEEP});
            border-bottom: 1px solid {C_BORDER};
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(14)

        orb_mini = NeuralOrb(size=38)
        hl.addWidget(orb_mini)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        nm = QLabel(Assistantname.upper())
        nm.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;"
                         f"letter-spacing:3px;background:transparent;")
        name_row.addWidget(nm)

        ai_badge = QLabel("AI")
        ai_badge.setStyleSheet(f"""
            color:{C_CYAN_BRT};
            font-size:9px;font-weight:800;
            letter-spacing:1px;
            background:{C_ELEVATED};
            border:1px solid {C_CYAN_DIM};
            border-radius:4px;
            padding:1px 5px;
        """)
        name_row.addWidget(ai_badge)
        name_row.addStretch(1)
        info_col.addLayout(name_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(PulseBar())
        self._status_lbl = QLabel("Initialising…")
        self._status_lbl.setStyleSheet(
            f"color:{C_TEXT_MED};font-size:11px;background:transparent;")
        status_row.addWidget(self._status_lbl)
        status_row.addStretch(1)
        info_col.addLayout(status_row)

        hl.addLayout(info_col)
        hl.addStretch(1)
        #layout.addWidget(header)

        #layout.addWidget(GradientLine())

        self._chat = ChatScrollArea()
        layout.addWidget(self._chat, stretch=1)

        layout.addWidget(GradientLine())

        input_container = QWidget()
        input_container.setFixedHeight(INPUT_CONTAINER_H + 6)
        input_container.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {C_DEEP}, stop:1 {C_VOID});
        """)
        il = QHBoxLayout(input_container)
        il.setContentsMargins(18, 10, 18, 10)
        il.setSpacing(10)

        self.text_field = QLineEdit()
        self.text_field.setPlaceholderText(f"Send a message to {Assistantname.capitalize()}…")
        self.text_field.setFixedHeight(INPUT_ROW_HEIGHT)
        self.text_field.setStyleSheet(f"""
            QLineEdit {{
                background: {C_ELEVATED};
                color: {C_TEXT};
                font-size: 14px;
                border: 1px solid {C_BORDER_MED};
                border-radius: 24px;
                padding: 0 22px;
                selection-background-color: {C_VIOLET_DIM};
            }}
            QLineEdit:focus {{
                border: 1px solid {C_VIOLET_BRT};
                background: #141830;
            }}
            QLineEdit::placeholder {{
                color: {C_TEXT_DIM};
            }}
        """)
        self.text_field.returnPressed.connect(self.onTextSubmit)
        il.addWidget(self.text_field, stretch=5)

        def _icon_btn(icon_text, tooltip, bg=C_ELEVATED, border=C_BORDER_MED,
                      hover_border=C_VIOLET_BRT):
            b = QPushButton(icon_text)
            b.setFixedSize(INPUT_ROW_HEIGHT, INPUT_ROW_HEIGHT)
            b.setToolTip(tooltip)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {bg};
                    color: {C_TEXT};
                    font-size: 18px;
                    border: 1px solid {border};
                    border-radius: 24px;
                }}
                QPushButton:hover {{
                    background: #1a1e38;
                    border-color: {hover_border};
                }}
                QPushButton:pressed {{
                    background: #0d1026;
                }}
            """)
            return b

        self.send_btn = _icon_btn("⬆", "Send", bg=C_VIOLET_DIM,
                                  border=C_VIOLET, hover_border=C_VIOLET_BRT)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {C_VIOLET}, stop:1 {C_CYAN_DIM});
                color: white;
                font-size: 17px;
                font-weight: bold;
                border-radius: 24px;
                border: none;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {C_VIOLET_BRT}, stop:1 {C_CYAN});
            }}
            QPushButton:pressed {{
                background: {C_VIOLET_DIM};
            }}
        """)
        self.send_btn.clicked.connect(self.onTextSubmit)
        il.addWidget(self.send_btn)

        self.mic_toggled = False
        self.mic_btn = _icon_btn("🎙", "Toggle voice", hover_border=C_CYAN_BRT)
        self.mic_btn.clicked.connect(self.toggleMic)
        il.addWidget(self.mic_btn)

        self.cam_btn = _icon_btn("📷", "Camera keyboard", hover_border=C_CYAN_BRT)
        self.cam_btn.clicked.connect(self._requestCameraKeyboard)
        il.addWidget(self.cam_btn)

        layout.addWidget(input_container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.loadMessages)
        self.timer.timeout.connect(self.RefreshStatus)
        self.timer.start(100)

    def _mic_active_style(self):
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #7f1d1d, stop:1 #b91c1c);
                color: white; font-size: 18px;
                border-radius: 24px; border: none;
            }}
            QPushButton:hover {{ background: #dc2626; }}
        """

    def _mic_idle_style(self):
        return f"""
            QPushButton {{
                background: {C_ELEVATED};
                color: {C_TEXT}; font-size: 18px;
                border: 1px solid {C_BORDER_MED};
                border-radius: 24px;
            }}
            QPushButton:hover {{
                background: #1a1e38;
                border-color: {C_CYAN_BRT};
            }}
        """

    def onTextSubmit(self):
        query = self.text_field.text().strip()
        if not query:
            return
        self.text_field.clear()
        self._chat.addBubble(query, is_user=True)
        SetUserQuery(query)
        SetMicrophoneStatus("True")

    def toggleMic(self):
        self.mic_toggled = not self.mic_toggled
        self.mic_btn.setStyleSheet(
            self._mic_active_style() if self.mic_toggled else self._mic_idle_style()
        )
        MicButtonClosed() if self.mic_toggled else MicButtonInitialed()

    def _requestCameraKeyboard(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MessageScreen):
                parent.showCameraKeyboard()
                return
            parent = parent.parent()

    def loadMessages(self):
        global old_chat_message
        try:
            with open(TempDirectoryPath('Responses.data'), "r", encoding='utf-8') as f:
                messages = f.read()
            if messages and len(messages) > 1 and str(old_chat_message) != str(messages):
                self._chat.addBubble(messages, is_user=False)
                old_chat_message = messages
        except Exception:
            pass

    def RefreshStatus(self):
        try:
            with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as f:
                self._status_lbl.setText(f.read())
        except Exception:
            pass

    def addMessage(self, message: str, color: str = "white"):
        is_user = (color == "#00FFB4")
        self._chat.addBubble(message, is_user=is_user)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._hex_bg.setGeometry(0, 0, self.width(), self.height())


# ─────────────────────────────────────────────────────────
#  MessageScreen
# ─────────────────────────────────────────────────────────

class MessageScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        desktop       = QApplication.desktop()
        screen_width  = desktop.screenGeometry().width()
        screen_height = desktop.screenGeometry().height()
        usable_h      = screen_height - TOP_BAR_HEIGHT
        self.setFixedSize(screen_width, usable_h)
        self.setStyleSheet(f"background: {C_VOID};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._pages = QStackedWidget()

        self._chat_section = ChatSection()
        self._pages.addWidget(self._chat_section)

        self._cam_kb = CameraKeyboardWidget()
        self._cam_kb.query_submitted.connect(self._onCamQuery)
        self._cam_kb.closed.connect(self.hideCameraKeyboard)
        self._pages.addWidget(self._cam_kb)

        self._yt_ctrl = YouTubeGestureWidget()
        self._yt_ctrl.yt_detected.connect(self._autoShowYouTubeController)
        self._yt_ctrl.yt_lost.connect(self._autoHideYouTubeController)
        self._yt_ctrl.closed.connect(self._autoHideYouTubeController)
        self._pages.addWidget(self._yt_ctrl)

        layout.addWidget(self._pages)
        self._yt_ctrl.start()

    def showCameraKeyboard(self):
        self._pages.setCurrentIndex(1)
        self._cam_kb.start()

    def hideCameraKeyboard(self):
        self._cam_kb.stop()
        self._pages.setCurrentIndex(0)

    def _autoShowYouTubeController(self):
        if self._pages.currentIndex() != 1:
            self._pages.setCurrentIndex(2)

    def _autoHideYouTubeController(self):
        if self._pages.currentIndex() == 2:
            self._pages.setCurrentIndex(0)

    def _onCamQuery(self, text: str):
        SetUserQuery(text)
        SetMicrophoneStatus("True")
        self._chat_section.addMessage(f"[Camera] {text}", "#00FFB4")
        self.hideCameraKeyboard()


# ─────────────────────────────────────────────────────────
#  InitialScreen  – premium full-bleed AI landing view
# ─────────────────────────────────────────────────────────

class initialScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        desktop       = QApplication.desktop()
        screen_width  = desktop.screenGeometry().width()
        screen_height = desktop.screenGeometry().height()
        usable_h      = screen_height - TOP_BAR_HEIGHT
        self.setFixedSize(screen_width, usable_h)
        self.setStyleSheet(f"background: {C_VOID};")

        self._hex_bg = HexBackground(self)
        self._hex_bg.setGeometry(0, 0, screen_width, usable_h)
        self._hex_bg.lower()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignCenter)

        col = QVBoxLayout()
        col.setSpacing(0)
        col.setAlignment(Qt.AlignCenter)

        # ── BIGGER CENTRAL ANIMATION ─────────────────────────────────────
        orb = NeuralOrb(size=320)          # ← Increased from 200 to 280
        col.addWidget(orb, alignment=Qt.AlignCenter)
        col.addSpacing(32)                 # Extra spacing for bigger orb

        name_lbl = QLabel(Assistantname.upper())
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(f"""
            color: {C_TEXT};
            font-size: 48px;
            font-weight: 800;
            letter-spacing: 16px;
            background: transparent;
        """)
        col.addWidget(name_lbl)
        col.addSpacing(8)

        tag_lbl = QLabel("N E X T · G E N E R A T I O N   A R T I F I C I A L   I N T E L L I G E N C E")
        tag_lbl.setAlignment(Qt.AlignCenter)
        tag_lbl.setStyleSheet(f"""
            color: {C_TEXT_DIM};
            font-size: 10px;
            letter-spacing: 3px;
            background: transparent;
        """)
        col.addWidget(tag_lbl)
        col.addSpacing(28)

        col.addWidget(GradientLine())
        col.addSpacing(28)

        s_row = QHBoxLayout()
        s_row.setSpacing(10)
        s_row.setAlignment(Qt.AlignCenter)
        s_row.addWidget(PulseBar())
        self.label = QLabel("Initialising…")
        self.label.setStyleSheet(
            f"color:{C_TEXT_MED};font-size:13px;background:transparent;")
        s_row.addWidget(self.label)
        col.addLayout(s_row)
        col.addSpacing(32)

        self.toggled = True
        self.mic_btn = QPushButton("🎙  VOICE ACTIVE")
        self.mic_btn.setFixedSize(200, 46)
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self._apply_mic_style()
        self.mic_btn.clicked.connect(self._toggle_mic)
        col.addWidget(self.mic_btn, alignment=Qt.AlignCenter)

        outer.addLayout(col)

        self._ver = QLabel("v3.0 · AI CORE")
        self._ver.setStyleSheet(f"""
            color: {C_TEXT_DIM};
            font-size: 10px;
            letter-spacing: 2px;
            background: transparent;
        """)
        ver_row = QHBoxLayout()
        ver_row.setContentsMargins(0, 0, 22, 14)
        ver_row.addStretch(1)
        ver_row.addWidget(self._ver)
        outer.addLayout(ver_row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(100)

    def _apply_mic_style(self):
        if self.toggled:
            self.mic_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C_CYAN_BRT};
                    font-size: 12px;
                    font-weight: 700;
                    letter-spacing: 2px;
                    border: 1px solid {C_CYAN};
                    border-radius: 23px;
                }}
                QPushButton:hover {{
                    background: rgba(6,182,212,0.08);
                    border-color: {C_CYAN_BRT};
                }}
            """)
        else:
            self.mic_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: #f87171;
                    font-size: 12px;
                    font-weight: 700;
                    letter-spacing: 2px;
                    border: 1px solid #b91c1c;
                    border-radius: 23px;
                }}
                QPushButton:hover {{ background: rgba(185,28,28,0.10); }}
            """)
            self.mic_btn.setText("🔇  VOICE MUTED")

    def _toggle_mic(self):
        if self.toggled:
            MicButtonInitialed()
            self.mic_btn.setText("🎙  VOICE ACTIVE")
        else:
            MicButtonClosed()
            self.mic_btn.setText("  VOICE ")
        self.toggled = not self.toggled
        self._apply_mic_style()

    def _refresh_status(self):
        try:
            with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as f:
                self.label.setText(f.read())
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
#  CustomTopBar
# ─────────────────────────────────────────────────────────

class CustomTopBar(QWidget):
    def __init__(self, parent, stacked_widget):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self._offset = None
        self.initUI()

    def initUI(self):
        self.setFixedHeight(TOP_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)

        orb_mini = NeuralOrb(size=26)
        layout.addWidget(orb_mini)

        title = QLabel(f"{Assistantname.upper()}")
        title.setStyleSheet(f"""
            color: {C_TEXT};
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 4px;
            background: transparent;
        """)
        layout.addWidget(title)

        ai_tag = QLabel("NEURAL AI")
        ai_tag.setStyleSheet(f"""
            color: {C_VIOLET_BRT};
            font-size: 9px; font-weight: 800;
            letter-spacing: 1px;
            background: #1a0a2e;
            border: 1px solid {C_VIOLET_DIM};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        layout.addWidget(ai_tag)
        layout.addStretch(1)

        for label, idx in [("HOME", 0), ("CHAT", 1)]:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C_TEXT_DIM};
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 2px;
                    border: 1px solid {C_BORDER};
                    border-radius: 4px;
                    padding: 0 14px;
                }}
                QPushButton:hover {{
                    background: rgba(124,58,237,0.12);
                    color: {C_VIOLET_BRT};
                    border-color: {C_VIOLET};
                }}
            """)
            btn.clicked.connect(lambda _, i=idx: self.stacked_widget.setCurrentIndex(i))
            layout.addWidget(btn)

        layout.addSpacing(12)

        for symbol, tip, handler, danger in [
            ("─", "Minimise", self.minimizeWindow, False),
            ("□", "Maximise", self.maximizeWindow, False),
            ("✕", "Close",    self.closeWindow,    True),
        ]:
            b = QPushButton(symbol)
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            hover_bg = "#c0392b" if danger else f"rgba(124,58,237,0.18)"
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C_TEXT_DIM};
                    font-size: 13px;
                    border: none;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background: {hover_bg};
                    color: white;
                }}
            """)
            b.clicked.connect(handler)
            layout.addWidget(b)

    def paintEvent(self, event):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0,   QColor(C_DEEP))
        grad.setColorAt(0.4, QColor("#090c1c"))
        grad.setColorAt(1,   QColor(C_DEEP))
        p.fillRect(self.rect(), grad)

        lg = QLinearGradient(0, 0, self.width(), 0)
        lg.setColorAt(0,   QColor(0, 0, 0, 0))
        lg.setColorAt(0.2, QColor(124, 58, 237, 160))
        lg.setColorAt(0.5, QColor(6, 182, 212, 200))
        lg.setColorAt(0.8, QColor(124, 58, 237, 160))
        lg.setColorAt(1,   QColor(0, 0, 0, 0))
        p.fillRect(0, self.height() - 1, self.width(), 1, lg)
        p.end()
        super().paintEvent(event)

    def minimizeWindow(self): self.parent().showMinimized()
    def closeWindow(self):    self.parent().close()
    def maximizeWindow(self):
        self.parent().showNormal() if self.parent().isMaximized() else self.parent().showMaximized()

    def mousePressEvent(self, event):
        self._offset = event.pos()

    def mouseMoveEvent(self, event):
        if self._offset:
            self.parent().move(event.globalPos() - self._offset)

    def mouseReleaseEvent(self, event):
        self._offset = None


# ─────────────────────────────────────────────────────────
#  MainWindow
# ─────────────────────────────────────────────────────────

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
        self.setStyleSheet(f"background: {C_VOID};")
        self.setMenuWidget(CustomTopBar(self, stacked))
        self.setCentralWidget(stacked)


def GraphicalUserInterface():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    GraphicalUserInterface()