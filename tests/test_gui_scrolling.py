"""
Tests for Visual Novel Patch Manager GUI scrolling functionality:
- Canvas scrollregion configuration in Posters, Grid, and List views.
- Mouse wheel event handling across Linux (Button-4, Button-5) and MouseWheel (Wayland/Windows).
- Keyboard arrow key navigation with automatic scroll into view.
- Window resize adaptation preserving scrollregion and scrollability.
"""

import time
from unittest.mock import patch, MagicMock
from PIL import Image
import customtkinter as ctk

from vnpatchmanager.gui.app_window import VNPatchManagerApp
from vnpatchmanager.controller_manager import ACTION_DOWN, ACTION_UP


def _create_app(tmp_path):
    with patch.object(VNPatchManagerApp, 'refresh_data'):
        app = VNPatchManagerApp()
    app.geometry('1060x680')
    app.withdraw()

    def _mock_cover(*args, **kwargs):
        img = Image.new('RGB', (20, 20), color='blue')
        return ctk.CTkImage(light_image=img, dark_image=img, size=(20, 20))

    app.cover_manager.get_cover_image = MagicMock(side_effect=_mock_cover)
    return app


def test_canvas_scrollregion_populated_in_all_views(tmp_path):
    app = _create_app(tmp_path)

    mock_games = {
        str(900000 + i): {
            'name': f'Visual Novel Game {i}',
            'path': str(tmp_path / f'game_{i}'),
            'is_installed': True,
            'vndb': {'vn_title': f'VN {i}'}
        } for i in range(25)
    }

    canvas = app.scrollable_games._parent_canvas

    for view_mode in ['Posters', 'Grid', 'List']:
        app.view_var.set(view_mode)
        app._populate_game_list(mock_games)

        for _ in range(8):
            app.update()
            time.sleep(0.02)

        scrollregion = canvas.cget('scrollregion')
        assert scrollregion != '', f'scrollregion is empty in {view_mode} view'
        coords = [float(c) for c in scrollregion.split()]
        assert len(coords) == 4
        assert coords[3] > 600, f'Expected scrollable height > 600 in {view_mode}, got {coords[3]}'
        yview = canvas.yview()
        assert yview != (0.0, 1.0), f'Canvas yview should not be (0.0, 1.0) in {view_mode}'

    app.destroy()


def test_mouse_wheel_scrolling(tmp_path):
    app = _create_app(tmp_path)

    mock_games = {
        str(900000 + i): {
            'name': f'Visual Novel Game {i}',
            'path': str(tmp_path / f'game_{i}'),
            'is_installed': True,
            'vndb': {'vn_title': f'VN {i}'}
        } for i in range(30)
    }

    app._populate_game_list(mock_games)
    for _ in range(10):
        app.update()
        time.sleep(0.02)

    canvas = app.scrollable_games._parent_canvas
    assert len(app._card_entries) > 0
    card = app._card_entries[0]['card']

    # 1. Test Linux Button-5 (Scroll Down)
    canvas.yview_moveto(0.0)
    app.update()
    assert canvas.yview()[0] == 0.0

    card._canvas.event_generate('<Button-5>')
    app.update()
    after_down_top = canvas.yview()[0]
    assert after_down_top > 0.0, 'Button-5 should scroll canvas downwards'

    # 2. Test Linux Button-4 (Scroll Up)
    card._canvas.event_generate('<Button-4>')
    app.update()
    after_up_top = canvas.yview()[0]
    assert after_up_top < after_down_top, 'Button-4 should scroll canvas upwards'

    # 3. Test Delta-based mouse wheel (Wayland / Windows)
    canvas.yview_moveto(0.0)
    app.update()
    card._canvas.event_generate('<MouseWheel>', delta=-120)
    app.update()
    delta_down_top = canvas.yview()[0]
    assert delta_down_top > 0.0, 'Negative delta should scroll canvas downwards'

    card._canvas.event_generate('<MouseWheel>', delta=120)
    app.update()
    delta_up_top = canvas.yview()[0]
    assert delta_up_top < delta_down_top, 'Positive delta should scroll canvas upwards'

    app.destroy()


def test_arrow_key_navigation_scrolling(tmp_path):
    app = _create_app(tmp_path)

    mock_games = {
        str(900000 + i): {
            'name': f'Visual Novel Game {i}',
            'path': str(tmp_path / f'game_{i}'),
            'is_installed': True,
            'vndb': {'vn_title': f'VN {i}'}
        } for i in range(35)
    }

    app._populate_game_list(mock_games)
    for _ in range(12):
        app.update()
        time.sleep(0.02)

    canvas = app.scrollable_games._parent_canvas
    canvas.yview_moveto(0.0)
    app.update()

    app._focused_zone = 'LIBRARY'
    app._focused_card_idx = 0
    app._apply_focus_visuals()

    assert canvas.yview()[0] == 0.0

    # Step down repeatedly with Arrow DOWN
    for step in range(8):
        app._handle_controller_action(ACTION_DOWN)
        app.update()

    # Viewport must have scrolled downwards
    scrolled_top = canvas.yview()[0]
    assert scrolled_top > 0.3, f'Expected viewport to scroll down past 0.3, got {scrolled_top}'

    # Step back up repeatedly with Arrow UP
    for step in range(8):
        app._handle_controller_action(ACTION_UP)
        app.update()

    # Viewport must have scrolled back near the top
    returned_top = canvas.yview()[0]
    assert returned_top == 0.0, f'Expected viewport to return to top 0.0, got {returned_top}'

    app.destroy()


def test_window_resize_preserves_scrolling(tmp_path):
    app = _create_app(tmp_path)

    mock_games = {
        str(900000 + i): {
            'name': f'Visual Novel Game {i}',
            'path': str(tmp_path / f'game_{i}'),
            'is_installed': True,
            'vndb': {'vn_title': f'VN {i}'}
        } for i in range(20)
    }

    app._populate_game_list(mock_games)
    for _ in range(8):
        app.update()
        time.sleep(0.02)

    canvas = app.scrollable_games._parent_canvas

    # Simulate resize event
    event = MagicMock()
    event.width = 1280
    app._on_games_area_resized(event)
    app.update()

    scrollregion = canvas.cget('scrollregion')
    assert scrollregion != '', 'scrollregion must remain configured after resize'
    assert canvas.yview() != (0.0, 1.0)

    app.destroy()
