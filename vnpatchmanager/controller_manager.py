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
REPEAT_DELAY = 0.25
REPEAT_INTERVAL = 0.07


class GamepadControllerManager:
    """
    Background gamepad listener utilizing native Linux joystick devices (/dev/input/js*).
    Provides zero-dependency, non-blocking controller integration for Steam Deck Game Mode.
    Monitors all accessible joystick devices concurrently (handling virtual devices like js1
    and hotplugged controllers).
    """

    def __init__(self, action_callback: Optional[Callable[[str], None]] = None):
        self.action_callback = action_callback
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._device_lock = threading.Lock()

        # Multi-device file descriptor mappings: dev_path -> fd, fd -> dev_path
        self._open_devices: dict[str, int] = {}
        self._fd_to_path: dict[int, str] = {}

        # State tracking for axis D-pad / sticks: (dev_path, axis_num) -> val
        self._axis_values: dict[tuple[str, int], int] = {}
        self._held_direction: Optional[str] = None
        self._held_since: float = 0.0
        self._last_repeat: float = 0.0

        # Debounce tracking across multiple devices
        self._last_emitted_action: Optional[str] = None
        self._last_emitted_time: float = 0.0

    @property
    def _fd(self) -> Optional[int]:
        """Backwards compatibility accessor for primary file descriptor."""
        with self._device_lock:
            return next(iter(self._open_devices.values()), None)

    @property
    def _device_path(self) -> Optional[str]:
        """Backwards compatibility accessor for primary device path."""
        with self._device_lock:
            return next(iter(self._open_devices.keys()), None)

    def start(self):
        """Starts background gamepad polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="GamepadListener")
        self._thread.start()

    def stop(self):
        """Stops background thread and releases all device descriptors."""
        self._running = False
        with self._device_lock:
            for dev_path, fd in list(self._open_devices.items()):
                try:
                    os.close(fd)
                except Exception:
                    pass
            self._open_devices.clear()
            self._fd_to_path.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _find_joystick_device(self) -> Optional[str]:
        """Finds the first accessible joystick device file in /dev/input."""
        devs = self._find_all_joystick_devices()
        return devs[0] if devs else None

    def _find_all_joystick_devices(self) -> list[str]:
        """Finds all accessible joystick device files in /dev/input."""
        js_devs = sorted(glob.glob("/dev/input/js*"))
        accessible = []
        for dev in js_devs:
            try:
                if os.access(dev, os.R_OK):
                    accessible.append(dev)
            except Exception:
                pass
        return accessible

    def _get_device_name(self, fd: int) -> str:
        """Queries the joystick device name using Linux ioctl JSIOCGNAME if available."""
        try:
            import fcntl
            buf = bytearray(128)
            # JSIOCGNAME(128) = 0x80806a13
            fcntl.ioctl(fd, 0x80806a13, buf)
            return buf.split(b"\x00")[0].decode("utf-8", errors="replace").strip()
        except Exception:
            return "Generic Gamepad"

    def _refresh_devices(self):
        """Opens newly connected joystick devices and purges stale ones."""
        accessible_list = self._find_all_joystick_devices()
        accessible_set = set(accessible_list)

        with self._device_lock:
            # Close and remove devices no longer accessible
            for dev_path in list(self._open_devices.keys()):
                if dev_path not in accessible_set:
                    self._close_device_locked(dev_path)

            # Open any new accessible devices in deterministic order
            for dev_path in accessible_list:
                if dev_path not in self._open_devices:
                    try:
                        fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
                        dev_name = self._get_device_name(fd)
                        self._open_devices[dev_path] = fd
                        self._fd_to_path[fd] = dev_path
                        logger.info(f"Connected to gamepad device: {dev_path} ({dev_name})")
                    except Exception as e:
                        logger.debug(f"Could not open {dev_path}: {e}")

    def _close_device(self, dev_path: str):
        """Safely closes an open joystick device."""
        with self._device_lock:
            self._close_device_locked(dev_path)

    def _close_device_locked(self, dev_path: str):
        fd = self._open_devices.pop(dev_path, None)
        if fd is not None:
            self._fd_to_path.pop(fd, None)
            try:
                os.close(fd)
            except Exception:
                pass
            logger.info(f"Disconnected gamepad device: {dev_path}")

    def _emit(self, action: str):
        """Dispatches an action to the registered callback with cross-device debouncing."""
        if not self.action_callback or not action:
            return

        now = time.time()
        # Debounce identical button actions across multiple devices within 40ms
        if action == self._last_emitted_action and (now - self._last_emitted_time) < 0.04:
            return

        self._last_emitted_action = action
        self._last_emitted_time = now

        try:
            self.action_callback(action)
        except Exception as e:
            logger.error(f"Error in gamepad action callback: {e}")

    def _run_loop(self):
        """Main event polling loop monitoring all accessible controllers simultaneously."""
        last_scan = 0.0

        while self._running:
            now = time.time()
            # Scan for newly plugged / created joystick devices periodically or if empty
            with self._device_lock:
                has_devices = bool(self._open_devices)
            if now - last_scan >= 1.0 or not has_devices:
                last_scan = now
                self._refresh_devices()

            # Process directional repeat if held
            self._process_repeat()

            with self._device_lock:
                if not self._open_devices or not self._running:
                    need_sleep = True
                else:
                    need_sleep = False
                    fds = list(self._open_devices.values())
                    fd_to_path_snapshot = dict(self._fd_to_path)

            if need_sleep:
                time.sleep(0.05)
                continue

            try:
                readable, _, _ = select.select(fds, [], [], 0.01)
                if not readable or not self._running:
                    continue

                for fd in readable:
                    dev_path = fd_to_path_snapshot.get(fd)
                    if not dev_path:
                        continue

                    try:
                        raw_data = os.read(fd, JS_EVENT_SIZE * 16)
                        if not raw_data:
                            self._close_device(dev_path)
                            continue

                        for i in range(0, len(raw_data), JS_EVENT_SIZE):
                            chunk = raw_data[i:i + JS_EVENT_SIZE]
                            if len(chunk) < JS_EVENT_SIZE:
                                break
                            _, val, event_type, number = struct.unpack(JS_EVENT_FORMAT, chunk)
                            self._handle_raw_event(val, event_type, number, dev_path=dev_path)

                    except (OSError, select.error) as e:
                        logger.debug(f"Device read error on {dev_path}: {e}")
                        self._close_device(dev_path)

            except (OSError, select.error) as e:
                logger.debug(f"Gamepad select error: {e}")
                time.sleep(0.05)

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

    def _handle_raw_event(self, val: int, event_type: int, number: int, dev_path: str = "default"):
        """Parses raw Linux joystick events into high-level gamepad actions."""
        # Ignore initial configuration snapshot events
        if event_type & JS_EVENT_INIT:
            if event_type & ~JS_EVENT_INIT == JS_EVENT_AXIS:
                self._axis_values[(dev_path, number)] = val
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
                # Support digital D-pad buttons (common on some pads/drivers)
                elif number in (11, 13):  # D-Pad Up
                    self._set_held_direction(ACTION_UP)
                elif number in (12, 14):  # D-Pad Down
                    self._set_held_direction(ACTION_DOWN)
                elif number in (15,):      # D-Pad Left
                    self._set_held_direction(ACTION_LEFT)
                elif number in (16,):      # D-Pad Right
                    self._set_held_direction(ACTION_RIGHT)
            elif val == 0:
                # Button release for D-pad buttons
                if number in (11, 12, 13, 14, 15, 16):
                    self._set_held_direction(None)

        elif event_type == JS_EVENT_AXIS:
            self._axis_values[(dev_path, number)] = val

            # Left Stick X (Axis 0) or D-Pad X (Axis 6)
            if number in (0, 6):
                if val < -AXIS_DEADZONE:
                    self._set_held_direction(ACTION_LEFT)
                elif val > AXIS_DEADZONE:
                    self._set_held_direction(ACTION_RIGHT)
                else:
                    # Check if vertical axis is still pressed before clearing
                    vert_val = self._axis_values.get((dev_path, 1 if number == 0 else 7), 0)
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
                    horiz_val = self._axis_values.get((dev_path, 0 if number == 1 else 6), 0)
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
