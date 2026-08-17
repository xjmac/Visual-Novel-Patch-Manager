import time
from unittest.mock import patch, MagicMock
import pytest
from vnpatchmanager.controller_manager import (
    GamepadControllerManager,
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_BACK,
    ACTION_QUICK_ACTION,
    ACTION_SEARCH,
    ACTION_PREV_TAB,
    ACTION_NEXT_TAB,
    ACTION_SCROLL_UP,
    ACTION_SCROLL_DOWN,
    JS_EVENT_BUTTON,
    JS_EVENT_AXIS,
    JS_EVENT_INIT
)


def test_controller_manager_lifecycle():
    with patch.object(GamepadControllerManager, "_find_joystick_device", return_value=None):
        mgr = GamepadControllerManager()
        mgr.start()
        assert mgr._running is True
        mgr.stop()
        assert mgr._running is False


def test_handle_raw_event_buttons():
    emitted = []
    mgr = GamepadControllerManager(action_callback=lambda act: emitted.append(act))

    # Test Button 0 (A) -> SELECT
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 0)
    assert emitted[-1] == ACTION_SELECT

    # Test Button 1 (B) -> BACK
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 1)
    assert emitted[-1] == ACTION_BACK

    # Test Button 2 (X) -> QUICK_ACTION
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 2)
    assert emitted[-1] == ACTION_QUICK_ACTION

    # Test Button 3 (Y) -> SEARCH
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 3)
    assert emitted[-1] == ACTION_SEARCH

    # Test Button 4 (L1) -> PREV_TAB
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 4)
    assert emitted[-1] == ACTION_PREV_TAB

    # Test Button 5 (R1) -> NEXT_TAB
    mgr._handle_raw_event(1, JS_EVENT_BUTTON, 5)
    assert emitted[-1] == ACTION_NEXT_TAB

    # Test Button Release (val == 0) -> Should NOT emit
    before_len = len(emitted)
    mgr._handle_raw_event(0, JS_EVENT_BUTTON, 0)
    assert len(emitted) == before_len


def test_handle_raw_event_axes_deadzone_and_direction():
    emitted = []
    mgr = GamepadControllerManager(action_callback=lambda act: emitted.append(act))

    # Axis 0 (Left Stick X): Inside deadzone -> No emission
    mgr._handle_raw_event(5000, JS_EVENT_AXIS, 0)
    assert len(emitted) == 0

    # Axis 0 (Left Stick X): Left (> deadzone negative) -> ACTION_LEFT
    mgr._handle_raw_event(-25000, JS_EVENT_AXIS, 0)
    assert emitted[-1] == ACTION_LEFT

    # Return to neutral
    mgr._handle_raw_event(0, JS_EVENT_AXIS, 0)

    # Axis 0 (Left Stick X): Right (> deadzone positive) -> ACTION_RIGHT
    mgr._handle_raw_event(25000, JS_EVENT_AXIS, 0)
    assert emitted[-1] == ACTION_RIGHT

    # Axis 1 (Left Stick Y): Up (< -deadzone) -> ACTION_UP
    mgr._handle_raw_event(0, JS_EVENT_AXIS, 0)
    mgr._handle_raw_event(-28000, JS_EVENT_AXIS, 1)
    assert emitted[-1] == ACTION_UP

    # Axis 1 (Left Stick Y): Down (> deadzone) -> ACTION_DOWN
    mgr._handle_raw_event(0, JS_EVENT_AXIS, 1)
    mgr._handle_raw_event(28000, JS_EVENT_AXIS, 1)
    assert emitted[-1] == ACTION_DOWN

    # Axis 4 (Right Stick Y): Scroll Up / Down
    mgr._handle_raw_event(-25000, JS_EVENT_AXIS, 4)
    assert emitted[-1] == ACTION_SCROLL_UP
    mgr._handle_raw_event(25000, JS_EVENT_AXIS, 4)
    assert emitted[-1] == ACTION_SCROLL_DOWN


def test_init_event_ignored():
    emitted = []
    mgr = GamepadControllerManager(action_callback=lambda act: emitted.append(act))

    # Init event should not trigger actions
    mgr._handle_raw_event(1, JS_EVENT_BUTTON | JS_EVENT_INIT, 0)
    mgr._handle_raw_event(30000, JS_EVENT_AXIS | JS_EVENT_INIT, 0)
    assert len(emitted) == 0


def test_axis_hold_repeat_timing():
    emitted = []
    mgr = GamepadControllerManager(action_callback=lambda act: emitted.append(act))

    # Push Left Stick Down
    mgr._handle_raw_event(28000, JS_EVENT_AXIS, 1)
    assert emitted == [ACTION_DOWN]

    # Advance time slightly before repeat delay -> should not repeat
    with patch("time.time", return_value=mgr._last_repeat + 0.1):
        mgr._process_repeat()
        assert len(emitted) == 1

    # Advance time past repeat delay -> should emit second repeat
    with patch("time.time", return_value=mgr._last_repeat + 0.35):
        mgr._process_repeat()
        assert len(emitted) == 2
        assert emitted[-1] == ACTION_DOWN


def test_find_joystick_device():
    with patch("glob.glob", return_value=["/dev/input/js0", "/dev/input/js1"]):
        mgr = GamepadControllerManager()
        assert mgr._find_joystick_device() == "/dev/input/js0"

    with patch("glob.glob", return_value=[]):
        mgr = GamepadControllerManager()
        assert mgr._find_joystick_device() is None


def test_emit_callback_exception_handling():
    def exploding_callback(action):
        raise RuntimeError("Callback crashed")

    mgr = GamepadControllerManager(action_callback=exploding_callback)
    # Should not raise exception
    mgr._emit(ACTION_SELECT)


def test_modal_controller_stack_delegation():
    # Test modal stack mechanics in isolation
    stack = []
    main_window_calls = []
    modal1_calls = []
    modal2_calls = []

    def main_handler(act):
        main_window_calls.append(act)

    def modal1_handler(act):
        modal1_calls.append(act)

    def modal2_handler(act):
        modal2_calls.append(act)

    def dispatch(act):
        if stack:
            stack[-1](act)
        else:
            main_handler(act)

    # 1. No modal active -> dispatches to main window
    dispatch(ACTION_SELECT)
    assert main_window_calls == [ACTION_SELECT]
    assert modal1_calls == []

    # 2. Push Modal 1 -> dispatches to Modal 1
    stack.append(modal1_handler)
    dispatch(ACTION_NEXT_TAB)
    dispatch(ACTION_DOWN)
    assert modal1_calls == [ACTION_NEXT_TAB, ACTION_DOWN]
    assert main_window_calls == [ACTION_SELECT]

    # 3. Push Modal 2 -> dispatches to Modal 2
    stack.append(modal2_handler)
    dispatch(ACTION_UP)
    assert modal2_calls == [ACTION_UP]
    assert modal1_calls == [ACTION_NEXT_TAB, ACTION_DOWN]

    # 4. Pop Modal 2 -> dispatches back to Modal 1
    stack.pop()
    dispatch(ACTION_BACK)
    assert modal1_calls == [ACTION_NEXT_TAB, ACTION_DOWN, ACTION_BACK]

    # 5. Pop Modal 1 -> dispatches back to main window
    stack.pop()
    dispatch(ACTION_PREV_TAB)
    assert main_window_calls == [ACTION_SELECT, ACTION_PREV_TAB]


