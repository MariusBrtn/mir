import json
import re
from typing import cast
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, 
    QLabel, QPushButton, QTextEdit, QFrame
)
from PySide6.QtGui import (
    QPainter, QTextFormat, QColor, QFont, QSyntaxHighlighter, 
    QTextCharFormat, QTextCursor
)
from PySide6.QtCore import QSize, Qt, QRect, QTimer, Signal

# Theme definitions for the JSON Code Editor Widget
THEMES = {
    "dark": {
        # QPlainTextEdit styles
        "editor_bg": "#1e1e1e",
        "editor_fg": "#d4d4d4",
        "editor_selection_bg": "#264f78",
        "editor_selection_fg": "#ffffff",
        
        # Line numbers
        "line_num_bg": "#1e1e1e",
        "line_num_fg": "#858585",
        "line_num_current_fg": "#ffffff",
        "line_num_error_fg": "#f44336",
        
        # Line highlights
        "current_line_bg": "#282828",
        "error_line_bg": "#421f1f",
        
        # QSyntaxHighlighter formats
        "syntax_key": "#9CDCFE",
        "syntax_key_bold": True,
        "syntax_string": "#CE9178",
        "syntax_number": "#B5CEA8",
        "syntax_keyword": "#569CD6",
        "syntax_punctuation": "#D4D4D4",
        "syntax_comment": "#6A9955",
        
        # Outer Widget & Containers
        "widget_border": "#3c3c3c",
        "header_bg": "#2d2d2d",
        "header_title": "#a0a0a0",
        
        # Buttons
        "btn_bg": "#3c3c3c",
        "btn_fg": "#cccccc",
        "btn_hover_bg": "#4c4c4c",
        "btn_hover_fg": "#ffffff",
        "btn_pressed_bg": "#5c5c5c",
        
        # Status Bar
        "status_bg": "#252526",
        "status_fg_normal": "#969696",
        "status_fg_neutral": "#a0a0a0",
        "status_fg_valid": "#89ca78",
        "status_fg_error": "#f48fb1"
    },
    "light": {
        # QPlainTextEdit styles
        "editor_bg": "#ffffff",
        "editor_fg": "#000000",
        "editor_selection_bg": "#add6ff",
        "editor_selection_fg": "#000000",
        
        # Line numbers
        "line_num_bg": "#f3f3f3",
        "line_num_fg": "#a0a0a0",
        "line_num_current_fg": "#000000",
        "line_num_error_fg": "#d32f2f",
        
        # Line highlights
        "current_line_bg": "#f2f2f2",
        "error_line_bg": "#eed0d0",
        
        # QSyntaxHighlighter formats
        "syntax_key": "#0451a5",
        "syntax_key_bold": True,
        "syntax_string": "#a31515",
        "syntax_number": "#098658",
        "syntax_keyword": "#0000ff",
        "syntax_punctuation": "#3b3b3b",
        "syntax_comment": "#008000",
        
        # Outer Widget & Containers
        "widget_border": "#cccccc",
        "header_bg": "#f3f3f3",
        "header_title": "#606060",
        
        # Buttons
        "btn_bg": "#e1e1e1",
        "btn_fg": "#333333",
        "btn_hover_bg": "#d0d0d0",
        "btn_hover_fg": "#000000",
        "btn_pressed_bg": "#b0b0b0",
        
        # Status Bar
        "status_bg": "#f3f3f3",
        "status_fg_normal": "#606060",
        "status_fg_neutral": "#7a7a7a",
        "status_fg_valid": "#2e7d32",
        "status_fg_error": "#d32f2f"
    }
}

