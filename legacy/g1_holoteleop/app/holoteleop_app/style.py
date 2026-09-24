APP_STYLE = """
QMainWindow {
    background: #f5f7fb;
}
QLabel#Title {
    color: #172033;
    font-size: 22px;
    font-weight: 800;
}
QLabel#Subtitle {
    color: #667085;
    font-size: 12px;
}
QLabel#RunHint {
    color: #475467;
    font-size: 13px;
    padding: 6px 2px;
}
QLabel#SectionHint {
    color: #667085;
    font-size: 12px;
}
QLabel#GuideText {
    color: #344054;
    line-height: 150%;
}
QTabWidget::pane {
    border: 1px solid #d9dee8;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    min-width: 92px;
    min-height: 24px;
    padding: 3px 10px;
    border: 1px solid #d9dee8;
    border-bottom: none;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    background: #eef2f8;
    color: #475467;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #172033;
    font-weight: 700;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #d9dee8;
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px;
    font-weight: 700;
    color: #1f2937;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLineEdit, QSpinBox, QComboBox {
    min-height: 26px;
    border: 1px solid #cfd6e4;
    border-radius: 6px;
    padding: 3px 8px;
    background: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #4f7cff;
}
QPushButton {
    min-height: 28px;
    border: 1px solid #c7cedb;
    border-radius: 6px;
    padding: 4px 12px;
    background: #ffffff;
    color: #1f2937;
}
QPushButton:hover {
    background: #f2f5fb;
}
QPushButton:pressed {
    background: #e7ecf6;
}
QPushButton:disabled {
    color: #98a2b3;
    background: #f1f3f7;
}
QPushButton[primary="true"] {
    background: #2f6bff;
    color: #ffffff;
    border: 1px solid #2f6bff;
    font-weight: 700;
}
QPushButton[primary="true"]:hover {
    background: #235be0;
}
QPushButton[danger="true"] {
    color: #b42318;
    border: 1px solid #f0b8b3;
    background: #fff7f6;
}
QPushButton[danger="true"]:hover {
    background: #ffe9e7;
}
QCheckBox {
    color: #344054;
    spacing: 7px;
}
QPlainTextEdit {
    background: #111827;
    color: #d1fae5;
    border: 1px solid #1f2937;
    border-radius: 8px;
    padding: 8px;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 12px;
}
"""
