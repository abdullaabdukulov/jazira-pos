GLOBAL_STYLE = """
/* General Application Background and Font */
QWidget {
    background-color: #f3f4f6; /* Very light gray background */
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1f2937; /* Dark gray text */
}

/* Base styles for labels */
QLabel {
    background-color: transparent;
    border: none;
}

/* Specific styling for large input fields */
QLineEdit, QComboBox {
    padding: 12px;
    font-size: 16px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    background-color: #ffffff;
    color: #1f2937;
}

QLineEdit:focus, QComboBox:focus {
    border: 2px solid #3b82f6;
    background-color: #ffffff;
}

/* ComboBox dropdown styling to fix white-on-white text */
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    selection-background-color: #eff6ff; /* Light blue on hover */
    selection-color: #1d4ed8; /* Dark blue text on hover */
}
QComboBox::drop-down {
    border: none;
}

/* Table Widget (Cart) styling */
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    gridline-color: #e5e7eb;
    color: #1f2937;
    font-size: 15px;
    selection-background-color: #eff6ff;
    selection-color: #1f2937;
}

QTableWidget::item {
    border-bottom: 1px solid #e5e7eb;
}

/* Table Header styling - CRITICAL FIX FOR INVISIBLE HEADERS */
QHeaderView::section {
    background-color: #f9fafb;
    color: #4b5563; /* Dark gray */
    padding: 12px 5px;
    border: none;
    border-bottom: 2px solid #d1d5db;
    font-size: 14px;
    font-weight: bold;
    text-transform: uppercase;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #f3f4f6;
    width: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #f3f4f6;
    height: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:horizontal {
    background: #d1d5db;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* GroupBox styling */
QGroupBox {
    font-weight: bold;
    font-size: 16px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-top: 15px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 15px;
    padding: 0 5px;
    color: #374151;
}

/* Custom general buttons */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    color: #374151;
    border-radius: 8px;
    padding: 8px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #f9fafb;
}
QPushButton:pressed {
    background-color: #e5e7eb;
}
"""
