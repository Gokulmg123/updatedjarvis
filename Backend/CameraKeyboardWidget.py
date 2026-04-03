"""
CameraKeyboardWidget.py
========================
An INLINE PyQt5 widget that embeds the virtual camera keyboard
directly inside the main Jarvis GUI window.

Drop this file next to gui.py (or anywhere on the Python path).
The widget runs MediaPipe hand-tracking in a QThread, paints each
processed frame onto a QLabel, and emits keypresses as Qt signals so
the parent window can route them exactly like text-field / mic input.

Gesture controls are identical to the original CameraKeyboard.py:
  ☝  Index only          → aim / hover
  ✌  Index + Middle close → press the hovered key
  ✋  Any other pose       → neutral

Usage (see gui.py patch at the bottom of this file for full wiring):
    from CameraKeyboardWidget import CameraKeyboardWidget
"""

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarkerResult
import numpy as np
import os
import urllib.request
import time

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont, QColor

# ── Keyboard layout ───────────────────────────────────────────────────────────
ROWS = [
    ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
    ["Z", "X", "C", "V", "B", "N", "M", "⌫", "⏎"],
    ["SPACE"],
]

KEY_W = 80
KEY_H = 60
KEY_GAP = 10
START_Y_RATIO = 0.28

HOVER_FRAMES = 14
PINCH_FRAMES = 3 
COOLDOWN_S = 0.65
PINCH_DIST_THR = 0.055
SMOOTH_ALPHA = 0.50

# BGR colors
C_KEY_NORMAL  = (35,  35,  55)
C_KEY_HOVER   = (130, 70, 210)
C_KEY_PRESSED = (0,  210, 255)
C_KEY_CHARGE  = (0,  160, 100)
C_BORDER      = (0,  191, 255)
C_BORDER_HOV  = (180, 100, 255)
C_TEXT        = (255, 255, 255)
C_INPUT_BG    = (10,  10,  30)
C_INPUT_TEXT  = (0,  255, 180)
C_AIM         = (0,  255,  80)
C_PINCH       = (0,  220, 255)
C_STATUS_AIM  = (0,  210, 120)
C_STATUS_PIN  = (0,  220, 255)
C_STATUS_NEU  = (140, 140, 160)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers (identical logic to original CameraKeyboard.py)
# ─────────────────────────────────────────────────────────────────────────────

def _smooth(state: dict, raw_x: int, raw_y: int):
    if not state["init"]:
        state["x"], state["y"], state["init"] = float(raw_x), float(raw_y), True
    else:
        state["x"] = SMOOTH_ALPHA * state["x"] + (1 - SMOOTH_ALPHA) * raw_x
        state["y"] = SMOOTH_ALPHA * state["y"] + (1 - SMOOTH_ALPHA) * raw_y
    return int(state["x"]), int(state["y"])


def _is_finger_up(lm, tip_id, pip_id):
    return lm.landmark[tip_id].y < lm.landmark[pip_id].y

def _is_thumb_up(lm):
    return abs(lm.landmark[4].x - lm.landmark[2].x) > 0.04

def _finger_states(lm):
    return {
        "thumb":  _is_thumb_up(lm),
        "index":  _is_finger_up(lm,  8,  6),
        "middle": _is_finger_up(lm, 12, 10),
        "ring":   _is_finger_up(lm, 16, 14),
        "pinky":  _is_finger_up(lm, 20, 18),
    }

def _only_index(st):
    return st["index"] and not st["middle"] and not st["ring"] and not st["pinky"]

def _index_middle(st):
    return st["index"] and st["middle"] and not st["ring"] and not st["pinky"]

def _tips_close(lm):
    a, b = lm.landmark[8], lm.landmark[12]
    return ((a.x - b.x)**2 + (a.y - b.y)**2) ** 0.5 < PINCH_DIST_THR

def _key_positions(fw, fh):
    positions = {}
    kbd_y = int(fh * START_Y_RATIO)
    max_keys = 10
    total_w = max_keys * KEY_W + (max_keys - 1) * KEY_GAP
    kbd_x = (fw - total_w) // 2

    for row_idx, row in enumerate(ROWS):
        row_y = kbd_y + row_idx * (KEY_H + KEY_GAP)
        if row == ["SPACE"]:
            sw = KEY_W * 6 + KEY_GAP * 5
            sx = kbd_x + (total_w - sw) // 2
            positions["SPACE"] = (sx, row_y, sw, KEY_H)
        else:
            num = len(row)
            rw = num * KEY_W + (num - 1) * KEY_GAP
            rx = kbd_x + (total_w - rw) // 2
            for ci, label in enumerate(row):
                x = rx + ci * (KEY_W + KEY_GAP)
                positions[label] = (x, row_y, KEY_W, KEY_H)
    return positions

