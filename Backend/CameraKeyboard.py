"""
Virtual Camera Keyboard — Backend/CameraKeyboard.py
=====================================================
Uses MediaPipe hand tracking + OpenCV to display an on-screen virtual keyboard
overlay on the live camera feed. Users "press" keys by hovering or tapping
their index finger tip over a key.

Usage:
    python Backend/CameraKeyboard.py

The typed text is written to Frontend/Files/UserQuery.data so the
main assistant pipeline picks it up and processes it.

Requirements (install if missing):
    pip install opencv-python mediapipe numpy
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import os
import sys

# ── Path helpers ──────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY_FILE = os.path.join(ROOT_DIR, "Frontend", "Files", "UserQuery.data")
MIC_FILE   = os.path.join(ROOT_DIR, "Frontend", "Files", "Mic.data")

# ── Keyboard layout ───────────────────────────────────────────────────────────
ROWS = [
    ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
    ["Z", "X", "C", "V", "B", "N", "M", "⌫", "⏎"],
    ["SPACE"],
]

KEY_W, KEY_H = 70, 60          # key size in pixels
KEY_GAP      = 8               # gap between keys
START_X      = 50              # keyboard left offset
START_Y_RATIO = 0.45           # keyboard top position (fraction of frame height)
HOVER_FRAMES  = 8              # frames finger must hover before registering press
COOLDOWN_S    = 0.35           # seconds between key presses

# ── Colors (BGR) ─────────────────────────────────────────────────────────────
C_KEY_NORMAL  = (30,  30,  50)
C_KEY_HOVER   = (120, 60, 200)
C_KEY_PRESSED = (0,  191, 255)
C_BORDER      = (0,  191, 255)
C_TEXT        = (255, 255, 255)
C_INPUT_BG    = (10,  10,  30)
C_INPUT_TEXT  = (0,  255, 180)


def key_positions(frame_h):
    """Return a dict: {label: (x, y, w, h)} for every key."""
    positions = {}
    kbd_y = int(frame_h * START_Y_RATIO)

    for row_idx, row in enumerate(ROWS):
        # Centre short rows
        total_w = len(row) * (KEY_W + KEY_GAP) - KEY_GAP
        # special wider SPACE key
        if len(row) == 1 and row[0] == "SPACE":
            total_w = KEY_W * 6 + KEY_GAP * 5

        row_x = START_X + (0 if row_idx < 3 else 0)
        row_y = kbd_y + row_idx * (KEY_H + KEY_GAP)

        if row == ["SPACE"]:
            w = KEY_W * 6 + KEY_GAP * 5
            positions["SPACE"] = (START_X + 2*(KEY_W + KEY_GAP), row_y, w, KEY_H)
        else:
            for col_idx, label in enumerate(row):
                x = START_X + col_idx * (KEY_W + KEY_GAP)
                positions[label] = (x, row_y, KEY_W, KEY_H)

    return positions


def draw_keyboard(frame, positions, hover_key=None, pressed_key=None):
    overlay = frame.copy()
    for label, (x, y, w, h) in positions.items():
        if label == pressed_key:
            color = C_KEY_PRESSED
        elif label == hover_key:
            color = C_KEY_HOVER
        else:
            color = C_KEY_NORMAL

        # Key background (semi-transparent rounded rect simulation)
        cv2.rectangle(overlay, (x, y), (x+w, y+h), color, -1)
        cv2.rectangle(overlay, (x, y), (x+w, y+h), C_BORDER, 2)

        # Key label
        display = label if label not in ("⌫", "⏎", "SPACE") else \
                  {"⌫": "DEL", "⏎": "ENTER", "SPACE": "SPACE"}[label]
        font_scale = 0.55 if len(display) > 2 else 0.75
        (tw, th), _ = cv2.getTextSize(display, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
        tx = x + (w - tw) // 2
        ty = y + (h + th) // 2
        cv2.putText(overlay, display, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, C_TEXT, 2, cv2.LINE_AA)

    # Blend for glassmorphism effect
    alpha = 0.72
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    return frame


def draw_input_bar(frame, text, frame_w):
    bar_h = 55
    cv2.rectangle(frame, (0, 0), (frame_w, bar_h), C_INPUT_BG, -1)
    display = ">>> " + text[-60:]   # show last 60 chars
    cv2.putText(frame, display, (12, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, C_INPUT_TEXT, 2, cv2.LINE_AA)
    cv2.putText(frame, "Press ENTER key to send | ESC to close | Q key=quit",
                (12, bar_h - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 150, 150), 1, cv2.LINE_AA)
    return frame


def fingertip_in_key(fx, fy, kx, ky, kw, kh, margin=10):
    return (kx - margin) <= fx <= (kx + kw + margin) and \
           (ky - margin) <= fy <= (ky + kh + margin)


def submit_query(text):
    """Write to UserQuery.data and set Mic.data to True so main.py processes it."""
    try:
        with open(QUERY_FILE, "w", encoding="utf-8") as f:
            f.write(text.strip())
        with open(MIC_FILE, "w", encoding="utf-8") as f:
            f.write("True")
        print(f"[CameraKeyboard] Submitted: {text.strip()}")
    except Exception as e:
        print(f"[CameraKeyboard] Error writing query: {e}")


def main():
    mp_hands = mp.solutions.hands
    mp_draw  = mp.solutions.drawing_utils

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[CameraKeyboard] ERROR: Cannot access camera.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    typed_text   = ""
    hover_key    = None
    hover_count  = {}
    last_press_t = 0.0
    pressed_key  = None
    pressed_disp = 0.0   # display flash duration

    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
    ) as hands:

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            frame_h, frame_w, _ = frame.shape
            positions = key_positions(frame_h)

            # MediaPipe hand detection
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)

            fingertip_x = fingertip_y = None

            if results.multi_hand_landmarks:
                for hand_lm in results.multi_hand_landmarks:
                    mp_draw.draw_landmarks(frame, hand_lm,
                                           mp_hands.HAND_CONNECTIONS,
                                           mp_draw.DrawingSpec(color=(0, 255, 100), thickness=2, circle_radius=4),
                                           mp_draw.DrawingSpec(color=(0, 191, 255), thickness=2))

                    # Index finger tip = landmark 8
                    tip = hand_lm.landmark[8]
                    fingertip_x = int(tip.x * frame_w)
                    fingertip_y = int(tip.y * frame_h)

                    # Draw fingertip circle
                    cv2.circle(frame, (fingertip_x, fingertip_y), 14,
                               (0, 255, 80), cv2.FILLED)
                    cv2.circle(frame, (fingertip_x, fingertip_y), 16,
                               C_BORDER, 2)

            # Determine which key (if any) is being hovered
            now = time.time()
            current_hover = None
            if fingertip_x is not None:
                for label, (kx, ky, kw, kh) in positions.items():
                    if fingertip_in_key(fingertip_x, fingertip_y, kx, ky, kw, kh):
                        current_hover = label
                        break

            # Accumulate hover frames
            if current_hover:
                hover_count[current_hover] = hover_count.get(current_hover, 0) + 1
                for k in list(hover_count):
                    if k != current_hover:
                        hover_count[k] = 0
            else:
                hover_count = {}

            # Register press after enough hover frames and past cooldown
            if (current_hover and
                    hover_count.get(current_hover, 0) >= HOVER_FRAMES and
                    now - last_press_t > COOLDOWN_S):

                key = current_hover
                last_press_t = now
                pressed_key  = key
                pressed_disp = now
                hover_count  = {}

                if key == "⌫":
                    typed_text = typed_text[:-1]
                elif key == "⏎":
                    if typed_text.strip():
                        submit_query(typed_text)
                        typed_text = ""
                elif key == "SPACE":
                    typed_text += " "
                else:
                    typed_text += key

            # Clear pressed flash after 0.2 s
            if pressed_key and now - pressed_disp > 0.25:
                pressed_key = None

            # Draw keyboard
            pk = pressed_key if (pressed_key and now - pressed_disp < 0.25) else None
            frame = draw_keyboard(frame, positions,
                                   hover_key=current_hover, pressed_key=pk)

            # Draw input bar at top
            frame = draw_input_bar(frame, typed_text, frame_w)

            # Help text — landmark confidence
            cv2.putText(frame, "Hover finger over key to type | Index finger = typing cursor",
                        (12, frame_h - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 120, 120), 1, cv2.LINE_AA)

            cv2.imshow("Jarvis — Virtual Camera Keyboard", frame)

            key_press = cv2.waitKey(1) & 0xFF
            if key_press == 27:    # ESC — close
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