class JsonHighlighter(QSyntaxHighlighter):
    """
    Syntax highlighter for JSON content using a lexical scanner approach
    supporting dynamic theme application.
    """
    def __init__(self, document, theme_name="dark"):
        super().__init__(document)
        self.formats = {
            "key": QTextCharFormat(),
            "string": QTextCharFormat(),
            "number": QTextCharFormat(),
            "keyword": QTextCharFormat(),
            "punctuation": QTextCharFormat(),
            "comment": QTextCharFormat()
        }
        self.applyTheme(THEMES[theme_name])

        # Setup token regexes for the scanner
        self.keyword_regex = re.compile(r'^(?:true|false|null)\b')
        self.number_regex = re.compile(r'^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\b')

    def applyTheme(self, theme):
        """Applies theme color variables to syntax highlight formats."""
        self.formats["key"].setForeground(QColor(theme["syntax_key"]))
        self.formats["key"].setFontWeight(QFont.Weight.Bold if theme.get("syntax_key_bold", True) else QFont.Weight.Normal)
        self.formats["string"].setForeground(QColor(theme["syntax_string"]))
        self.formats["number"].setForeground(QColor(theme["syntax_number"]))
        self.formats["keyword"].setForeground(QColor(theme["syntax_keyword"]))
        self.formats["punctuation"].setForeground(QColor(theme["syntax_punctuation"]))
        self.formats["comment"].setFontItalic(True)

    def highlightBlock(self, text):
        i = 0
        n = len(text)
        
        while i < n:
            # Skip whitespace
            if text[i].isspace():
                i += 1
                continue
                
            # Single-line comment: // ...
            if i + 1 < n and text[i] == '/' and text[i+1] == '/':
                self.setFormat(i, n - i, self.formats["comment"])
                break
                
            # String literal
            if text[i] == '"':
                start = i
                i += 1
                # Find closing double quote, taking escape chars into account
                while i < n:
                    if text[i] == '\\' and i + 1 < n:
                        i += 2  # Skip escape and escaped char
                    elif text[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
                
                length = i - start
                
                # Check if it's a key or value by looking ahead for a ':'
                is_key = False
                j = i
                while j < n and text[j].isspace():
                    j += 1
                if j < n and text[j] == ':':
                    is_key = True
                    
                if is_key:
                    self.setFormat(start, length, self.formats["key"])
                else:
                    self.setFormat(start, length, self.formats["string"])
                continue
                
            # Brackets, colons, commas
            char = text[i]
            if char in '{}[]:,':
                self.setFormat(i, 1, self.formats["punctuation"])
                i += 1
                continue
                
            # Match keywords (true, false, null)
            keyword_match = self.keyword_regex.match(text, i)
            if keyword_match:
                length = len(keyword_match.group(0))
                self.setFormat(i, length, self.formats["keyword"])
                i += length
                continue
                
            # Match numbers
            number_match = self.number_regex.match(text, i)
            if number_match:
                length = len(number_match.group(0))
                self.setFormat(i, length, self.formats["number"])
                i += length
                continue
                
            # Fallback for unknown character
            i += 1


class LineNumberArea(QWidget):
    """
    Sub-widget that draws the line numbers for the QPlainTextEdit.
    """
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.code_editor.lineNumberAreaPaintEvent(event)

INDENT = 2
class CodeEditor(QPlainTextEdit):
    """
    Custom QPlainTextEdit supporting line numbering, current line highlighting,
    and automatic indent/bracket closing key handling.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.error_lineno = None
        self.current_theme = THEMES["dark"]

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        # Modern monospaced font settings
        font = QFont()
        font.setFamily("IBM Plex Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(10)
        self.setFont(font)

        # Tab key spacing (4 spaces)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * INDENT)

        # Instantiate Syntax Highlighter on own document
        self.highlighter = JsonHighlighter(self.document(), "dark")

        # Apply default theme
        self.setTheme("dark")

    def setTheme(self, theme_name):
        """Sets the theme of the editor to either 'dark' or 'light'."""
        if theme_name not in THEMES:
            return
        
        self.current_theme = THEMES[theme_name]

        # Apply QSS to the QPlainTextEdit
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {self.current_theme['editor_bg']};
                color: {self.current_theme['editor_fg']};
                selection-background-color: {self.current_theme['editor_selection_bg']};
                selection-color: {self.current_theme['editor_selection_fg']};
            }}
        """)

        # Update highlighter colors
        if hasattr(self, 'highlighter'):
            self.highlighter.applyTheme(self.current_theme)
            self.highlighter.rehighlight()

        # Trigger re-layout of viewport margins and line highlights
        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()
        self.line_number_area.update()

    def lineNumberAreaWidth(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        space = 15 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        # Background of line numbers
        painter.fillRect(event.rect(), QColor(self.current_theme["line_num_bg"]))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                
                # Highlight error line number in red, current line in bright white/gray, others dim
                current_cursor = self.textCursor()
                is_current_line = (block_number == current_cursor.blockNumber())
                is_error_line = (self.error_lineno is not None and block_number + 1 == self.error_lineno)

                if is_error_line:
                    painter.setPen(QColor(self.current_theme["line_num_error_fg"]))
                elif is_current_line:
                    painter.setPen(QColor(self.current_theme["line_num_current_fg"]))
                else:
                    painter.setPen(QColor(self.current_theme["line_num_fg"]))

                painter.drawText(
                    0, top, 
                    self.line_number_area.width() - 8, 
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 
                    number
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def setErrorLine(self, lineno):
        self.error_lineno = lineno
        self.updateLineNumberArea(self.rect(), 0)
        self.highlightCurrentLine()
        
    def clearErrorLine(self):
        self.error_lineno = None
        self.updateLineNumberArea(self.rect(), 0)
        self.highlightCurrentLine()

    def highlightCurrentLine(self):
        extra_selections: list[QTextEdit.ExtraSelection] = []

        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor(self.current_theme["current_line_bg"])
            fmt = cast(QTextCharFormat, selection.format)  # pyrefly: PySide6 stub types this as Ellipsis
            fmt.setBackground(line_color)
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            cur = self.textCursor()
            cur.clearSelection()
            selection.cursor = cur  # type: ignore[assignment]
            extra_selections.append(selection)

        if self.error_lineno is not None:
            selection = QTextEdit.ExtraSelection()
            # Soft red background for the line containing invalid JSON
            error_color = QColor(self.current_theme["error_line_bg"])
            fmt = cast(QTextCharFormat, selection.format)  # pyrefly: PySide6 stub types this as Ellipsis
            fmt.setBackground(error_color)
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            
            doc = self.document()
            block = doc.findBlockByNumber(self.error_lineno - 1)
            if block.isValid():
                cur = self.textCursor()
                cur.setPosition(block.position())
                selection.cursor = cur  # type: ignore[assignment]
                extra_selections.append(selection)

        self.setExtraSelections(extra_selections)

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        cursor = self.textCursor()

        # 1. Handle bracket / quote auto-closing
        pairs = {
            '{': '}',
            '[': ']',
            '"': '"',
            '(': ')'
        }

        if text in pairs:
            closing_char = pairs[text]
            # If quotes, and we are already right before a quote, just step over
            if text == '"' and not cursor.atEnd():
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                if cursor.selectedText() == '"':
                    cursor.clearSelection()
                    self.setTextCursor(cursor)
                    event.accept()
                    return
                cursor.setPosition(cursor.position() - 1) # reset cursor
            
            cursor.insertText(text + closing_char)
            cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
            self.setTextCursor(cursor)
            event.accept()
            return

        # 2. Skip over closing bracket if typed
        if text in ('}', ']', ')'):
            if not cursor.atEnd():
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                if cursor.selectedText() == text:
                    cursor.clearSelection()
                    self.setTextCursor(cursor)
                    event.accept()
                    return
                cursor.setPosition(cursor.position() - 1)

        # 3. Backspace handling for matching pairs (deletes both)
        if key == Qt.Key.Key_Backspace:
            if not cursor.atStart() and not cursor.atEnd():
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
                char_before = cursor.selectedText()
                cursor.setPosition(cursor.position() + 1)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                char_after = cursor.selectedText()
                cursor.setPosition(cursor.position() - 1)
                
                if (char_before == '{' and char_after == '}') or \
                   (char_before == '[' and char_after == ']') or \
                   (char_before == '"' and char_after == '"') or \
                   (char_before == '(' and char_after == ')'):
                    cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
                    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 2)
                    cursor.removeSelectedText()
                    event.accept()
                    return

        # 4. Handle Enter key for smart auto-indentation
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current_line = cursor.block().text()
            # Keep previous line indentation
            leading_spaces = len(current_line) - len(current_line.lstrip(' '))
            indentation = " " * leading_spaces
            
            stripped = current_line.strip()
            extra_indent = ""
            if stripped.endswith('{') or stripped.endswith('['):
                extra_indent = "    "

            # Check if cursor is directly between open & close braces
            between_brackets = False
            if not cursor.atStart() and not cursor.atEnd():
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
                char_before = cursor.selectedText()
                cursor.setPosition(cursor.position() + 1)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                char_after = cursor.selectedText()
                cursor.setPosition(cursor.position() - 1)
                if (char_before == '{' and char_after == '}') or (char_before == '[' and char_after == ']'):
                    between_brackets = True

            if between_brackets:
                # Format:
                # {
                #     <cursor>
                # }
                cursor.insertText("\n" + indentation + extra_indent)
                pos = cursor.position()
                cursor.insertText("\n" + indentation)
                cursor.setPosition(pos)
                self.setTextCursor(cursor)
                event.accept()
                return
            else:
                cursor.insertText("\n" + indentation + extra_indent)
                self.setTextCursor(cursor)
                event.accept()
                return

        # 5. Handle Tab key by inserting 4 spaces
        if key == Qt.Key.Key_Tab:
            cursor.insertText(" " * INDENT)
            event.accept()
            return

        super().keyPressEvent(event)


class CodeEditorWidget(QWidget):
    """
    Reusable Widget representing a fully featured JSON code editor:
    - CodeEditor with syntax highlighting and line numbers
    - Visual toolbar (Format, Minify, Clear)
    - Status bar with debounced validation and cursor indicators
    """
    # PySide6 Signals
    textChanged = Signal()
    validationChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_valid = True
        self.current_theme_name = "dark"

        # Main Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Header Bar
        self.header = QFrame(self)
        self.header.setObjectName("headerBar")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)

        self.btn_format = QPushButton("Format", self.header)
        self.btn_format.clicked.connect(self.format_json)
        header_layout.addWidget(self.btn_format,0,  Qt.AlignmentFlag.AlignLeft)

        
        self.status_label = QLabel("✓ Valid JSON")
        self.status_label.setObjectName("statusLabel")
        header_layout.addWidget(self.status_label, 1, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.header)

        # 2. Main Editor
        self.editor = CodeEditor(self)
        layout.addWidget(self.editor)

        # Reference the editor's syntax highlighter
        self.highlighter = self.editor.highlighter

        # Apply initial theme
        self.setTheme("dark")

        # Debounced validation setup (300ms)
        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(300)
        self.validation_timer.timeout.connect(self.validate_json)

        # Signals connections
        self.editor.textChanged.connect(self.on_text_changed)

    def setTheme(self, theme_name):
        """Applies stylesheet and color variables of the selected theme to the widget components."""
        if theme_name not in THEMES:
            return
        
        self.current_theme_name = theme_name
        theme = THEMES[theme_name]

        # Dynamic QSS styling using theme variables
        self.setStyleSheet(f"""
            CodeEditorWidget {{
                background-color: {theme['editor_bg']};
                border: 1px solid {theme['widget_border']};
                border-radius: 6px;
            }}
            #headerBar {{
                background-color: {theme['header_bg']};
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                border-bottom: 1px solid {theme['widget_border']};
                min-height: 32px;
            }}
            #headerTitle {{
                color: {theme['header_title']};
                font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                margin-left: 10px;
            }}
            #headerBar QPushButton {{
                background-color: {theme['btn_bg']};
                color: {theme['btn_fg']};
                border: 1px solid {theme['widget_border']};
                border-radius: 3px;
                padding: 4px 10px;
                font-size: 11px;
                font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
                font-weight: 500;
            }}
            #headerBar QPushButton:hover {{
                background-color: {theme['btn_hover_bg']};
                color: {theme['btn_hover_fg']};
            }}
            #headerBar QPushButton:pressed {{
                background-color: {theme['btn_pressed_bg']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {theme['editor_bg']};
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {theme['btn_bg']};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {theme['btn_hover_bg']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: {theme['editor_bg']};
                height: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {theme['btn_bg']};
                min-width: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {theme['btn_hover_bg']};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            #statusBar {{
                background-color: {theme['status_bg']};
                border-bottom-left-radius: 5px;
                border-bottom-right-radius: 5px;
                border-top: 1px solid {theme['widget_border']};
                min-height: 24px;
            }}
            #cursorLabel {{
                color: {theme['status_fg_normal']};
                font-size: 11px;
                font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
                margin-right: 10px;
            }}
        """)

        # Update QPlainTextEdit component (which handles its own highlighter update)
        self.editor.setTheme(theme_name)

        # Update validation label style colors
        self.validate_json()

    # API methods for reusability
    def setPlainText(self, text):
        """Sets text content and immediately validates it."""
        self.editor.setPlainText(text)
        self.validate_json()

    def toPlainText(self):
        """Returns raw string content of the editor."""
        return self.editor.toPlainText()

    def jsonValue(self):
        """Returns the parsed JSON object, or None if the JSON is invalid."""
        try:
            return json.loads(self.toPlainText())
        except json.JSONDecodeError:
            return None

    def setJsonValue(self, val):
        """Sets a Python dict/list as pretty-printed JSON in the editor."""
        formatted = json.dumps(val, indent=INDENT, ensure_ascii=False)
        self.setPlainText(formatted)

    def isValidJson(self):
        """Returns True if JSON is currently valid, False otherwise."""
        return self.is_valid

    # Event handlers & internal helpers
    def on_text_changed(self):
        self.textChanged.emit()
        self.validation_timer.start()

    def validate_json(self):
        text = self.toPlainText()
        theme = THEMES[self.current_theme_name]
        
        # Neutral empty state check
        if not text.strip():
            self.is_valid = True
            self.status_label.setText("Empty Document")
            self.status_label.setStyleSheet(f"color: {theme['status_fg_neutral']};")
            self.editor.clearErrorLine()
            self.validationChanged.emit(True)
            return

        try:
            json.loads(text)
            self.is_valid = True
            self.status_label.setText("✓ Valid JSON")
            self.status_label.setStyleSheet(f"color: {theme['status_fg_valid']};")
            self.editor.clearErrorLine()
            self.validationChanged.emit(True)
        except json.JSONDecodeError as e:
            self.is_valid = False
            err_msg = f"✗ Invalid JSON (Ln {e.lineno}, Col {e.colno}): {e.msg}"
            self.status_label.setText(err_msg)
            self.status_label.setStyleSheet(f"color: {theme['status_fg_error']};")
            self.editor.setErrorLine(e.lineno)
            self.validationChanged.emit(False)

    def format_json(self):
        text = self.toPlainText()
        theme = THEMES[self.current_theme_name]
        if not text.strip():
            return
        try:
            obj = json.loads(text)
            formatted = json.dumps(obj, indent=INDENT, ensure_ascii=False)
            self.setPlainText(formatted)
        except json.JSONDecodeError as e:
            self.status_label.setText(f"⚠ Cannot format: Invalid JSON (line {e.lineno})")
            self.status_label.setStyleSheet(f"color: {theme['status_fg_error']};")

    def minify_json(self):
        text = self.toPlainText()
        theme = THEMES[self.current_theme_name]
        if not text.strip():
            return
        try:
            obj = json.loads(text)
            minified = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
            self.setPlainText(minified)
        except json.JSONDecodeError as e:
            self.status_label.setText(f"⚠ Cannot minify: Invalid JSON (line {e.lineno})")
            self.status_label.setStyleSheet(f"color: {theme['status_fg_error']};")

    def clear_text(self):
        self.editor.clear()


