"""
YouTubeGestureController.py
============================
Gesture-based YouTube controller (fully automatic, zero UI friction).

HOW IT WORKS
------------
  1. App starts  →  _YTMonitor begins silently polling for YouTube in Chrome.
                    Camera does NOT open yet.
  2. YouTube detected  →  Camera + MediaPipe start automatically.
                          Jarvis overlay appears.
  3. YouTube closed  →  Camera released, overlay hides.
                        Monitor keeps running — ready for next YouTube session.
  4. User clicks ✕  →  Camera released, overlay hides.
                        Monitor keeps running — re-opens automatically
                        whenever YouTube is opened again.

Gesture Map
-----------
  ☝  Index only       →  Cursor pointer  (moves OS mouse)
  ✊  Closed fist      →  Scroll  (raise fist = scroll up, lower = scroll down)
  ✌  Index+Mid pinch  →  Click / Select
  ✋  Open palm 5f     →  Play / Pause  (hold ~0.4 s)
  🤙  Pinky only       →  Next video  (Shift+N)
  👍  Thumb only       →  Previous video  (Shift+P)
  🤏  Thumb+Idx pinch  →  Volume  (raise = vol up, lower = vol down)

FIXES APPLIED
-------------
  1. cv2.error on cap.release() — wrapped in try/except (OpenCV/DirectShow bug).
  2. Prefer CAP_MSMF over CAP_DSHOW — more stable on modern Windows.
  3. Added pre-release cleanup step before cap.release().
  4. Worker thread join timeout increased for safer shutdown.
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import os
import sys
import time
import math
import urllib.request
from collections import deque

# ── third-party ───────────────────────────────────────────────────────────────
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

import psutil
import win32gui
import win32con

import pyautogui
import keyboard as kb

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap

# ── PyAutoGUI global safety ───────────────────────────────────────────────────
# SECURITY FIX: FAILSAFE must stay True so moving the mouse to any screen
# corner raises FailSafeException and stops runaway automation immediately.
pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.0   # 0.0 keeps gesture response real-time

# ─────────────────────────────────────────────────────────────────────────────
#  Tuning constants
# ─────────────────────────────────────────────────────────────────────────────

# Cursor (EMA smoothing)
SMOOTH_ALPHA       = 0.45    # lower  = snappier cursor
CURSOR_SENSITIVITY = 1.70    # >1 amplifies hand movement across screen

# Scroll (fist)
FIST_SCROLL_DEAD   = 0.006   # normalised wrist-y dead-zone (filters tremor)
FIST_SCROLL_SCALE  = 22      # wrist delta → scroll ticks multiplier
FIST_SCROLL_MAX    = 10      # cap ticks per event
FIST_VEL_WIN       = 6       # velocity averaging window (frames)
SCROLL_COOLDOWN    = 0.045   # seconds between scroll events

# Volume (thumb+index pinch)
VOL_DEAD           = 0.010   # min normalised delta to trigger volume step
VOL_COOLDOWN       = 0.12    # seconds between volume steps

# Discrete gesture cooldown (click / next / prev / pause)
GESTURE_COOLDOWN   = 0.55

# Pause needs a brief hold so open-palm transitions don't misfire
PAUSE_HOLD_FRAMES  = 10

# Pinch thresholds (normalised tip-to-tip distance)
IDX_MID_PINCH_THR  = 0.052
THB_IDX_PINCH_THR  = 0.052

# ─────────────────────────────────────────────────────────────────────────────
#  Colour palette  (BGR)
# ─────────────────────────────────────────────────────────────────────────────
_C = dict(
    active   = (0,   255, 120),  # neon-green
    inactive = (90,  90,  110),  # muted grey
    gesture  = (0,   191, 255),  # cyan
    cursor   = (0,   220, 255),
    click    = (255, 70,    0),
    scroll   = (170, 30,  255),
    vol      = (255, 195,   0),
    bg       = (8,   8,   24),
    text     = (220, 220, 240),
)

_GESTURE_LABELS = {
    "neutral": "—",
    "cursor":  "☝  CURSOR",
    "scroll":  "✊  SCROLL",
    "click":   "✌  CLICK",
    "pause":   "✋  PLAY / PAUSE",
    "next":    "🤙  NEXT",
    "prev":    "👍  PREVIOUS",
    "volume":  "🤏  VOLUME",
}

_HAND_CONN = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),
    (0,17),
]

_LEGEND = [
    "☝ INDEX only    = cursor",
    "✊ FIST          = scroll  ▲▼",
    "✌ IDX+MID pinch = click",
    "✋ OPEN PALM     = play/pause",
    "🤙 PINKY only    = next",
    "👍 THUMB only    = previous",
    "🤏 THUMB+IDX     = volume  ▲▼",
]


# ─────────────────────────────────────────────────────────────────────────────
#  Math / detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(state, key, raw, alpha=SMOOTH_ALPHA):
    prev = state.get(key)
    state[key] = raw if prev is None else alpha * prev + (1 - alpha) * raw
    return state[key]


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_up(lm, tip, pip):
    """Tip above (lower y) than PIP = finger extended."""
    return lm[tip].y < lm[pip].y


def _thumb_up(lm):
    """Thumb extended if tip is displaced horizontally from index MCP."""
    return abs(lm[4].x - lm[2].x) > 0.035 or abs(lm[4].x - lm[17].x) > 0.10


def _states(lm):
    return {
        "thumb":  _thumb_up(lm),
        "index":  _finger_up(lm, 8,  6),
        "middle": _finger_up(lm, 12, 10),
        "ring":   _finger_up(lm, 16, 14),
        "pinky":  _finger_up(lm, 20, 18),
    }


def _is_fist(lm):
    """
    True when all four finger tips are curled below their PIP joints.
    Margin of 0.01 lets a slightly-relaxed fist still trigger.
    Thumb intentionally skipped — it folds sideways, not down.
    """
    pairs = [(8,6), (12,10), (16,14), (20,18)]
    return all(lm[tip].y > lm[pip].y - 0.01 for tip, pip in pairs)


def _draw_landmarks(frame, lm, fw, fh):
    pts = [(int(l.x * fw), int(l.y * fh)) for l in lm]
    for a, b in _HAND_CONN:
        cv2.line(frame, pts[a], pts[b], (0, 191, 255), 2)
    for pt in pts:
        cv2.circle(frame, pt, 4, (0, 255, 100), -1)


# ─────────────────────────────────────────────────────────────────────────────
#  Chrome / YouTube window helpers  (Windows-specific)
# ─────────────────────────────────────────────────────────────────────────────

def _yt_hwnd():
    """Return HWND of a Chrome window whose title contains 'YouTube', or None."""
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if "YouTube" in t and "Chrome" in t:
                found.append(hwnd)
        return True
    win32gui.EnumWindows(_cb, None)
    return found[0] if found else None


def _focus_yt():
    h = _yt_hwnd()
    if h:
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(h)


def _yt_rect():
    h = _yt_hwnd()
    return win32gui.GetWindowRect(h) if h else None


def _send_key(key_str):
    _focus_yt()
    time.sleep(0.04)
    kb.press_and_release(key_str)


def _click_at(sx, sy):
    _focus_yt()
    pyautogui.moveTo(sx, sy, duration=0)
    pyautogui.click()


def _map_cursor(nx, ny, rect):
    l, t, r, b = rect
    cx = 0.5 + (nx - 0.5) * CURSOR_SENSITIVITY
    cy = 0.5 + (ny - 0.5) * CURSOR_SENSITIVITY
    return (
        int(l + max(0.0, min(1.0, cx)) * (r - l)),
        int(t + max(0.0, min(1.0, cy)) * (b - t)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  HUD overlay
# ─────────────────────────────────────────────────────────────────────────────

def _draw_hud(frame, fw, fh, gesture, yt_active, cursor_pos=None,
              scroll_dir="", vol_dir=""):
    # ── Top bar ───────────────────────────────────────────────────────────────
    cv2.rectangle(frame, (0, 0), (fw, 50), _C["bg"], -1)
    sc = _C["active"] if yt_active else _C["inactive"]
    txt = "▶ YouTube ACTIVE" if yt_active else "⏸ Watching for YouTube…"
    cv2.putText(frame, txt, (12, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.72, sc, 2, cv2.LINE_AA)

    label = _GESTURE_LABELS.get(gesture, gesture)
    (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)
    cv2.putText(frame, label, (fw - tw - 14, 33),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72, _C["gesture"], 2, cv2.LINE_AA)

    # ── Cursor crosshair ──────────────────────────────────────────────────────
    if cursor_pos:
        cx, cy = cursor_pos
        cv2.circle(frame, (cx, cy), 16, _C["cursor"], 2)
        cv2.line(frame,  (cx-20, cy), (cx+20, cy), _C["cursor"], 2)
        cv2.line(frame,  (cx, cy-20), (cx, cy+20), _C["cursor"], 2)

    # ── Scroll indicator ──────────────────────────────────────────────────────
    if scroll_dir:
        sym = "▲ SCROLL UP" if scroll_dir == "up" else "▼ SCROLL DOWN"
        cv2.putText(frame, sym, (fw//2 - 90, fh//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, _C["scroll"], 3, cv2.LINE_AA)

    # ── Volume indicator ──────────────────────────────────────────────────────
    if vol_dir:
        sym = "VOL ▲ UP" if vol_dir == "up" else "VOL ▼ DOWN"
        cv2.putText(frame, sym, (fw//2 - 80, fh//2 + 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, _C["vol"], 3, cv2.LINE_AA)

    # ── Bottom legend ─────────────────────────────────────────────────────────
    n   = len(_LEGEND)
    bar_h = 26 * n + 10
    cv2.rectangle(frame, (0, fh - bar_h), (fw, fh), _C["bg"], -1)
    for i, txt in enumerate(_LEGEND):
        y = fh - bar_h + 22 + i * 26
        cv2.putText(frame, txt, (14, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (155, 155, 185), 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
#  _YTMonitor — lightweight Chrome/YouTube watcher
#  Stays running ALWAYS (even when widget is closed via ✕).
#  Only emits signals on state CHANGES.
# ─────────────────────────────────────────────────────────────────────────────

class _YTMonitor(QThread):
    yt_found = pyqtSignal()   # YouTube appeared in Chrome
    yt_lost  = pyqtSignal()   # YouTube closed / navigated away

    def __init__(self):
        super().__init__()
        self._running    = True
        self._was_active = False

    def stop(self):
        self._running = False
        self.wait(3000)

    def run(self):
        while self._running:
            active = _yt_hwnd() is not None
            if active and not self._was_active:
                self._was_active = True
                self.yt_found.emit()
            elif not active and self._was_active:
                self._was_active = False
                self.yt_lost.emit()
            time.sleep(1.0)


# ─────────────────────────────────────────────────────────────────────────────
#  _YTWorker — camera + MediaPipe gesture loop
# ─────────────────────────────────────────────────────────────────────────────

class _YTWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    gesture     = pyqtSignal(str)
    yt_active   = pyqtSignal(bool)
    error       = pyqtSignal(str)

    # Model path — set once at class level so it's shared
    _MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "hand_landmarker.task")

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False
        self.wait(5000)   # FIX: increased from 4000 → 5000 ms for safer shutdown

    @classmethod
    def _ensure_model(cls):
        if os.path.exists(cls._MODEL_PATH):
            return True
        url = ("https://storage.googleapis.com/mediapipe-models/"
               "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task")
        try:
            urllib.request.urlretrieve(url, cls._MODEL_PATH)
            return True
        except Exception:
            return False

    # ── FIX: safe camera release helper ──────────────────────────────────────
    @staticmethod
    def _safe_release(cap):
        """
        Release a VideoCapture object without raising on the known
        OpenCV / DirectShow / MSMF cleanup exception on Windows.
        """
        if cap is None:
            return
        try:
            # Drain any pending frames so the driver buffer is clean
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception:
            pass
        try:
            cap.release()
        except Exception:
            pass  # Swallow cv2.error from DirectShow/MSMF teardown (harmless)

    def run(self):
        cap = None   # FIX: initialise to None so finally block is always safe

        # ── 1. Model ─────────────────────────────────────────────────────────
        if not self._ensure_model():
            self.error.emit("❌ Cannot load hand_landmarker.task model.")
            return

        # ── 2. Camera  (FIX: prefer MSMF → fall back to DSHOW → raw index) ──
        # CAP_MSMF (Media Foundation) is more stable on Windows 10/11 than the
        # older DirectShow backend and avoids the teardown exception.
        for backend in (cv2.CAP_MSMF, cv2.CAP_DSHOW, None):
            try:
                cap = (cv2.VideoCapture(0, backend)
                       if backend is not None
                       else cv2.VideoCapture(0))
                if cap.isOpened():
                    break
                self._safe_release(cap)
                cap = None
            except Exception:
                cap = None

        if cap is None or not cap.isOpened():
            self.error.emit("❌ Camera not available.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS,          30)

        # ── 3. MediaPipe ──────────────────────────────────────────────────────
        opts = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=self._MODEL_PATH),
            num_hands=1,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )

        # ── 4. State ──────────────────────────────────────────────────────────
        smooth         = {}          # EMA state dict
        last_action    = 0.0         # cooldown for discrete gestures
        last_scroll    = 0.0
        last_vol       = 0.0
        pause_frames   = 0           # hold counter for open-palm pause
        fist_y_hist    = deque(maxlen=FIST_VEL_WIN)
        prev_fist_y    = None        # wrist-y from previous frame (scroll)
        prev_vol_y     = None        # index-tip y from previous frame (volume)
        click_armed    = True        # resets after pinch releases
        yt_active      = False
        yt_check_t     = 0.0
        chrome_rect    = None
        rect_check_t   = 0.0
        scroll_dir     = ""
        vol_dir        = ""
        scroll_clear_t = 0.0
        vol_clear_t    = 0.0
        fail_count     = 0

        try:
            with mp_vision.HandLandmarker.create_from_options(opts) as det:
                while self._running:
                    # ── Read frame ────────────────────────────────────────────
                    ok, frame = cap.read()
                    if not ok:
                        fail_count += 1
                        if fail_count > 40:
                            self.error.emit("❌ Camera feed lost.")
                            break
                        time.sleep(0.02)
                        continue
                    fail_count = 0

                    frame = cv2.flip(frame, 1)
                    fh, fw = frame.shape[:2]
                    now   = time.time()

                    # ── Poll YouTube presence (every 1 s) ─────────────────────
                    if now - yt_check_t >= 1.0:
                        yt_check_t = now
                        yt_active  = _yt_hwnd() is not None
                        self.yt_active.emit(yt_active)

                    # ── Cache Chrome rect (every 0.5 s) ───────────────────────
                    if yt_active and now - rect_check_t >= 0.5:
                        rect_check_t = now
                        chrome_rect  = _yt_rect()

                    # ── Clear overlay after timeout ───────────────────────────
                    if scroll_dir and now - scroll_clear_t > 0.35:
                        scroll_dir = ""
                    if vol_dir and now - vol_clear_t > 0.35:
                        vol_dir = ""

                    # ── MediaPipe inference ───────────────────────────────────
                    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    results = det.detect(mp_img)

                    cur_g      = "neutral"
                    cursor_pos = None   # landmark position for HUD crosshair

                    if results.hand_landmarks:
                        lm = results.hand_landmarks[0]
                        _draw_landmarks(frame, lm, fw, fh)

                        st = _states(lm)

                        idx_tip = lm[8]
                        mid_tip = lm[12]
                        thb_tip = lm[4]
                        wrist   = lm[0]

                        # EMA-smoothed tip position (used for cursor + HUD)
                        sx_n = _ema(smooth, "cx", idx_tip.x)
                        sy_n = _ema(smooth, "cy", idx_tip.y)
                        px   = int(sx_n * fw)
                        py   = int(sy_n * fh)

                        # Precomputed distances
                        d_idx_mid = _dist(idx_tip, mid_tip)
                        d_thb_idx = _dist(thb_tip, idx_tip)

                        # ── Compound gesture flags ─────────────────────────────

                        # ☝  Index only
                        only_idx  = (st["index"] and not st["middle"]
                                     and not st["ring"] and not st["pinky"]
                                     and not st["thumb"])

                        # 👍 Thumb only
                        only_thb  = (st["thumb"] and not st["index"]
                                     and not st["middle"] and not st["ring"]
                                     and not st["pinky"])

                        # 🤙 Pinky only
                        only_pky  = (st["pinky"] and not st["index"]
                                     and not st["middle"] and not st["ring"]
                                     and not st["thumb"])

                        # ✌ Index + Middle up
                        idx_mid_up    = (st["index"] and st["middle"]
                                         and not st["ring"] and not st["pinky"])
                        idx_mid_pinch = idx_mid_up and d_idx_mid < IDX_MID_PINCH_THR

                        # 🤏 Thumb + Index pinch (volume)
                        thb_idx_pinch = (st["thumb"] and st["index"]
                                         and not st["middle"] and not st["ring"]
                                         and not st["pinky"]
                                         and d_thb_idx < THB_IDX_PINCH_THR)

                        # ✋ All fingers up
                        all_up = (st["index"] and st["middle"]
                                  and st["ring"]  and st["pinky"])

                        # ✊ Closed fist
                        fist = _is_fist(lm)

                        # ═══════════════════════════════════════════════════════
                        #  PRIORITY ORDER
                        # ═══════════════════════════════════════════════════════

                        # 1. ✋ Open palm → Play / Pause  (requires brief hold)
                        if all_up:
                            pause_frames += 1
                            cur_g      = "pause"
                            cursor_pos = (px, py)
                            prev_fist_y = None
                            prev_vol_y  = None
                            click_armed = True
                            fist_y_hist.clear()
                            if (pause_frames >= PAUSE_HOLD_FRAMES
                                    and now - last_action > GESTURE_COOLDOWN):
                                last_action  = now
                                pause_frames = 0
                                if yt_active:
                                    _send_key("space")
                                self.gesture.emit("pause")

                        # 2. 🤏 Thumb+Idx pinch → Volume
                        elif thb_idx_pinch:
                            pause_frames = 0
                            cur_g        = "volume"
                            click_armed  = True
                            prev_fist_y  = None
                            fist_y_hist.clear()
                            raw_y = idx_tip.y

                            if prev_vol_y is not None:
                                delta = raw_y - prev_vol_y
                                sd    = _ema(smooth, "vd", delta, 0.4)
                                if abs(sd) > VOL_DEAD and now - last_vol > VOL_COOLDOWN:
                                    last_vol = now
                                    if sd < 0:
                                        vol_dir = "up"
                                        if yt_active:
                                            kb.press_and_release("up")
                                    else:
                                        vol_dir = "down"
                                        if yt_active:
                                            kb.press_and_release("down")
                                    vol_clear_t = now
                                    self.gesture.emit("volume")
                            prev_vol_y = raw_y
                            cursor_pos = (px, py)

                        # 3. 🤙 Pinky only → Next video
                        elif only_pky:
                            pause_frames = 0
                            cur_g        = "next"
                            prev_fist_y  = None
                            prev_vol_y   = None
                            click_armed  = True
                            fist_y_hist.clear()
                            if now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                if yt_active:
                                    _send_key("shift+n")
                                self.gesture.emit("next")

                        # 4. 👍 Thumb only → Previous video
                        elif only_thb:
                            pause_frames = 0
                            cur_g        = "prev"
                            prev_fist_y  = None
                            prev_vol_y   = None
                            click_armed  = True
                            fist_y_hist.clear()
                            if now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                if yt_active:
                                    _send_key("shift+p")
                                self.gesture.emit("prev")

                        # 5. ✌ Index+Mid pinch → Click
                        elif idx_mid_pinch:
                            pause_frames = 0
                            cur_g        = "click"
                            prev_fist_y  = None
                            prev_vol_y   = None
                            fist_y_hist.clear()
                            cv2.circle(frame, (px, py), 22, _C["click"], 3)
                            if click_armed and now - last_action > GESTURE_COOLDOWN:
                                last_action = now
                                click_armed = False
                                if yt_active and chrome_rect:
                                    sx, sy = _map_cursor(sx_n, sy_n, chrome_rect)
                                    _click_at(sx, sy)
                                self.gesture.emit("click")

                        # 6. ✌ Index+Mid spread → re-arm click
                        elif idx_mid_up and not idx_mid_pinch:
                            pause_frames = 0
                            cur_g        = "neutral"
                            click_armed  = True
                            prev_fist_y  = None
                            prev_vol_y   = None
                            fist_y_hist.clear()

                        # 7. ☝ Index only → Cursor pointer  (pure movement, no scroll)
                        elif only_idx:
                            pause_frames  = 0
                            cur_g         = "cursor"
                            prev_vol_y    = None
                            prev_fist_y   = None
                            fist_y_hist.clear()

                            if yt_active and chrome_rect:
                                sx, sy = _map_cursor(sx_n, sy_n, chrome_rect)
                                pyautogui.moveTo(sx, sy, duration=0)
                            cursor_pos = (px, py)

                        # 8. ✊ Closed fist → Smooth scroll
                        elif fist:
                            pause_frames = 0
                            cur_g        = "scroll"
                            prev_vol_y   = None
                            click_armed  = True
                            # Anchor: wrist landmark — stable even with fingers curled
                            raw_y = wrist.y

                            if prev_fist_y is not None:
                                fist_y_hist.append(raw_y - prev_fist_y)

                                if len(fist_y_hist) >= 2:
                                    avg_d = sum(fist_y_hist) / len(fist_y_hist)

                                    if abs(avg_d) > FIST_SCROLL_DEAD:
                                        if now - last_scroll > SCROLL_COOLDOWN:
                                            last_scroll = now
                                            ticks = max(1, min(FIST_SCROLL_MAX,
                                                               int(abs(avg_d) * FIST_SCROLL_SCALE)))
                                            if avg_d < 0:           # fist raised  → scroll UP
                                                scroll_dir = "up"
                                                if yt_active:
                                                    pyautogui.scroll(ticks)
                                            else:                   # fist lowered → scroll DOWN
                                                scroll_dir = "down"
                                                if yt_active:
                                                    pyautogui.scroll(-ticks)
                                            scroll_clear_t = now
                                            self.gesture.emit("scroll")
                                    else:
                                        if now - scroll_clear_t > 0.15:
                                            scroll_dir = ""

                            prev_fist_y = raw_y
                            cursor_pos  = (int(wrist.x * fw), int(wrist.y * fh))

                        # 9. Neutral
                        else:
                            pause_frames = 0
                            prev_fist_y  = None
                            prev_vol_y   = None
                            click_armed  = True
                            cur_g        = "neutral"
                            fist_y_hist.clear()

                    else:
                        # No hand detected — reset everything
                        smooth.clear()
                        pause_frames = 0
                        prev_fist_y  = None
                        prev_vol_y   = None
                        click_armed  = True
                        cur_g        = "neutral"
                        fist_y_hist.clear()

                    # ── Draw HUD and emit frame ───────────────────────────────
                    _draw_hud(frame, fw, fh, cur_g, yt_active,
                              cursor_pos=cursor_pos,
                              scroll_dir=scroll_dir,
                              vol_dir=vol_dir)
                    self.frame_ready.emit(frame)

        finally:
            # FIX: use safe_release — swallows the cv2.error thrown by
            # DirectShow / MSMF drivers during teardown on Windows.
            self._safe_release(cap)


# ─────────────────────────────────────────────────────────────────────────────
#  YouTubeGestureWidget  — Qt widget embedding camera feed + controls
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeGestureWidget(QWidget):
    """
    Embedded inline widget.

    Lifecycle (automatic, no user action needed):
      start()           → starts _YTMonitor only (camera stays off)
      Monitor detects YouTube → _on_yt_found() → starts camera worker
      YouTube closes          → _on_yt_lost()  → stops camera worker
      User clicks ✕           → stops camera worker; monitor keeps running
                                so next YouTube session auto-triggers again.

    Signals:
      yt_detected  → GUI should show this widget
      yt_lost      → GUI can hide this widget
      closed       → user hit ✕ (GUI hides widget)
    """

    closed      = pyqtSignal()
    yt_detected = pyqtSignal()
    yt_lost     = pyqtSignal()

    _GESTURE_DESC = {
        "cursor":  "☝  Pointing",
        "scroll":  "✊  Scrolling",
        "click":   "✌  Clicked!",
        "volume":  "🤏  Volume",
        "pause":   "✋  Play / Pause",
        "next":    "🤙  Next video",
        "prev":    "👍  Previous",
        "neutral": "",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0a0a1a;")
        self._monitor   = None    # _YTMonitor — runs permanently after start()
        self._worker    = None    # _YTWorker  — runs only while YouTube active
        self._yt_active = False
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background:#0d0d1f; border-bottom:1px solid #FF0000;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 0, 14, 0)
        bl.setSpacing(10)

        yt_icon = QLabel("▶")
        yt_icon.setStyleSheet("color:#FF0000; font-size:22px; font-weight:bold;")

        title = QLabel("YouTube Gesture Controller  ·  AUTO")
        title.setStyleSheet("color:#fff; font-size:15px; font-weight:bold;")

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#444; font-size:16px;")
        self._dot.setToolTip("Green = YouTube active in Chrome")

        self._status = QLabel("Watching for YouTube in Chrome…")
        self._status.setStyleSheet("color:#666; font-size:12px;")
        self._status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        close_btn = QPushButton("✕  Close")
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet("""
            QPushButton { background:#1a1a2e; color:#FF4444; font-size:13px;
                          border:1px solid #FF4444; border-radius:16px; padding:0 14px; }
            QPushButton:hover { background:#c0392b; color:#fff; border-color:#c0392b; }
        """)
        close_btn.clicked.connect(self._on_close)

        bl.addWidget(yt_icon)
        bl.addWidget(title)
        bl.addSpacing(8)
        bl.addWidget(self._dot)
        bl.addWidget(self._status, stretch=1)
        bl.addWidget(close_btn)
        root.addWidget(bar)

        # Body
        body = QWidget()
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        # Camera feed
        self._feed = QLabel()
        self._feed.setAlignment(Qt.AlignCenter)
        self._feed.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._feed.setStyleSheet("background:#050510;")
        body_l.addWidget(self._feed, stretch=3)

        # Right panel
        panel = QWidget()
        panel.setFixedWidth(240)
        panel.setStyleSheet("background:#08081a; border-left:1px solid #1a1a3e;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 14, 12, 14)
        pl.setSpacing(5)

        h1 = QLabel("Gesture Map")
        h1.setStyleSheet("color:#FF3333; font-size:13px; font-weight:bold;")
        pl.addWidget(h1)

        gmap = [
            ("☝  Index only",       "Cursor pointer"),
            ("✊  Closed fist",      "Scroll  ▲▼"),
            ("✌  Index+Mid pinch",  "Click / Select"),
            ("✋  Open palm",        "Play / Pause"),
            ("🤙  Pinky only",       "Next video"),
            ("👍  Thumb only",       "Previous video"),
            ("🤏  Thumb+Idx pinch",  "Volume  ▲▼"),
        ]
        for g, a in gmap:
            row = QLabel(f"<b style='color:#00BFFF'>{g}</b><br>"
                         f"<span style='color:#999;font-size:11px'>{a}</span>")
            row.setWordWrap(True)
            row.setStyleSheet("padding:3px 0;")
            pl.addWidget(row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1a1a3e;")
        pl.addWidget(sep)

        pl.addWidget(QLabel("<b style='color:#FF3333;font-size:12px'>Last Gesture</b>"))
        self._log = QLabel("—")
        self._log.setWordWrap(True)
        self._log.setStyleSheet("color:#00FFB4; font-size:14px; padding:2px 0;")
        pl.addWidget(self._log)

        pl.addStretch(1)

        self._warn = QLabel("⚠  Open YouTube in\nGoogle Chrome to\nactivate controls.")
        self._warn.setWordWrap(True)
        self._warn.setAlignment(Qt.AlignCenter)
        self._warn.setStyleSheet(
            "color:#e8a020; font-size:12px; background:#1a1100;"
            " border-radius:6px; padding:8px;")
        pl.addWidget(self._warn)

        body_l.addWidget(panel)
        root.addWidget(body, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """
        Start the YouTube monitor ONLY.
        Camera opens only when YouTube is actually detected.
        Call once at app init — it keeps running until the app closes.
        """
        self._start_monitor()

    def stop(self):
        """Full stop (app shutdown)."""
        self._stop_worker()
        self._stop_monitor()

    # ── Monitor management ────────────────────────────────────────────────────

    def _start_monitor(self):
        if self._monitor and self._monitor.isRunning():
            return
        self._monitor = _YTMonitor()
        self._monitor.yt_found.connect(self._on_yt_found)
        self._monitor.yt_lost.connect(self._on_yt_lost)
        self._monitor.start()

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

    # ── Worker management ─────────────────────────────────────────────────────

    def _start_worker(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = _YTWorker()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.gesture.connect(self._on_gesture)
        self._worker.yt_active.connect(self._on_yt_active)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._status.setText("Camera active — detecting hand…")

    def _stop_worker(self):
        if self._worker:
            self._worker.stop()
            self._worker = None
        # Clear the feed so old frame doesn't persist
        self._feed.clear()
        self._feed.setStyleSheet("background:#050510;")

    # ── Monitor slots ─────────────────────────────────────────────────────────

    def _on_yt_found(self):
        """YouTube appeared → start camera, tell GUI to show us."""
        self._status.setText("YouTube detected ✔  starting camera…")
        self._dot.setStyleSheet("color:#00FF70; font-size:16px;")
        self._warn.setVisible(False)
        self._start_worker()
        self.yt_detected.emit()

    def _on_yt_lost(self):
        """YouTube closed → stop camera, tell GUI to hide us."""
        self._stop_worker()
        self._status.setText("YouTube closed — watching…")
        self._dot.setStyleSheet("color:#444; font-size:16px;")
        self._warn.setVisible(True)
        self.yt_lost.emit()

    # ── Worker slots ──────────────────────────────────────────────────────────

    def _on_frame(self, bgr: np.ndarray):
        h, w, ch = bgr.shape
        rgb  = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img  = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        lw, lh = self._feed.width(), self._feed.height()
        self._feed.setPixmap(
            QPixmap.fromImage(img).scaled(lw, lh, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))

    def _on_gesture(self, g: str):
        desc = self._GESTURE_DESC.get(g, g)
        if desc:
            self._log.setText(desc)

    def _on_yt_active(self, active: bool):
        self._yt_active = active
        self._dot.setStyleSheet(
            f"color:{'#00FF70' if active else '#888'}; font-size:16px;")
        if active:
            self._status.setText("YouTube active ✔  gestures live")
        else:
            self._status.setText("Waiting for YouTube…")

    def _on_error(self, msg: str):
        self._status.setText(msg)
        self._status.setStyleSheet("color:#e74c3c; font-size:12px;")
        self._feed.setText(msg)
        self._feed.setStyleSheet("background:#050510; color:#e74c3c; font-size:15px;")
        self._feed.setAlignment(Qt.AlignCenter)

    # ── Close button ──────────────────────────────────────────────────────────

    def _on_close(self):
        """
        Stop camera worker ONLY.
        Monitor keeps running so the next time YouTube opens it will
        auto-detect and re-open the camera automatically.
        """
        self._stop_worker()
        self._status.setText("Paused (monitor still watching…)")
        self.closed.emit()    # GUI will hide this widget

    def closeEvent(self, event):
        self._stop_worker()
        self._stop_monitor()
        super().closeEvent(event)