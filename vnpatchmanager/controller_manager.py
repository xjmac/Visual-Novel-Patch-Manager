import glob
import logging
import os
import select
import struct
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Virtual Action Constants
ACTION_UP = "UP"
ACTION_DOWN = "DOWN"
ACTION_LEFT = "LEFT"
ACTION_RIGHT = "RIGHT"
ACTION_SELECT = "SELECT"          # A / South button
ACTION_BACK = "BACK"              # B / East button
ACTION_QUICK_ACTION = "QUICK_ACTION"  # X / West button
ACTION_SEARCH = "SEARCH"          # Y / North button
ACTION_PREV_TAB = "PREV_TAB"      # L1 bumper
ACTION_NEXT_TAB = "NEXT_TAB"      # R1 bumper
ACTION_SCROLL_UP = "SCROLL_UP"    # L2 / Right Stick Up
ACTION_SCROLL_DOWN = "SCROLL_DOWN"# R2 / Right Stick Down

# Linux JS Event Spec: 32-bit time, 16-bit value, 8-bit type, 8-bit number
JS_EVENT_FORMAT = "IhBB"
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FORMAT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

AXIS_DEADZONE = 16000
REPEAT_DELAY = 0.28
REPEAT_INTERVAL = 0.08


class GamepadControllerManager:
    """
    Background gamepad listener utilizing native Linux joystick devices (/dev/input/js*).
    Provides zero-dependency, non-blocking controller integration for Steam Deck Game Mode.
    """

    def __init__(self, action_callback: Optional[Callable[[str], None]] = None):
        self.action_callback = action_callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fd: Optional[int] = None
        self._device_path: Optional[str] = None

        # Repeat state for directional hold navigation
        self._held_direction: Optional[str] = None
        self._held_since: float = 0.0
        self._last_repeat: float = 0.0

        # Axis states for stick and d-pad tracking
        self._axis_values: dict[int, int] = {}

    def start(self):
        """Starts the background gamepad listener thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="GamepadListener")
        self._thread.start()
        logger.info("Gamepad controller manager started.")

    def stop(self):
        """Stops the controller manager and closes open devices."""
        self._running = False
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        logger.info("Gamepad controller manager stopped.")

    def _find_joystick_device(self) -> Optional[str]:
        """Scans /dev/input for available joystick devices."""
        js_devices = sorted(glob.glob("/dev/input/js*"))
        if js_devices:
            return js_devices[0]
        return None

    def _emit(self, action: str):
        """Dispatches an action to the registered callback."""
        if self.action_callback and action:
            try:
                self.action_callback(action)
            except Exception as e:
                logger.error(f"Error in gamepad action callback: {e}")

    def _run_loop(self):
        """Main event polling loop."""
        while self._running:
            # Reconnect device if not currently open
            if self._fd is None:
                dev = self._find_joystick_device()
                if dev:
                    try:
                        self._fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                        self._device_path = dev
                        self._axis_values.clear()
                        logger.info(f"Connected to gamepad device: {dev}")
                    except Exception as e:
                        self._fd = None
                        time.sleep(1.0)
                        continue
                else:
                    time.sleep(1.0)
                    continue

            # Process directional repeat if held
            self._process_repeat()

            # Poll device with select
            if self._fd is None or not self._running:
                continue

            try:
                r, _, _ = select.select([self._fd], [], [], 0.02)
                if not r or not self._running or self._fd is None:
                    continue

                fd = self._fd
                if fd is None:
                    continue

                raw_data = os.read(fd, JS_EVENT_SIZE * 16)
                if not raw_data:
                    raise OSError("Gamepad disconnected")

                for i in range(0, len(raw_data), JS_EVENT_SIZE):
                    chunk = raw_data[i:i + JS_EVENT_SIZE]
                    if len(chunk) < JS_EVENT_SIZE:
                        break
                    _, val, event_type, number = struct.unpack(JS_EVENT_FORMAT, chunk)
                    self._handle_raw_event(val, event_type, number)

            except (OSError, select.error) as e:
                logger.debug(f"Gamepad device read error: {e}")
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except Exception:
                        pass
                    self._fd = None
                self._held_direction = None
                time.sleep(1.0)

    def _process_repeat(self):
        """Emits repeated directional actions when D-pad or stick is held."""
        if not self._held_direction:
            return
        now = time.time()
        if now - self._held_since >= REPEAT_DELAY:
            if now - self._last_repeat >= REPEAT_INTERVAL:
                self._last_repeat = now
                self._emit(self._held_direction)

    def _set_held_direction(self, direction: Optional[str]):
        if self._held_direction != direction:
            self._held_direction = direction
            if direction:
                self._held_since = time.time()
                self._last_repeat = self._held_since
                self._emit(direction)

    def _handle_raw_event(self, val: int, event_type: int, number: int):
        """Parses raw Linux joystick events into high-level gamepad actions."""
        # Ignore initial configuration snapshot events
        if event_type & JS_EVENT_INIT:
            if event_type & ~JS_EVENT_INIT == JS_EVENT_AXIS:
                self._axis_values[number] = val
            return

        if event_type == JS_EVENT_BUTTON:
            # Button press (val == 1)
            if val == 1:
                if number == 0:    # A (South)
                    self._emit(ACTION_SELECT)
                elif number == 1:  # B (East)
                    self._emit(ACTION_BACK)
                elif number == 2:  # X (West)
                    self._emit(ACTION_QUICK_ACTION)
                elif number == 3:  # Y (North)
                    self._emit(ACTION_SEARCH)
                elif number == 4:  # L1
                    self._emit(ACTION_PREV_TAB)
                elif number == 5:  # R1
                    self._emit(ACTION_NEXT_TAB)

        elif event_type == JS_EVENT_AXIS:
            self._axis_values[number] = val

            # Left Stick X (Axis 0) or D-Pad X (Axis 6)
            if number in (0, 6):
                if val < -AXIS_DEADZONE:
                    self._set_held_direction(ACTION_LEFT)
                elif val > AXIS_DEADZONE:
                    self._set_held_direction(ACTION_RIGHT)
                else:
                    # Check if vertical axis is still pressed before clearing
                    vert_val = self._axis_values.get(1 if number == 0 else 7, 0)
                    if vert_val < -AXIS_DEADZONE:
                        self._set_held_direction(ACTION_UP)
                    elif vert_val > AXIS_DEADZONE:
                        self._set_held_direction(ACTION_DOWN)
                    else:
                        self._set_held_direction(None)

            # Left Stick Y (Axis 1) or D-Pad Y (Axis 7)
            elif number in (1, 7):
                if val < -AXIS_DEADZONE:
                    self._set_held_direction(ACTION_UP)
                elif val > AXIS_DEADZONE:
                    self._set_held_direction(ACTION_DOWN)
                else:
                    horiz_val = self._axis_values.get(0 if number == 1 else 6, 0)
                    if horiz_val < -AXIS_DEADZONE:
                        self._set_held_direction(ACTION_LEFT)
                    elif horiz_val > AXIS_DEADZONE:
                        self._set_held_direction(ACTION_RIGHT)
                    else:
                        self._set_held_direction(None)

            # Right Stick Y (Axis 4) / Triggers (Axis 2 / 5) for Fast Page Scrolling
            elif number == 4:
                if val < -AXIS_DEADZONE:
                    self._emit(ACTION_SCROLL_UP)
                elif val > AXIS_DEADZONE:
                    self._emit(ACTION_SCROLL_DOWN)
