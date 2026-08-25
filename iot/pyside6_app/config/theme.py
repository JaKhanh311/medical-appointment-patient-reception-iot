"""
Material Design 3 color tokens — Dark & Light mode support.
"""
from __future__ import annotations


# ── Dark Theme Palette ────────────────────────────────────────────────────────
DARK = {
    "background":                "#10141a",
    "on_background":             "#dfe2eb",
    "surface":                   "#10141a",
    "surface_dim":               "#10141a",
    "surface_bright":            "#353940",
    "surface_container":         "#1c2026",
    "surface_container_high":    "#262a31",
    "surface_container_highest": "#31353c",
    "surface_container_low":     "#181c22",
    "surface_container_lowest":  "#0a0e14",
    "surface_variant":           "#31353c",
    "on_surface":                "#dfe2eb",
    "on_surface_variant":        "#c2c6d6",
    "primary":                   "#adc6ff",
    "on_primary":                "#002e6a",
    "primary_container":         "#4d8eff",
    "on_primary_container":      "#00285d",
    "primary_fixed":             "#d8e2ff",
    "primary_fixed_dim":         "#adc6ff",
    "secondary":                 "#4edea3",
    "on_secondary":              "#003824",
    "secondary_container":       "#00a572",
    "secondary_fixed":           "#6ffbbe",
    "secondary_fixed_dim":       "#4edea3",
    "tertiary":                  "#ffb786",
    "tertiary_container":        "#df7412",
    "outline":                   "#8c909f",
    "outline_variant":           "#424754",
    "error":                     "#ffb4ab",
    "error_container":           "#93000a",
    "inverse_surface":           "#dfe2eb",
    "inverse_on_surface":        "#2d3137",
    "login_bg":                  "#0d1117",
}

# ── Light Theme Palette ───────────────────────────────────────────────────────
LIGHT = {
    "background":                "#f5f7fa",
    "on_background":             "#1a1c1e",
    "surface":                   "#f5f7fa",
    "surface_dim":               "#e8eaed",
    "surface_bright":            "#ffffff",
    "surface_container":         "#eef0f3",
    "surface_container_high":    "#e4e6e9",
    "surface_container_highest": "#d9dce0",
    "surface_container_low":     "#f2f4f7",
    "surface_container_lowest":  "#ffffff",
    "surface_variant":           "#dfe2e5",
    "on_surface":                "#1a1c1e",
    "on_surface_variant":        "#44474a",
    "primary":                   "#1a73e8",
    "on_primary":                "#ffffff",
    "primary_container":         "#1565c0",
    "on_primary_container":      "#ffffff",
    "primary_fixed":             "#d8e2ff",
    "primary_fixed_dim":         "#adc6ff",
    "secondary":                 "#00897b",
    "on_secondary":              "#ffffff",
    "secondary_container":       "#b2dfdb",
    "secondary_fixed":           "#b2dfdb",
    "secondary_fixed_dim":       "#80cbc4",
    "tertiary":                  "#e65100",
    "tertiary_container":        "#ffcc80",
    "outline":                   "#5f6368",
    "outline_variant":           "#dadce0",
    "error":                     "#d32f2f",
    "error_container":           "#fce4ec",
    "inverse_surface":           "#2e3133",
    "inverse_on_surface":        "#f0f0f2",
    "login_bg":                  "#f0f4f8",
}

# ── Active palette (mutable, switched at runtime) ─────────────────────────────
C: dict = dict(DARK)


def set_theme(mode: str) -> None:
    """Switch active palette. mode = 'dark' or 'light'."""
    global C
    C.clear()
    C.update(LIGHT if mode == "light" else DARK)


def get_theme_name() -> str:
    """Return current theme name based on background brightness."""
    return "light" if C.get("background", "#10141a") == LIGHT["background"] else "dark"


