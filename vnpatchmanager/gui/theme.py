"""
SteamOS-inspired Visual Design System & Theme Engine for Visual Novel Patch Manager.
Defines layered surface elevations, high-contrast OLED/SteamOS color tokens,
typography scales, and touch-target dimensions.
"""

from typing import Tuple

# Surface Elevation Palette (SteamOS Dark Slate)
COLOR_CANVAS = "#0b0e14"               # Deep slate navy window canvas
COLOR_ELEVATION_1 = "#141a24"          # Toolbars, containers, tab bar
COLOR_BORDER_1 = "#1f2937"             # Elevation 1 subtle border
COLOR_ELEVATION_2 = "#1a2232"          # Cards, panels, inputs
COLOR_BORDER_2 = "#283548"             # Elevation 2 card border
COLOR_ELEVATION_3 = "#223048"          # Active / hover surface
COLOR_BORDER_FOCUSED = "#38bdf8"       # Focused card highlight (electric sky blue, 2px)
COLOR_BORDER_HOVER = "#475569"         # Subtle hover border

# Brand & Action Accents
COLOR_ACCENT_BLUE = "#38bdf8"          # Luminous electric sky blue
COLOR_PRIMARY_BLUE = "#0284c7"         # Primary interactive buttons
COLOR_PRIMARY_HOVER = "#0369a1"        # Primary button hover
COLOR_ACCENT_GREEN = "#10b981"         # Success / Add / Verified
COLOR_ACCENT_GREEN_HOVER = "#059669"   # Green button hover
COLOR_DANGER_RED = "#ef4444"           # Rollback / Remove
COLOR_DANGER_HOVER = "#dc2626"         # Danger button hover

# Status Pill & Badge Colors
COLOR_STATUS_PATCHED = "#10b981"       # Emerald green
COLOR_STATUS_READY = "#f59e0b"         # Amber
COLOR_STATUS_MISSING = "#ec4899"       # Sakura pink (Missing 18+ VNDB)
COLOR_STATUS_BACKUP = "#0ea5e9"        # Sky blue (Backed up)
COLOR_STATUS_MUTED = "#64748b"         # Slate gray

# Typography Colors
COLOR_TEXT_PRIMARY = "#f8fafc"         # Crisp readable white
COLOR_TEXT_SECONDARY = "#94a3b8"       # Slate light
COLOR_TEXT_MUTED = "#64748b"           # Slate muted
COLOR_TEXT_DARK = "#475569"            # Slate dark

# Gamepad Prompt Pill Colors
COLOR_PAD_BTN_BG = "#2a3447"
COLOR_PAD_BTN_FG = "#38bdf8"
COLOR_PAD_BTN_BORDER = "#3b82f6"

# Dimensions & Responsive Layout
POSTER_CARD_SIZE: Tuple[int, int] = (180, 270)      # 2:3 Visual Novel Portrait Poster
GRID_CARD_BANNER_SIZE: Tuple[int, int] = (280, 130) # Classic wide banner
LIST_ROW_BANNER_SIZE: Tuple[int, int] = (150, 70)   # Compact list thumbnail
HERO_BANNER_SIZE: Tuple[int, int] = (640, 220)      # Detail view hero header
MIN_TOUCH_TARGET: int = 44                          # Handheld touch target minimum height
CARD_RADIUS: int = 10                               # Rounded corners for cards
POSTER_COLUMNS_MIN: int = 3                         # Minimum poster columns on handheld
POSTER_COL_WIDTH: int = 210                         # Target width per column for responsive math
