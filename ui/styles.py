from ui.scale import s, font


def get_global_style() -> str:
    return f"""
/* General Application Background and Font */
QWidget {{
    background-color: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1f2937;
}}

/* Base styles for labels */
QLabel {{
    background-color: transparent;
    border: none;
}}

/* Specific styling for large input fields */
QLineEdit, QComboBox {{
    padding: {s(12)}px;
    font-size: {font(16)}px;
    border: 1px solid #d1d5db;
    border-radius: {s(8)}px;
    background-color: #ffffff;
    color: #1f2937;
}}

QLineEdit:focus, QComboBox:focus {{
    border: 2px solid #3b82f6;
    background-color: #ffffff;
}}

/* ComboBox dropdown styling to fix white-on-white text */
QComboBox QAbstractItemView {{
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    selection-background-color: #eff6ff;
    selection-color: #1d4ed8;
}}
QComboBox::drop-down {{
    border: none;
}}

/* Table Widget (Cart) styling */
QTableWidget {{
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: {s(8)}px;
    gridline-color: #e5e7eb;
    color: #1f2937;
    font-size: {font(15)}px;
    selection-background-color: #eff6ff;
    selection-color: #1f2937;
}}

QTableWidget::item {{
    border-bottom: 1px solid #e5e7eb;
}}

/* Table Header styling */
QHeaderView::section {{
    background-color: #f9fafb;
    color: #4b5563;
    padding: {s(12)}px {s(5)}px;
    border: none;
    border-bottom: 2px solid #d1d5db;
    font-size: {font(14)}px;
    font-weight: bold;
    text-transform: uppercase;
}}

/* Scrollbars */
QScrollBar:vertical {{
    border: none;
    background: #f3f4f6;
    width: {s(10)}px;
    margin: 0px 0px 0px 0px;
}}
QScrollBar::handle:vertical {{
    background: #d1d5db;
    min-height: {s(20)}px;
    border-radius: {s(5)}px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    border: none;
    background: #f3f4f6;
    height: {s(10)}px;
    margin: 0px 0px 0px 0px;
}}
QScrollBar::handle:horizontal {{
    background: #d1d5db;
    min-width: {s(20)}px;
    border-radius: {s(5)}px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* GroupBox styling */
QGroupBox {{
    font-weight: bold;
    font-size: {font(16)}px;
    border: 1px solid #e5e7eb;
    border-radius: {s(8)}px;
    margin-top: {s(15)}px;
    background-color: #ffffff;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {s(15)}px;
    padding: 0 {s(5)}px;
    color: #374151;
}}

/* Custom general buttons */
QPushButton {{
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    color: #374151;
    border-radius: {s(8)}px;
    padding: {s(8)}px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #f9fafb;
}}
QPushButton:pressed {{
    background-color: #e5e7eb;
}}
"""