def build_qss(palette: dict | None = None) -> str:
    """Generate full QSS from a color palette dict."""
    p = palette or C
    return f"""
/* ── Base ── */
QWidget {{
    background-color: {p['background']};
    color: {p['on_surface']};
    font-family: "Inter", "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
    selection-background-color: {p['primary']};
    selection-color: {p['on_primary']};
}}
QMainWindow {{
    background-color: {p['background']};
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['outline_variant']};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['outline']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {p['outline_variant']};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['outline']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

/* ── Tooltip ── */
QToolTip {{
    background: {p['surface_container_highest']};
    color: {p['on_surface']};
    border: 1px solid {p['outline_variant']};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ── Sidebar nav buttons ── */
QPushButton#navBtn {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0px;
    text-align: left;
    color: {p['on_surface_variant']};
    padding: 9px 16px;
    font-size: 13px;
    font-weight: normal;
}}
QPushButton#navBtn:hover {{
    background: {p['surface_container_highest']};
    color: {p['on_surface']};
}}
QPushButton#navBtn:checked {{
    background: rgba({_hex_to_rgba(p['primary'], 0.12)});
    border-left-color: {p['primary']};
    color: {p['primary']};
    font-weight: 600;
}}

/* ── Header bar ── */
QFrame#headerBar {{
    background: {p['surface_container']};
    border-bottom: 1px solid {p['outline_variant']};
}}

/* ── Sidebar frame ── */
QFrame#sidebarFrame {{
    background: {p['surface_dim']};
    border-right: 1px solid {p['outline_variant']};
}}

/* ── Content cards ── */
QFrame#card {{
    background: {p['surface_container']};
    border: 1px solid {p['outline_variant']};
    border-radius: 8px;
}}
QFrame#cardLowest {{
    background: {p['surface_container_lowest']};
    border: 1px solid {p['outline_variant']};
    border-radius: 8px;
}}

/* ── Input fields ── */
QLineEdit {{
    background: {p['surface_container_lowest']};
    border: 1.5px solid {p['outline_variant']};
    border-radius: 4px;
    color: {p['on_surface']};
    padding: 9px 12px;
    font-size: 13px;
    selection-background-color: {p['primary']};
    selection-color: {p['on_primary']};
}}
QLineEdit:focus {{
    border-color: {p['primary']};
    border-width: 2px;
}}
QLineEdit:disabled {{
    color: {p['outline']};
    background: {p['surface_container_low']};
}}

/* ── Buttons ── */
QPushButton {{
    background: {p['surface_container_high']};
    color: {p['on_surface']};
    border: 1px solid {p['outline_variant']};
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton#primaryBtn {{
    background-color: {p['primary']};
    color: {p['on_primary']};
    border: none;
    border-radius: 4px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#primaryBtn:hover {{
    background: {p['primary_container']};
    color: {p['on_primary_container']};
}}
QPushButton#primaryBtn:pressed {{
    background: {p['primary_container']};
    color: {p['on_primary_container']};
}}
QPushButton#primaryBtn:disabled {{
    background: {p['outline_variant']};
    color: {p['outline']};
    border: 1px solid {p['outline_variant']};
}}
QPushButton#secondaryBtn {{
    background: {p['surface_container_high']};
    color: {p['on_surface']};
    border: 1.5px solid {p['outline']};
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton#secondaryBtn:hover {{
    background: {p['surface_container_highest']};
    border-color: {p['primary']};
}}
QPushButton#dangerBtn {{
    background: {p['error_container']};
    color: {p['error']};
    border: none;
    border-radius: 4px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#dangerBtn:hover {{
    background: #b00008;
}}

/* ── Theme toggle button ── */
QPushButton#themeToggleBtn {{
    background: {p['surface_container_high']};
    color: {p['on_surface_variant']};
    border: 1px solid {p['outline_variant']};
    border-radius: 14px;
    padding: 6px 12px;
    font-size: 12px;
}}
QPushButton#themeToggleBtn:hover {{
    background: {p['surface_container_highest']};
    color: {p['on_surface']};
    border-color: {p['primary']};
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {p['on_surface']};
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p['outline_variant']};
    border-radius: 2px;
    background: {p['surface_container_lowest']};
}}
QCheckBox::indicator:checked {{
    background: {p['primary']};
    border-color: {p['primary']};
}}

/* ── ComboBox ── */
QComboBox {{
    background: {p['surface_container_lowest']};
    border: 1px solid {p['outline_variant']};
    border-radius: 4px;
    color: {p['on_surface']};
    padding: 8px 12px;
    font-size: 13px;
}}
QComboBox:focus {{
    border-color: {p['primary']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {p['surface_container_high']};
    border: 1px solid {p['outline_variant']};
    color: {p['on_surface']};
    selection-background-color: {p['surface_container_highest']};
    selection-color: {p['on_surface']};
}}

/* ── Table ── */
QTableWidget {{
    background: {p['surface_container_lowest']};
    border: 1px solid {p['outline_variant']};
    border-radius: 4px;
    gridline-color: {p['outline_variant']};
    color: {p['on_surface']};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 6px 12px;
}}
QTableWidget::item:selected {{
    background: rgba({_hex_to_rgba(p['primary'], 0.15)});
    color: {p['on_surface']};
}}
QHeaderView::section {{
    background: {p['surface_container_high']};
    color: {p['on_surface_variant']};
    border: none;
    border-bottom: 1px solid {p['outline_variant']};
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    font-family: "JetBrains Mono", monospace;
}}

/* ── Labels ── */
QLabel#heading1 {{
    color: {p['on_surface']};
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.4px;
}}
QLabel#heading2 {{
    color: {p['on_surface']};
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.2px;
}}
QLabel#labelMono {{
    color: {p['on_surface_variant']};
    font-size: 11px;
    font-weight: 600;
    font-family: "JetBrains Mono", monospace;
}}
QLabel#bodyMuted {{
    color: {p['on_surface_variant']};
    font-size: 13px;
}}
QLabel#primaryAccent {{
    color: {p['primary']};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#secondaryAccent {{
    color: {p['secondary']};
    font-size: 11px;
    font-weight: 600;
    font-family: "JetBrains Mono", monospace;
}}
QLabel#errorLabel {{
    color: {p['error']};
    font-size: 12px;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {p['outline_variant']};
}}

/* ── Log area ── */
QTextEdit#logArea {{
    background: {p['surface_container_lowest']};
    border: none;
    border-radius: 0px;
    color: {p['on_surface_variant']};
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    padding: 8px;
}}
"""


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to 'R, G, B, alpha' for rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}, {alpha}"


# ── Default QSS (dark mode) ──────────────────────────────────────────────────
APP_QSS = build_qss(DARK)
