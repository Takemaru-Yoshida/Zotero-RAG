"""Colours and the application style sheet (ported from the web UI tokens)."""
from __future__ import annotations

from types import SimpleNamespace

C = SimpleNamespace(
    bg="#fbfaf8", fg="#151b32", card="#ffffff",
    primary="#223677", primary_hover="#1b2b60", primary_fg="#fbfaf8",
    secondary="#ebedf4", muted="#f3f1ed", muted_fg="#636a7e", border="#e4dfd8",
    verified="#298e60", partial="#e18d09", refuted="#d92626",
    marker="#ffe870", marker_ai="#c9e8d8", focus="#eef1fa",
)

# verdict -> (label, colour); order = severity shown in the fact-check page
VERDICTS = {
    "refuted": ("矛盾", C.refuted),
    "not_found": ("文献なし", C.muted_fg),
    "partial": ("一部支持", C.partial),
    "supported": ("支持", C.verified),
}

# Node colours of the relation graph (one per tag).
PALETTE = ["#2f4a9a", "#0f8a6a", "#c2410c", "#9333ea", "#0e7490", "#be185d",
           "#a16207", "#4d7c0f"]
NO_TAG_COLOR = "#94a3b8"

SERIF = "'Hiragino Mincho ProN', 'Yu Mincho', Georgia, serif"

STYLESHEET = f"""
QWidget {{ color: {C.fg}; font-size: 13px; }}
QMainWindow {{ background: {C.bg}; }}
QWidget#sidebar {{ background: {C.muted}; border-right: 1px solid {C.border}; }}
QWidget#sidebar QLabel {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#logo {{ font-size: 20px; font-weight: 700; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; }}
QLabel#title {{ font-size: 13px; font-weight: 600; }}
QLabel#muted {{ color: {C.muted_fg}; font-size: 12px; }}
QLabel#linkLabel {{ color: {C.primary}; font-weight: 500; }}
QLabel#stat {{ font-size: 24px; font-weight: 700; }}
QLabel#serif {{ font-family: {SERIF}; font-size: 14px; }}
QLabel#docTitle {{ font-family: {SERIF}; font-size: 22px; font-weight: 600; }}
QLabel#abstract {{
    background: {C.secondary}; border-radius: 8px; padding: 12px;
}}
QFrame#card {{
    background: {C.card}; border: 1px solid {C.border}; border-radius: 10px;
}}
QFrame#card[hover="true"] {{ border: 1px solid {C.primary}; }}
QPushButton {{
    padding: 7px 14px; border-radius: 8px; background: {C.primary};
    color: {C.primary_fg}; font-weight: 600; border: none;
}}
QPushButton:hover {{ background: {C.primary_hover}; }}
QPushButton:disabled {{ background: #a9b1cc; }}
QPushButton#nav {{
    text-align: left; padding: 9px 12px; background: transparent;
    color: {C.muted_fg}; font-weight: 500;
}}
QPushButton#nav:hover {{ background: {C.secondary}; color: {C.fg}; }}
QPushButton#nav:checked {{ background: {C.primary}; color: {C.primary_fg}; }}
QPushButton#outline, QPushButton#chip {{
    background: {C.card}; color: {C.fg}; border: 1px solid {C.border};
    font-weight: 500;
}}
QPushButton#outline:hover, QPushButton#chip:hover {{ background: {C.secondary}; }}
QPushButton#chip {{ padding: 3px 10px; border-radius: 11px; font-size: 12px; }}
QPushButton#chip:checked {{
    background: {C.primary}; color: {C.primary_fg}; border-color: {C.primary};
}}
QPushButton#link {{
    background: transparent; color: {C.primary}; padding: 2px 0;
    text-align: left; font-weight: 500;
}}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#tile {{
    background: {C.card}; color: {C.fg}; border: 1px solid {C.border};
    text-align: left; padding: 10px 12px; font-size: 13px;
}}
QPushButton#tile:checked {{ border: 2px solid {C.primary}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    padding: 7px 10px; border: 1px solid {C.border}; border-radius: 8px;
    background: {C.card}; selection-background-color: {C.marker};
    selection-color: {C.fg};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {C.primary}; }}
QTextBrowser {{
    border: none; background: {C.bg}; font-family: {SERIF}; font-size: 15px;
}}
QScrollArea {{ border: none; background: transparent; }}
QProgressBar {{
    border: none; border-radius: 3px; background: {C.secondary};
    max-height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ border-radius: 3px; background: {C.primary}; }}
QCheckBox {{ spacing: 8px; }}
QGraphicsView {{ border: none; background: {C.card}; }}
"""


def apply_theme(app) -> None:
    """Install the style sheet and a matching palette on the QApplication.

    Page backgrounds come from the palette rather than a blanket
    ``QWidget { background }`` rule, so widgets inside white cards stay
    transparent and the app looks the same in macOS light and dark mode.
    """
    from PyQt6.QtGui import QColor, QPalette

    palette = app.palette()
    for role, color in (
            (QPalette.ColorRole.Window, C.bg),
            (QPalette.ColorRole.Base, C.card),
            (QPalette.ColorRole.AlternateBase, C.muted),
            (QPalette.ColorRole.WindowText, C.fg),
            (QPalette.ColorRole.Text, C.fg),
            (QPalette.ColorRole.Button, C.card),
            (QPalette.ColorRole.ButtonText, C.fg),
            (QPalette.ColorRole.ToolTipBase, C.card),
            (QPalette.ColorRole.ToolTipText, C.fg),
            (QPalette.ColorRole.PlaceholderText, C.muted_fg),
            (QPalette.ColorRole.Highlight, C.marker),
            (QPalette.ColorRole.HighlightedText, C.fg)):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


def badge_style(color: str) -> str:
    """Tinted pill: coloured text on a 15 % tint of the same colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return (f"color: {color}; background: rgba({r},{g},{b},0.15); "
            "border-radius: 9px; padding: 2px 8px; font-size: 11px; "
            "font-weight: 600;")
