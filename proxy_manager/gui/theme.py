"""Paleta e stylesheet (QSS) centralizados, para que os widgets desenhados à mão (sparkline,
indicadores de status) usem exatamente as mesmas cores do restante da interface."""
from __future__ import annotations

PALETTE = {
    "bg": "#0f1117",
    "surface": "#171a24",
    "surface_alt": "#1e2230",
    "surface_hover": "#262b3c",
    "border": "#2b3044",
    "border_soft": "#232838",
    "text": "#eaecf3",
    "text_muted": "#9aa0b8",
    "text_faint": "#6b7189",
    "accent": "#5b8cff",
    "accent_hover": "#7aa3ff",
    "accent_pressed": "#4574e6",
    "accent_soft": "#243257",
    "success": "#33c07f",
    "success_soft": "#173226",
    "danger": "#f2574c",
    "danger_soft": "#3a1f1f",
    "warning": "#f0a93c",
    "warning_soft": "#332a16",
}


def build_stylesheet() -> str:
    p = PALETTE
    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Cantarell", "Ubuntu", sans-serif;
    font-size: 13px;
    color: {p['text']};
    outline: none;
}}

QMainWindow, QWidget#Root {{
    background-color: {p['bg']};
}}

QWidget {{
    background-color: transparent;
}}

QToolTip {{
    background-color: {p['surface_alt']};
    color: {p['text']};
    border: 1px solid {p['border']};
    padding: 6px 8px;
    border-radius: 6px;
}}

/* ---------- Sidebar ---------- */
QFrame#Sidebar {{
    background-color: {p['surface']};
    border-right: 1px solid {p['border_soft']};
}}

QLabel#BrandTitle {{
    color: {p['text']};
    font-size: 17px;
    font-weight: 600;
    padding: 4px 4px;
}}

QLabel#BrandSubtitle {{
    color: {p['text_faint']};
    font-size: 11px;
    padding: 0 4px 8px 4px;
}}

QPushButton#NavButton {{
    text-align: left;
    padding: 10px 14px;
    border-radius: 8px;
    border: none;
    background-color: transparent;
    color: {p['text_muted']};
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background-color: {p['surface_hover']};
    color: {p['text']};
}}
QPushButton#NavButton:checked {{
    background-color: {p['accent_soft']};
    color: {p['accent_hover']};
    font-weight: 600;
}}

/* ---------- Cards ---------- */
QFrame#Card {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-radius: 12px;
}}
QLabel#CardTitle {{
    color: {p['text_muted']};
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel#CardValue {{
    color: {p['text']};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#CardHint {{
    color: {p['text_faint']};
    font-size: 11px;
}}
QLabel#SectionTitle {{
    color: {p['text']};
    font-size: 15px;
    font-weight: 600;
    padding-top: 4px;
}}
QLabel#PageSubtitle {{
    color: {p['text_muted']};
    font-size: 12px;
}}

/* ---------- Atalho de proxy ativo (Dashboard) ---------- */
QFrame#QuickProxyBar {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QLabel#QuickProxyLabel {{
    color: {p['text_faint']};
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding-left: 1px;
}}
QComboBox#QuickProxyCombo {{
    min-width: 172px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    padding: 4px 8px;
}}
QComboBox#QuickProxyCombo:focus {{ border: 1px solid {p['accent']}; }}
QFrame#QuickProxyDivider {{
    background-color: {p['border']};
    margin: 4px 2px;
}}
QLabel#QuickProxyIpPrevious {{
    color: {p['text_faint']};
    font-size: 12px;
}}
QLabel#QuickProxyIpArrow {{
    color: {p['text_faint']};
    font-size: 12px;
}}
QLabel#QuickProxyIpCurrent {{
    color: {p['text']};
    font-weight: 600;
    font-size: 12px;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 7px 14px;
    color: {p['text']};
}}
QPushButton:hover {{
    background-color: {p['surface_hover']};
}}
QPushButton:pressed {{
    background-color: {p['border']};
}}
QPushButton:disabled {{
    color: {p['text_faint']};
    background-color: {p['surface']};
}}

QPushButton#PrimaryButton {{
    background-color: {p['accent']};
    border: 1px solid {p['accent']};
    color: #0b1020;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background-color: {p['accent_hover']}; }}
QPushButton#PrimaryButton:pressed {{ background-color: {p['accent_pressed']}; }}

QPushButton#DangerButton {{
    background-color: transparent;
    border: 1px solid {p['danger']};
    color: {p['danger']};
}}
QPushButton#DangerButton:hover {{ background-color: {p['danger_soft']}; }}

QPushButton#IconButton {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 4px;
    font-weight: 600;
}}
QPushButton#IconButton:hover {{
    background-color: {p['surface_hover']};
    border-color: {p['accent']};
    color: {p['accent_hover']};
}}
QPushButton#IconButton::menu-indicator {{
    subcontrol-position: right center;
    subcontrol-origin: padding;
    right: 4px;
}}

QPushButton#EngineToggleOn {{
    background-color: {p['danger']};
    border: 1px solid {p['danger']};
    color: white;
    font-weight: 700;
    padding: 10px 22px;
    border-radius: 10px;
}}
QPushButton#EngineToggleOn:hover {{ background-color: #ff6a5f; }}

QPushButton#EngineToggleOff {{
    background-color: {p['success']};
    border: 1px solid {p['success']};
    color: #06231a;
    font-weight: 700;
    padding: 10px 22px;
    border-radius: 10px;
}}
QPushButton#EngineToggleOff:hover {{ background-color: #3fd995; }}

/* ---------- Inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 10px;
    color: {p['text']};
    selection-background-color: {p['accent']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {p['accent']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    selection-background-color: {p['accent_soft']};
    color: {p['text']};
    outline: none;
}}
QPlainTextEdit#RulesEditor {{
    font-family: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;
    font-size: 13px;
    background-color: {p['surface']};
}}

QCheckBox {{ spacing: 8px; color: {p['text']}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {p['border']};
    background-color: {p['surface_alt']};
}}
QCheckBox::indicator:checked {{
    background-color: {p['accent']};
    border: 1px solid {p['accent']};
}}

/* ---------- Tables ---------- */
QTableView, QTableWidget {{
    background-color: {p['surface']};
    alternate-background-color: {p['surface_alt']};
    gridline-color: {p['border_soft']};
    border: 1px solid {p['border_soft']};
    border-radius: 10px;
    selection-background-color: {p['accent_soft']};
    selection-color: {p['text']};
}}
QHeaderView::section {{
    background-color: {p['surface_alt']};
    color: {p['text_muted']};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {p['border']};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}}
QTableView::item, QTableWidget::item {{ padding: 4px 6px; }}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    border: 1px solid {p['border_soft']};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {p['text_muted']};
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QTabBar::tab:selected {{
    background-color: {p['surface']};
    color: {p['text']};
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {p['text']}; }}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['surface_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------- Menu (tray) ---------- */
QMenu {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 6px;
    color: {p['text']};
}}
QMenu::item:selected {{ background-color: {p['accent_soft']}; }}

QSplitter::handle {{ background-color: {p['border_soft']}; }}
"""
