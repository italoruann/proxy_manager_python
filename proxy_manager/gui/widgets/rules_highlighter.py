from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..theme import PALETTE

_COMMENT_RE = re.compile(r"#.*$")
_APPS_RE = re.compile(r"^\s*apps\s*:", re.IGNORECASE)
_ACTION_RE = re.compile(r"\+\w+(:\S+)?")
_DISABLED_RE = re.compile(r"^\s*!")


class RulesHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor(PALETTE["text_faint"]))
        self._comment_fmt.setFontItalic(True)

        self._apps_fmt = QTextCharFormat()
        self._apps_fmt.setForeground(QColor(PALETTE["accent_hover"]))
        self._apps_fmt.setFontWeight(QFont.Weight.DemiBold)

        self._action_fmt = QTextCharFormat()
        self._action_fmt.setForeground(QColor(PALETTE["warning"]))

        self._disabled_fmt = QTextCharFormat()
        self._disabled_fmt.setForeground(QColor(PALETTE["danger"]))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        if _APPS_RE.match(text):
            self.setFormat(0, len(text), self._apps_fmt)
            return

        for match in _ACTION_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._action_fmt)

        disabled_match = _DISABLED_RE.match(text)
        if disabled_match:
            self.setFormat(disabled_match.start(), disabled_match.end() - disabled_match.start(), self._disabled_fmt)

        comment_match = _COMMENT_RE.search(text)
        if comment_match:
            self.setFormat(comment_match.start(), len(text) - comment_match.start(), self._comment_fmt)
