"""Shared full-width disclosure headers for optional control categories."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QToolButton


def disclosure_header(text, body, parent=None):
    header = QToolButton(parent)
    header.setProperty("disclosure", True)
    header.setText(text)
    header.setCheckable(True)
    header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    header.setArrowType(Qt.ArrowType.RightArrow)
    header.toggled.connect(body.setVisible)
    header.toggled.connect(lambda opened: header.setArrowType(
        Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
    body.hide()
    return header
