"""
YouTubeGestureController.py
============================
Gesture-based YouTube controller that:
  • Activates ONLY when YouTube is open in Google Chrome (checks every second)
  • Uses MediaPipe hand-tracking (mediapipe 0.10.x Tasks API) via QThread
  • Sends real OS-level keyboard / mouse actions to the Chrome window
  • Supports smooth cursor control, scrolling, video selection & playback

Gesture Map (UPDATED)
---------------------
  ☝  Index only                    → Virtual cursor (move) + scroll (vertical hand movement)
  ✌  Index + Middle (spread/pinch) → LEFT CLICK / SELECT
  ✋  All 5 fingers                 → SPACE (play/pause)
  🤙  Pinky only                    → Next video (Shift+N)
  👍  Thumb only                    → Previous video (Shift+P)
  🤏  Thumb + Index pinch           → Volume control (hand up = vol up, down = vol down)

Architecture
------------
  _YTWorker (QThread)
    ├─ detects YouTube/Chrome presence every 1 s (psutil + win32)
    ├─ runs MediaPipe HandLandmarker per frame
    └─ emits signals: frame_ready, gesture, status, yt_active

  YouTubeGestureWidget (QWidget)
    ├─ embeds the live camera feed
    ├─ shows gesture legend and status overlay
    └─ exposes start() / stop() / closed signal
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import os
import time
import math
import ctypes
import urllib.request

# ── third-party ───────────────────────────────────────────────────────────────
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

import psutil
import win32gui
import win32con
import win32api
import win32process

# PyAutoGUI is used ONLY for smooth cursor movement (has built-in failsafe)
import pyautogui

# keyboard for sending keystrokes to Chrome window
import keyboard as kb

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont, QColor

# ── PyAutoGUI safety ──────────────────────────────────────────────────────────
pyautogui.FAILSAFE = False   # we handle our own bounds
pyautogui.PAUSE    = 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  Constants & tuning
# ─────────────────────────────────────────────────────────────────────────────
SMOOTH_ALPHA        = 0.55    # cursor EMA — balanced smoothness vs responsiveness
SCROLL_ALPHA        = 0.50    # scroll EMA
PINCH_DIST_THR      = 0.055   # index+middle pinch threshold (normalized)
THUMB_IDX_THR       = 0.055   # thumb+index pinch threshold (volume control)
GESTURE_COOLDOWN    = 0.50    # seconds between discrete gesture triggers
SCROLL_COOLDOWN     = 0.06    # seconds between scroll ticks
VOL_COOLDOWN        = 0.10    # seconds between volume ticks
CURSOR_SENSITIVITY  = 1.5     # multiplier for cursor movement vs hand movement
FIST_HOLD_FRAMES    = 18      # frames to hold fist before "back" fires (unused now)
ALL5_HOLD_FRAMES    = 12      # frames to hold open hand before pause fires
CURSOR_SCROLL_DELTA = 0.012   # min normalised y-delta to trigger scroll in cursor mode
VOLUME_DELTA        = 0.010   # min normalised y-delta to trigger volume in pinch mode

# BGR colour palette
C_ACTIVE   = (0,  255, 120)   # neon green — YouTube active
C_INACTIVE = (100, 100, 120)  # muted grey — YouTube not found
C_GESTURE  = (0,  191, 255)   # cyan
C_CURSOR   = (0,  220, 255)
C_CLICK    = (255, 80,   0)
C_SCROLL   = (180, 40, 255)
C_VOL      = (255, 200,   0)  # gold — volume control
C_BORDER   = (0,  191, 255)
C_BG       = (10,   10,  30)
C_TEXT     = (255, 255, 255)

# Gesture names shown in the HUD
GESTURE_LABELS = {
    "neutral":    "— NEUTRAL",
    "cursor":     "☝ CURSOR / SCROLL",
    "click":      "✌ CLICK",
    "volume":     "🤏 VOLUME",
    "pause":      "✋ PLAY/PAUSE",
    "next":       "🤙 NEXT",
    "prev":       "👍 PREVIOUS",
}

# Hand connections (identical to hand_connections in mp.solutions.hands)
_HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),
    (0,17),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _smooth_val(state: dict, key: str, raw: float, alpha: float = SMOOTH_ALPHA) -> float:
    prev = state.get(key)
    if prev is None:
        state[key] = raw
    else:
        state[key] = alpha * prev + (1 - alpha) * raw
    return state[key]


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_up(lm, tip, pip) -> bool:
    return lm[tip].y < lm[pip].y


def _thumb_up(lm) -> bool:
    """
    More robust thumb detection: compare tip x to MCP joint x,
    accounting for hand orientation via wrist-to-index-MCP vector.
    """
    # Simple: thumb tip significantly extended away from index MCP
    return abs(lm[4].x - lm[2].x) > 0.035 or abs(lm[4].x - lm[17].x) > 0.10


def _finger_states(lm: list) -> dict:
    return {
        "thumb":  _thumb_up(lm),
        "index":  _finger_up(lm, 8,  6),
        "middle": _finger_up(lm, 12, 10),
        "ring":   _finger_up(lm, 16, 14),
        "pinky":  _finger_up(lm, 20, 18),
    }


def _draw_landmarks(frame, lm_list, fw, fh):
    pts = [(int(l.x * fw), int(l.y * fh)) for l in lm_list]
    for a, b in _HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (0, 191, 255), 2)
    for pt in pts:
        cv2.circle(frame, pt, 4, (0, 255, 100), -1)


# ─────────────────────────────────────────────────────────────────────────────
#  Chrome / YouTube detection helpers (Windows)
# ─────────────────────────────────────────────────────────────────────────────

def _get_chrome_youtube_hwnd() -> int | None:
    """
    Return the HWND of the Chrome window whose title contains 'YouTube',
    or None if no such window is found.
    """
    found = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if "YouTube" in title and "Chrome" in title:
            found.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return found[0] if found else None


def _is_youtube_chrome_running() -> bool:
    """Quick psutil scan — cheaper than EnumWindows for the poll loop."""
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] and "chrome" in proc.info["name"].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def _focus_chrome_youtube():
    """Bring the YouTube Chrome window to front."""
    hwnd = _get_chrome_youtube_hwnd()
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)


def _get_chrome_rect() -> tuple | None:
    """Return (left, top, right, bottom) of the Chrome YouTube window."""
    hwnd = _get_chrome_youtube_hwnd()
    if hwnd:
        return win32gui.GetWindowRect(hwnd)
    return None


def _send_key_to_youtube(key_str: str):
    """Focus Chrome + send OS keystroke."""
    _focus_chrome_youtube()
    time.sleep(0.04)
    kb.press_and_release(key_str)


def _click_at(screen_x: int, screen_y: int):
    """Move cursor and left-click."""
    _focus_chrome_youtube()
    pyautogui.moveTo(screen_x, screen_y, duration=0)
    pyautogui.click()


def _map_cursor(norm_x: float, norm_y: float, rect) -> tuple[int, int]:
    """
    Map normalized hand coordinates (0-1) to screen coordinates
    within the Chrome window rect.
    """
    l, t, r, b = rect
    w = r - l
    h = b - t
    cx = 0.5 + (norm_x - 0.5) * CURSOR_SENSITIVITY
    cy = 0.5 + (norm_y - 0.5) * CURSOR_SENSITIVITY
    sx = int(l + max(0.0, min(1.0, cx)) * w)
    sy = int(t + max(0.0, min(1.0, cy)) * h)
    return sx, sy


# ─────────────────────────────────────────────────────────────────────────────
#  OSD helpers drawn onto the camera frame
# ─────────────────────────────────────────────────────────────────────────────

def _draw_hud(frame, fw, fh, gesture: str, yt_active: bool,
              cursor_pos=None, scroll_dir: str = "", vol_dir: str = ""):
    # Top status bar
    status_color = C_ACTIVE if yt_active else C_INACTIVE
    cv2.rectangle(frame, (0, 0), (fw, 52), C_BG, -1)
    status_txt = "▶ YouTube ACTIVE — gestures live" if yt_active else "⏸ YouTube not detected in Chrome"
    cv2.putText(frame, status_txt, (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.70, status_color, 2, cv2.LINE_AA)

    # Gesture label (top-right)
    label = GESTURE_LABELS.get(gesture, gesture)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
    cv2.putText(frame, label, (fw - tw - 16, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, C_GESTURE, 2, cv2.LINE_AA)

    # Cursor crosshair
    if cursor_pos:
        cx, cy = cursor_pos
        cv2.circle(frame, (cx, cy), 14, C_CURSOR, 2)
        cv2.line(frame, (cx - 18, cy), (cx + 18, cy), C_CURSOR, 2)
        cv2.line(frame, (cx, cy - 18), (cx, cy + 18), C_CURSOR, 2)

    # Scroll arrow overlay
    if scroll_dir:
        arrow = "  SCROLL " + ("▲" if scroll_dir == "up" else "▼")
        cv2.putText(frame, arrow, (fw // 2 - 70, fh // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, C_SCROLL, 3, cv2.LINE_AA)

    # Volume indicator overlay
    if vol_dir:
        icon = "🔊  VOL " + ("▲  UP" if vol_dir == "up" else "▼  DOWN")
        cv2.putText(frame, icon, (fw // 2 - 80, fh // 2 + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, C_VOL, 3, cv2.LINE_AA)

    # Legend at bottom
    legend = [
        "☝ INDEX only   = cursor + scroll",
        "✌ IDX+MID pinch = click/select",
        "✋ ALL 5 fingers = play/pause",
        "🤙 PINKY only   = next video",
        "👍 THUMB only   = previous video",
        "🤏 THUMB+IDX    = volume ▲▼",
    ]
    cv2.rectangle(frame, (0, fh - 32 - 22 * len(legend)), (fw, fh), C_BG, -1)
    for i, txt in enumerate(legend):
        y = fh - 32 - 22 * (len(legend) - 1 - i)
        cv2.putText(frame, txt, (16, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 190), 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
#  Worker thread
# ─────────────────────────────────────────────────────────────────────────────

class _YTWorker(QThread):
    """
    Camera + MediaPipe loop.  Detects gestures and fires OS-level actions.
    """
    frame_ready = pyqtSignal(np.ndarray)
    gesture     = pyqtSignal(str)
    status      = pyqtSignal(str)
    yt_active   = pyqtSignal(bool)
    error       = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False
        self.wait(3000)

    @staticmethod
    def _download_model(path: str) -> bool:
        if os.path.exists(path):
            return True
        url = (
            "https://storage.googleapis.com/mediapipe-models/"
            "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
        )
        try:
            urllib.request.urlretrieve(url, path)
            return True
        except Exception:
            return False

    def run(self):
        # 1. Model
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "hand_landmarker.task")
        if not self._download_model(model_path):
            self.error.emit("❌ Could not download hand_landmarker.task model.")
            return

        # 2. Camera
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.error.emit("❌ Camera unavailable.")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)

        # 3. MediaPipe HandLandmarker
        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )

        # 4. State
        smooth            = {}
        last_action       = 0.0
        last_scroll       = 0.0
        last_vol          = 0.0
        all5_frames       = 0
        prev_cursor_y     = None    # for index-only scroll
        prev_vol_y        = None    # for thumb+index volume
        consecutive_fail  = 0
        yt_is_active      = False
        yt_check_t        = 0.0
        cur_gesture       = "neutral"
        cursor_screen     = None
        scroll_dir        = ""
        vol_dir           = ""
        scroll_clear_t    = 0.0
        vol_clear_t       = 0.0
        # Cache chrome rect — refresh only every 0.5 s to avoid spamming win32
        chrome_rect       = None
        chrome_rect_t     = 0.0
        # Debounce for click — require pinch to be released before re-firing
        click_armed       = True

        try:
            with mp_vision.HandLandmarker.create_from_options(options) as detector:
                while self._running:
                    ret, frame = cap.read()
                    if not ret:
                        consecutive_fail += 1
                        if consecutive_fail > 40:
                            self.error.emit("❌ Camera stream lost.")
                            break
                        time.sleep(0.02)
                        continue
                    consecutive_fail = 0

                    frame = cv2.flip(frame, 1)
                    fh, fw = frame.shape[:2]
                    now = time.time()

                    # ── YouTube presence check (every 1 s) ───────────────────
                    if now - yt_check_t >= 1.0:
                        yt_check_t = now
                        hwnd = _get_chrome_youtube_hwnd()
                        yt_is_active = hwnd is not None
                        self.yt_active.emit(yt_is_active)

                    # ── Chrome rect cache (every 0.5 s) ──────────────────────
                    if yt_is_active and now - chrome_rect_t >= 0.5:
                        chrome_rect_t = now
                        chrome_rect = _get_chrome_rect()

                    # ── Overlay fade timers ───────────────────────────────────
                    if scroll_dir and now - scroll_clear_t > 0.30:
                        scroll_dir = ""
                    if vol_dir and now - vol_clear_t > 0.30:
                        vol_dir = ""

                    # ── MediaPipe detection ───────────────────────────────────
                    rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    results = detector.detect(mp_img)

                    cur_gesture   = "neutral"
                    cursor_screen = None

                    if results.hand_landmarks:
                        lm = results.hand_landmarks[0]
                        _draw_landmarks(frame, lm, fw, fh)

                        st       = _finger_states(lm)
                        idx_tip  = lm[8]
                        mid_tip  = lm[12]
                        thb_tip  = lm[4]

                        # Smoothed normalised cursor position (index fingertip)
                        sx_n = _smooth_val(smooth, "cx", idx_tip.x)
                        sy_n = _smooth_val(smooth, "cy", idx_tip.y)
                        px   = int(sx_n * fw)
                        py   = int(sy_n * fh)

                        # Distance metrics
                        idx_mid_dist = _dist(idx_tip, mid_tip)
                        thb_idx_dist = _dist(thb_tip, idx_tip)

                        # ── Gesture flags ─────────────────────────────────────
                        only_idx = (st["index"]
                                    and not st["middle"]
                                    and not st["ring"]
                                    and not st["pinky"]
                                    and not st["thumb"])

                        only_thb = (st["thumb"]
                                    and not st["index"]
                                    and not st["middle"]
                                    and not st["ring"]
                                    and not st["pinky"])

                        only_pky = (st["pinky"]
                                    and not st["index"]
                                    and not st["middle"]
                                    and not st["ring"]
                                    and not st["thumb"])

                        # Index + middle both up (spread or pinch)
                        idx_mid_up = (st["index"]
                                      and st["middle"]
                                      and not st["ring"]
                                      and not st["pinky"])

                        # Pinch = index+middle close together while both raised
                        idx_mid_pinch = idx_mid_up and idx_mid_dist < PINCH_DIST_THR

                        # Thumb + index pinch (volume control)
                        thb_idx_pinch = (st["thumb"]
                                         and st["index"]
                                         and not st["middle"]
                                         and not st["ring"]
                                         and not st["pinky"]
                                         and thb_idx_dist < THUMB_IDX_THR)

                        # All 5 fingers up
                        all_up = (st["index"] and st["middle"]
                                  and st["ring"] and st["pinky"])

                        # ── Priority order ────────────────────────────────────

                        # 1. ALL 5 — Play / Pause (highest priority, needs hold)
                        if all_up:
                            all5_frames += 1
                            cur_gesture  = "pause"
                            cursor_screen = (px, py)
                            prev_cursor_y = None
                            prev_vol_y    = None
                            click_armed   = True
                            if all5_frames >= ALL5_HOLD_FRAMES and now - last_action > GESTURE_COOLDOWN:
                                last_action  = now
                                all5_frames  = 0
                                if yt_is_active:
                                    _send_key_to_youtube("space")
                                self.gesture.emit("pause")

                        # 2. Thumb + Index pinch — Volume control
                        elif thb_idx_pinch:
                            all5_frames   = 0
                            cur_gesture   = "volume"
                            raw_y         = lm[8].y
                            click_armed   = True
                            prev_cursor_y = None

                            if prev_vol_y is not None:
                                delta_y = raw_y - prev_vol_y
                                sdelta  = _smooth_val(smooth, "vol_d", delta_y, SCROLL_ALPHA)
                                if abs(sdelta) > VOLUME_DELTA and now - last_vol > VOL_COOLDOWN:
                                    last_vol = now
                                    if sdelta < 0:      # hand moved up → volume up
                                        vol_dir = "up"
                                        if yt_is_active:
                                            kb.press_and_release("up")
                                    else:               # hand moved down → volume down
                                        vol_dir = "down"
                                        if yt_is_active:
                                            kb.press_and_release("down")
                                    vol_clear_t = now
                                    self.gesture.emit("volume")
                            prev_vol_y = raw_y
                            cursor_screen = (px, py)

                        # 3. Pinky only — Next video
                        elif only_pky:
                            all5_frames   = 0
                            cur_gesture   = "next"
                            prev_cursor_y = None
                            prev_vol_y    = None
                            click_armed   = True
                            if now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                if yt_is_active:
                                    _send_key_to_youtube("shift+n")
                                self.gesture.emit("next")

                        # 4. Thumb only — Previous video
                        elif only_thb:
                            all5_frames   = 0
                            cur_gesture   = "prev"
                            prev_cursor_y = None
                            prev_vol_y    = None
                            click_armed   = True
                            if now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                if yt_is_active:
                                    _send_key_to_youtube("shift+p")
                                self.gesture.emit("prev")

                        # 5. Index + Middle pinch — Click / Select
                        elif idx_mid_pinch:
                            all5_frames   = 0
                            cur_gesture   = "click"
                            prev_cursor_y = None
                            prev_vol_y    = None
                            cv2.circle(frame, (px, py), 20, C_CLICK, 3)
                            if click_armed and now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                click_armed = False     # arm resets when pinch releases
                                if yt_is_active and chrome_rect:
                                    sx, sy = _map_cursor(sx_n, sy_n, chrome_rect)
                                    _click_at(sx, sy)
                                self.gesture.emit("click")

                        # 6. Index + Middle spread (not pinching) — re-arm click
                        elif idx_mid_up and not idx_mid_pinch:
                            all5_frames   = 0
                            cur_gesture   = "neutral"
                            click_armed   = True        # spread = ready to click again
                            prev_cursor_y = None
                            prev_vol_y    = None

                        # 7. Index only — Cursor movement + vertical scroll
                        elif only_idx:
                            all5_frames = 0
                            cur_gesture = "cursor"
                            prev_vol_y  = None
                            raw_y       = lm[8].y

                            # Move cursor on screen
                            if yt_is_active and chrome_rect:
                                mapped_sx, mapped_sy = _map_cursor(sx_n, sy_n, chrome_rect)
                                pyautogui.moveTo(mapped_sx, mapped_sy, duration=0)
                            cursor_screen = (px, py)

                            # Vertical hand movement → page scroll
                            if prev_cursor_y is not None:
                                delta_y = raw_y - prev_cursor_y
                                sdelta  = _smooth_val(smooth, "scroll_d", delta_y, SCROLL_ALPHA)
                                if abs(sdelta) > CURSOR_SCROLL_DELTA and now - last_scroll > SCROLL_COOLDOWN:
                                    last_scroll = now
                                    ticks = max(1, int(abs(sdelta) * 15))
                                    if sdelta < 0:       # hand up → scroll page up
                                        scroll_dir = "up"
                                        if yt_is_active:
                                            pyautogui.scroll(ticks)
                                    else:                # hand down → scroll page down
                                        scroll_dir = "down"
                                        if yt_is_active:
                                            pyautogui.scroll(-ticks)
                                    scroll_clear_t = now
                            prev_cursor_y = raw_y

                        # 8. Neutral — nothing
                        else:
                            all5_frames   = 0
                            prev_cursor_y = None
                            prev_vol_y    = None
                            click_armed   = True
                            cur_gesture   = "neutral"

                    else:
                        # No hand detected — reset all state
                        smooth.clear()
                        all5_frames   = 0
                        prev_cursor_y = None
                        prev_vol_y    = None
                        click_armed   = True
                        cur_gesture   = "neutral"

                    # ── Draw HUD ──────────────────────────────────────────────
                    _draw_hud(frame, fw, fh,
                              gesture=cur_gesture,
                              yt_active=yt_is_active,
                              cursor_pos=cursor_screen,
                              scroll_dir=scroll_dir,
                              vol_dir=vol_dir)

                    self.frame_ready.emit(frame)

        finally:
            cap.release()


# ─────────────────────────────────────────────────────────────────────────────
#  Public widget
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeGestureWidget(QWidget):
    """
    Drop-in inline widget.

    Signals:
        closed()  — user clicked Close
    """
    closed = pyqtSignal()

    _GESTURE_DESC = {
        "cursor":  "☝  Cursor / Scroll",
        "click":   "✌  Clicked!",
        "volume":  "🤏  Volume adjust",
        "pause":   "✋  Play / Pause",
        "next":    "🤙  Next video",
        "prev":    "👍  Previous video",
        "neutral": "",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0a0a1a;")
        self._worker = None
        self._yt_active = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background-color: #0d0d1f; border-bottom: 1px solid #FF0000;")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(14, 0, 14, 0)
        bar_l.setSpacing(10)

        yt_icon = QLabel("▶")
        yt_icon.setStyleSheet("color: #FF0000; font-size: 22px; font-weight: bold;")

        title = QLabel("YouTube Gesture Controller")
        title.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")

        self._yt_dot = QLabel("●")
        self._yt_dot.setStyleSheet("color: #555; font-size: 16px;")
        self._yt_dot.setToolTip("Green = YouTube detected in Chrome")

        self._status_lbl = QLabel("Initialising…")
        self._status_lbl.setStyleSheet("color: #7B8794; font-size: 12px;")
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        close_btn = QPushButton("✕  Close")
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #FF4444;
                font-size: 13px; border: 1px solid #FF4444;
                border-radius: 16px; padding: 0 14px;
            }
            QPushButton:hover { background-color: #c0392b; color: white; border-color: #c0392b; }
        """)
        close_btn.clicked.connect(self._on_close)

        bar_l.addWidget(yt_icon)
        bar_l.addWidget(title)
        bar_l.addSpacing(8)
        bar_l.addWidget(self._yt_dot)
        bar_l.addWidget(self._status_lbl, stretch=1)
        bar_l.addWidget(close_btn)
        root.addWidget(bar)

        # ── Body: camera feed + panel ─────────────────────────────────────────
        body   = QWidget()
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        self._feed = QLabel()
        self._feed.setAlignment(Qt.AlignCenter)
        self._feed.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._feed.setStyleSheet("background-color: #050510;")
        body_l.addWidget(self._feed, stretch=3)

        # Right panel
        panel   = QWidget()
        panel.setFixedWidth(250)
        panel.setStyleSheet("background-color: #08081a; border-left: 1px solid #1a1a3e;")
        panel_l = QVBoxLayout(panel)
        panel_l.setContentsMargins(12, 12, 12, 12)
        panel_l.setSpacing(6)

        lbl_legend = QLabel("Gesture Map")
        lbl_legend.setStyleSheet("color: #FF0000; font-size: 13px; font-weight: bold;")
        panel_l.addWidget(lbl_legend)

        gesture_map = [
            ("☝  Index only",        "Cursor + Scroll ▲▼"),
            ("✌  Index+Mid pinch",   "Click / Select"),
            ("✋  All 5 fingers",     "Play / Pause"),
            ("🤙  Pinky only",        "Next Video"),
            ("👍  Thumb only",        "Previous Video"),
            ("🤏  Thumb+Idx pinch",   "Volume ▲▼"),
        ]
        for gesture, action in gesture_map:
            row = QLabel(f"<b style='color:#00BFFF'>{gesture}</b><br>"
                         f"<span style='color:#aaa;font-size:11px'>{action}</span>")
            row.setWordWrap(True)
            row.setStyleSheet("padding: 4px 0;")
            panel_l.addWidget(row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #1a1a3e;")
        panel_l.addWidget(sep)

        log_title = QLabel("Action Log")
        log_title.setStyleSheet("color: #FF0000; font-size: 12px; font-weight: bold;")
        panel_l.addWidget(log_title)

        self._log_lbl = QLabel("—")
        self._log_lbl.setWordWrap(True)
        self._log_lbl.setStyleSheet("color: #00FFB4; font-size: 13px;")
        panel_l.addWidget(self._log_lbl)

        panel_l.addStretch(1)

        self._yt_warn = QLabel("⚠️  Open YouTube in\nGoogle Chrome to\nactivate controls.")
        self._yt_warn.setWordWrap(True)
        self._yt_warn.setAlignment(Qt.AlignCenter)
        self._yt_warn.setStyleSheet(
            "color: #e8a020; font-size: 12px; "
            "background: #1a1100; border-radius: 6px; padding: 8px;")
        panel_l.addWidget(self._yt_warn)

        body_l.addWidget(panel)
        root.addWidget(body, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = _YTWorker()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.gesture.connect(self._on_gesture)
        self._worker.status.connect(self._on_status)
        self._worker.yt_active.connect(self._on_yt_active)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._status_lbl.setText("Camera active  ● detecting…")

    def stop(self):
        if self._worker:
            self._worker.stop()
            self._worker = None
        self._status_lbl.setText("Stopped.")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_frame(self, bgr: np.ndarray):
        h, w, ch = bgr.shape
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        lw  = self._feed.width()
        lh  = self._feed.height()
        self._feed.setPixmap(
            QPixmap.fromImage(img).scaled(lw, lh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _on_gesture(self, g: str):
        desc = self._GESTURE_DESC.get(g, g)
        if desc:
            self._log_lbl.setText(desc)

    def _on_status(self, s: str):
        self._status_lbl.setText(s)

    def _on_yt_active(self, active: bool):
        self._yt_active = active
        self._yt_dot.setStyleSheet(
            f"color: {'#00FF70' if active else '#555'}; font-size: 16px;")
        self._yt_warn.setVisible(not active)
        if active:
            self._status_lbl.setText("YouTube detected ✔  controls live")
        else:
            self._status_lbl.setText("Watching for YouTube in Chrome…")

    def _on_error(self, msg: str):
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet("color: #e74c3c; font-size: 12px;")
        self._feed.setText(msg)
        self._feed.setStyleSheet(
            "background-color: #050510; color: #e74c3c; font-size: 16px;")
        self._feed.setAlignment(Qt.AlignCenter)

    def _on_close(self):
        self.stop()
        self.closed.emit()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)