def _in_key(fx, fy, kx, ky, kw, kh, m=8):
    return (kx - m) <= fx <= (kx + kw + m) and (ky - m) <= fy <= (ky + kh + m)

def _draw_keyboard(frame, positions, hover_key=None, pressed_key=None, charge=0.0):
    overlay = frame.copy()
    for label, (x, y, w, h) in positions.items():
        is_hov = label == hover_key
        is_prs = label == pressed_key
        color  = C_KEY_PRESSED if is_prs else (C_KEY_HOVER if is_hov else C_KEY_NORMAL)
        border = C_BORDER_HOV  if is_hov else C_BORDER
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(overlay, (x, y), (x + w, y + h), border, 2)
        if is_hov and charge > 0.01:
            bw = int(w * min(charge, 1.0))
            cv2.rectangle(overlay, (x, y + h - 5), (x + bw, y + h), C_KEY_CHARGE, -1)
        disp = {"⌫": "DEL", "⏎": "ENT", "SPACE": "SPACE"}.get(label, label)
        fs = 0.48 if len(disp) > 3 else (0.58 if len(disp) > 1 else 0.75)
        (tw, th), _ = cv2.getTextSize(disp, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
        cv2.putText(overlay, disp, (x + (w - tw) // 2, y + (h + th) // 2 - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, C_TEXT, 2, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.74, frame, 0.26, 0, frame)
    return frame

def _draw_input_bar(frame, text, fw):
    cv2.rectangle(frame, (0, 0), (fw, 52), C_INPUT_BG, -1)
    disp = ">>> " + (text[-60:] if len(text) > 60 else text)
    cv2.putText(frame, disp, (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.80, C_INPUT_TEXT, 2, cv2.LINE_AA)
    return frame

def _draw_status(frame, text, color, fw):
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.58, 2)
    cv2.putText(frame, text, (fw - tw - 14, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
#  Worker thread
# ─────────────────────────────────────────────────────────────────────────────

class _CamWorker(QThread):
    """
    Runs the camera + MediaPipe loop in a background thread.
    Emits:
      frame_ready  – processed BGR frame as numpy array
      key_pressed  – label of the key that was just pressed
      buffer_changed – current typed text after each keypress
    """
    frame_ready    = pyqtSignal(np.ndarray)
    key_pressed    = pyqtSignal(str)
    buffer_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)   # camera/mediapipe error message

    def __init__(self):
        super().__init__()
        self._running = True
        self.typed_text = ""

    def stop(self):
        self._running = False
        self.wait()

    # Hand connections for manual drawing (mediapipe 0.10.x removed drawing_utils)
    _HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (5,9),(9,10),(10,11),(11,12),
        (9,13),(13,14),(14,15),(15,16),
        (13,17),(17,18),(18,19),(19,20),
        (0,17),
    ]

    @staticmethod
    def _draw_landmarks_manual(frame, landmarks, fw, fh):
        """Replaces mp.solutions.drawing_utils for mediapipe 0.10.x"""
        pts = [(int(lm.x * fw), int(lm.y * fh)) for lm in landmarks]
        for a, b in _CamWorker._HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (0, 191, 255), 2)
        for pt in pts:
            cv2.circle(frame, pt, 3, (0, 255, 100), -1)

    def run(self):
        # ── Download hand landmarker model if missing ──────────────────────────
        model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "hand_landmarker.task"
        )
        if not os.path.exists(model_path):
            model_url = (
                "https://storage.googleapis.com/mediapipe-models/"
                "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
            )
            try:
                urllib.request.urlretrieve(model_url, model_path)
            except Exception as e:
                self.error_occurred.emit(f"❌ Failed to download hand model: {e}")
                return

        # ── Open camera ───────────────────────────────────────────────────────
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # CAP_DSHOW = faster on Windows
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.error_occurred.emit(
                "❌ Could not open camera. Check it is plugged in and not used by another app."
            )
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        smooth_state  = {"x": 0.0, "y": 0.0, "init": False}
        hover_frames  = 0
        pinch_frames  = 0
        last_press_t  = 0.0
        pressed_key   = None
        pressed_disp  = 0.0
        current_hover = None
        consecutive_failures = 0

        # ── Build mediapipe 0.10.x HandLandmarker ─────────────────────────────
        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.72,
            min_hand_presence_confidence=0.65,
            min_tracking_confidence=0.65,
        )

        try:
            with mp_vision.HandLandmarker.create_from_options(options) as detector:
                while self._running:
                    ret, frame = cap.read()
                    if not ret:
                        consecutive_failures += 1
                        if consecutive_failures > 30:
                            self.error_occurred.emit(
                                "❌ Camera stream lost. Try re-opening the keyboard."
                            )
                            break
                        time.sleep(0.03)
                        continue
                    consecutive_failures = 0

                    frame  = cv2.flip(frame, 1)
                    fh, fw = frame.shape[:2]
                    positions = _key_positions(fw, fh)

                    # mediapipe 0.10.x uses mp.Image with BGR→RGB conversion
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    results: HandLandmarkerResult = detector.detect(mp_image)

                    tip_x = tip_y = None
                    mode  = "neutral"

                    if results.hand_landmarks:
                        lm_list = results.hand_landmarks[0]  # list of NormalizedLandmark

                        # Draw skeleton manually (drawing_utils removed in 0.10.x)
                        self._draw_landmarks_manual(frame, lm_list, fw, fh)

                        # Wrap in a simple object to reuse _finger_states etc.
                        class _LM:
                            def __init__(self, landmarks):
                                self.landmark = landmarks
                        lm = _LM(lm_list)

                        st    = _finger_states(lm)
                        two   = _index_middle(st)
                        one   = _only_index(st)
                        close = _tips_close(lm) if two else False

                        raw_x = int(lm_list[8].x * fw)
                        raw_y = int(lm_list[8].y * fh)
                        tip_x, tip_y = _smooth(smooth_state, raw_x, raw_y)

                        if two and close:
                            mode = "pinch"
                        elif one:
                            mode = "aim"

                        if mode == "aim":
                            cv2.circle(frame, (tip_x, tip_y), 14, C_AIM, cv2.FILLED)
                            cv2.circle(frame, (tip_x, tip_y), 17, C_BORDER, 2)
                            _draw_status(frame, "☝ AIM", C_STATUS_AIM, fw)
                        elif mode == "pinch":
                            mx = int(lm_list[12].x * fw)
                            my = int(lm_list[12].y * fh)
                            cv2.circle(frame, (tip_x, tip_y), 14, C_PINCH, cv2.FILLED)
                            cv2.circle(frame, (mx, my),       14, C_PINCH, cv2.FILLED)
                            cv2.line(frame, (tip_x, tip_y), (mx, my), C_PINCH, 3)
                            _draw_status(frame, "✌ PRESS!", C_STATUS_PIN, fw)
                        else:
                            _draw_status(frame, "✋ NEUTRAL", C_STATUS_NEU, fw)

                    # Hover logic
                    now = time.time()
                    new_hover = None
                    if tip_x is not None and mode in ("aim", "pinch"):
                        for label, (kx, ky, kw, kh) in positions.items():
                            if _in_key(tip_x, tip_y, kx, ky, kw, kh):
                                new_hover = label
                                break

                    if new_hover != current_hover:
                        hover_frames = pinch_frames = 0
                        current_hover = new_hover
                    else:
                        if new_hover:
                            hover_frames = min(hover_frames + 1, HOVER_FRAMES + 10)

                    if mode == "pinch" and current_hover:
                        pinch_frames += 1
                    else:
                        pinch_frames = 0

                    # Trigger keypress
                    if (current_hover and
                            pinch_frames >= PINCH_FRAMES and
                            now - last_press_t > COOLDOWN_S):
                        key          = current_hover
                        last_press_t = now
                        pressed_key  = key
                        pressed_disp = now
                        pinch_frames = hover_frames = 0

                        if key == "⌫":
                            self.typed_text = self.typed_text[:-1]
                        elif key == "⏎":
                            submitted = self.typed_text
                            self.typed_text = ""
                            self.buffer_changed.emit(self.typed_text)
                            self.key_pressed.emit("SUBMIT:" + submitted)
                        elif key == "SPACE":
                            self.typed_text += " "
                        else:
                            self.typed_text += key

                        if key != "⏎":
                            self.key_pressed.emit(key)
                            self.buffer_changed.emit(self.typed_text)

                    if pressed_key and now - pressed_disp > 0.28:
                        pressed_key = None

                    charge = min(hover_frames / HOVER_FRAMES, 1.0) if current_hover else 0.0

                    frame = _draw_keyboard(
                        frame, positions,
                        hover_key   = current_hover,
                        pressed_key = pressed_key if (pressed_key and now - pressed_disp < 0.28) else None,
                        charge      = charge,
                    )
                    frame = _draw_input_bar(frame, self.typed_text, fw)

                    # Bottom hint bar
                    cv2.rectangle(frame, (0, fh - 30), (fw, fh), (8, 8, 16), -1)
                    cv2.putText(
                        frame,
                        "☝ Index=aim   ✌ Index+Middle close=PRESS   Close button to exit",
                        (10, fh - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (130, 130, 155), 1, cv2.LINE_AA,
                    )

                    self.frame_ready.emit(frame)

        finally:
            cap.release()


# ─────────────────────────────────────────────────────────────────────────────
#  Public widget
# ─────────────────────────────────────────────────────────────────────────────

class CameraKeyboardWidget(QWidget):
    """
    Inline camera keyboard. Embed inside a QStackedWidget page.

    Signals:
        query_submitted(str)  – fired when the user presses ⏎; carries the
                                typed text so the caller can submit it.
        closed()              – fired when the user clicks "Close Keyboard".
    """
    query_submitted = pyqtSignal(str)
    closed          = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0a0a1a;")
        self._worker = None
        self._build_ui()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background-color: #0d0d1f; border-bottom: 1px solid #00BFFF;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 0, 12, 0)

        title = QLabel("📷  Virtual Camera Keyboard")
        title.setStyleSheet("color: #00BFFF; font-size: 14px; font-weight: bold;")

        self._status_lbl = QLabel("Initialising camera…")
        self._status_lbl.setStyleSheet("color: #7B8794; font-size: 12px;")
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        close_btn = QPushButton("✕  Close Keyboard")
        close_btn.setFixedHeight(30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e;
                color: #00BFFF;
                font-size: 13px;
                border: 1px solid #00BFFF;
                border-radius: 15px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #c0392b; border-color: #c0392b; color: white; }
        """)
        close_btn.clicked.connect(self._on_close)

        bar_layout.addWidget(title)
        bar_layout.addWidget(self._status_lbl, stretch=1)
        bar_layout.addWidget(close_btn)
        root.addWidget(bar)

        # Camera feed
        self._feed_label = QLabel()
        self._feed_label.setAlignment(Qt.AlignCenter)
        self._feed_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._feed_label.setStyleSheet("background-color: #050510;")
        root.addWidget(self._feed_label, stretch=1)

        # Buffer display + submit button row
        bottom = QWidget()
        bottom.setFixedHeight(54)
        bottom.setStyleSheet("background-color: #0d0d1f; border-top: 1px solid #1a1a3e;")
        btm_layout = QHBoxLayout(bottom)
        btm_layout.setContentsMargins(14, 6, 14, 6)
        btm_layout.setSpacing(10)

        self._buffer_lbl = QLabel(">>> ")
        self._buffer_lbl.setStyleSheet(
            "color: #00FFB4; font-size: 15px; font-family: monospace;")
        self._buffer_lbl.setWordWrap(False)

        submit_btn = QPushButton("⏎  Send")
        submit_btn.setFixedSize(90, 36)
        submit_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #7B2FBE, stop:1 #00BFFF);
                color: white; font-size: 14px; font-weight: bold;
                border-radius: 18px; border: none;
            }
            QPushButton:hover   { background: #00BFFF; }
            QPushButton:pressed { background: #7B2FBE; }
        """)
        submit_btn.clicked.connect(self._manual_submit)

        btm_layout.addWidget(self._buffer_lbl, stretch=1)
        btm_layout.addWidget(submit_btn)
        root.addWidget(bottom)

    # ── Public API ────────────────────────────────────────────────────────────
    def start(self):
        """Call this when the widget becomes visible."""
        if self._worker and self._worker.isRunning():
            return
        self._worker = _CamWorker()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.key_pressed.connect(self._on_key)
        self._worker.buffer_changed.connect(self._on_buffer)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
        self._status_lbl.setText("Camera active — ☝ aim  ✌ press")

    def stop(self):
        """Call this when the widget is hidden / destroyed."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        self._status_lbl.setText("Camera stopped.")

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_frame(self, bgr: np.ndarray):
        h, w, ch = bgr.shape
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        lw  = self._feed_label.width()
        lh  = self._feed_label.height()
        self._feed_label.setPixmap(
            QPixmap.fromImage(img).scaled(lw, lh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _on_key(self, key: str):
        # Key is either a plain label, or 'SUBMIT:<typed_text>'
        if key.startswith("SUBMIT:"):
            text = key[len("SUBMIT:"):]
            if text.strip():
                self.query_submitted.emit(text.strip())
        # Any other key is just noted (buffer_changed handles display)

    def _on_buffer(self, text: str):
        display = text[-55:] if len(text) > 55 else text
        self._buffer_lbl.setText(">>> " + display)

    def _on_error(self, msg: str):
        """Show camera error in status label and feed area."""
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet("color: #e74c3c; font-size: 12px;")
        self._feed_label.setText(msg)
        self._feed_label.setStyleSheet(
            "background-color: #050510; color: #e74c3c; font-size: 16px;")
        self._feed_label.setAlignment(Qt.AlignCenter)

    def _manual_submit(self):
        """Submit button in the bottom bar."""
        if self._worker and self._worker.typed_text.strip():
            self.query_submitted.emit(self._worker.typed_text.strip())
            self._worker.typed_text = ""
            self._buffer_lbl.setText(">>> ")

    def _on_close(self):
        self.stop()
        self.closed.emit()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)