class PythonHighlighter(QSyntaxHighlighter):
    """Coloration syntaxique Python simple : mots-clés, chaînes, nombres, commentaires, décorateurs."""
    KEYWORDS = ("False None True and as assert async await break class continue def del elif else except finally "
                "for from global if import in is lambda nonlocal not or pass raise return try while with yield self").split()

    def __init__(self, document, theme_name="dark"):
        super().__init__(document)
        self.formats = {name: QTextCharFormat() for name in ("keyword", "string", "number", "comment", "definition")}
        self.rules = [
            (re.compile(r"\b(?:" + "|".join(self.KEYWORDS) + r")\b"), "keyword"),
            (re.compile(r"\b(?:def|class)\s+(\w+)"), "definition"),
            (re.compile(r"\b\d+(?:\.\d+)?\b"), "number"),
            (re.compile(r"@\w+"), "definition"),
            (re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'|\"[^\"\\]*(?:\\.[^\"\\]*)*\""), "string"),
            (re.compile(r"#[^\n]*"), "comment"),
        ]
        self.triple = re.compile(r'"""|\'\'\'')
        self.applyTheme(THEMES[theme_name])

    def applyTheme(self, theme):
        self.formats["keyword"].setForeground(QColor(theme["syntax_keyword"]))
        self.formats["string"].setForeground(QColor(theme["syntax_string"]))
        self.formats["number"].setForeground(QColor(theme["syntax_number"]))
        self.formats["comment"].setForeground(QColor(theme["syntax_comment"]))
        self.formats["comment"].setFontItalic(True)
        self.formats["definition"].setForeground(QColor(theme["syntax_key"]))
        self.formats["definition"].setFontWeight(QFont.Weight.Bold)

    def highlightBlock(self, text):
        for regex, name in self.rules:
            for match in regex.finditer(text):
                start, end = (match.start(1), match.end(1)) if match.groups() else (match.start(), match.end())
                self.setFormat(start, end - start, self.formats[name])
        # chaînes sur plusieurs lignes (docstrings) : état 1 = à l'intérieur
        start = 0
        if self.previousBlockState() == 1:
            match = self.triple.search(text)
            end = match.end() if match else len(text)
            self.setFormat(0, end, self.formats["string"])
            if not match:
                self.setCurrentBlockState(1)
                return
            start = end
        self.setCurrentBlockState(0)
        while True:
            opening = self.triple.search(text, start)
            if not opening:
                return
            closing = self.triple.search(text, opening.end())
            end = closing.end() if closing else len(text)
            self.setFormat(opening.start(), end - opening.start(), self.formats["string"])
            if not closing:
                self.setCurrentBlockState(1)
                return
            start = end


class PythonCodeEditor(CodeEditor):
    """Éditeur de code Python : coloration Python, tabulation = 4 espaces, indentation après « : »."""
    PY_INDENT = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * self.PY_INDENT)
        self.highlighter.setDocument(None)
        self.highlighter = PythonHighlighter(self.document(), "dark")
        self.highlighter.applyTheme(self.current_theme)

    def keyPressEvent(self, event):
        cursor = self.textCursor()
        if event.key() == Qt.Key.Key_Tab:
            cursor.insertText(" " * self.PY_INDENT)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            line = cursor.block().text()[: cursor.positionInBlock()]
            indentation = " " * (len(line) - len(line.lstrip(" ")))
            if line.rstrip().endswith(":"):
                indentation += " " * self.PY_INDENT
            cursor.insertText("\n" + indentation)
            self.ensureCursorVisible()
            event.accept()
            return
        super().keyPressEvent(event)
