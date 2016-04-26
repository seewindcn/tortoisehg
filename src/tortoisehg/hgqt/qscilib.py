# qscilib.py - Utility codes for QsciScintilla
#
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import re, os, weakref

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import *

# indicator for highlighting preedit text of input method
_IM_PREEDIT_INDIC_ID = QsciScintilla.INDIC_MAX
# indicator for keyword highlighting
_HIGHLIGHT_INDIC_ID = _IM_PREEDIT_INDIC_ID - 1

class _SciImSupport(object):
    """Patch for QsciScintilla to implement improved input method support

    See http://doc.trolltech.com/4.7/qinputmethodevent.html
    """

    def __init__(self, sci):
        self._sci = weakref.proxy(sci)
        self._preeditpos = (0, 0)  # (line, index) where preedit text starts
        self._preeditlen = 0
        self._preeditcursorpos = 0  # relative pos where preedit cursor exists
        self._undoactionbegun = False
        sci.SendScintilla(QsciScintilla.SCI_INDICSETSTYLE,
                          _IM_PREEDIT_INDIC_ID, QsciScintilla.INDIC_PLAIN)

    def removepreedit(self):
        """Remove the previous preedit text

        original pos: preedit cursor
        final pos: target cursor
        """
        l, i = self._sci.getCursorPosition()
        i -= self._preeditcursorpos
        self._preeditcursorpos = 0
        try:
            self._sci.setSelection(
                self._preeditpos[0], self._preeditpos[1],
                self._preeditpos[0], self._preeditpos[1] + self._preeditlen)
            self._sci.removeSelectedText()
        finally:
            self._sci.setCursorPosition(l, i)

    def commitstr(self, start, repllen, commitstr):
        """Remove the repl string followed by insertion of the commit string

        original pos: target cursor
        final pos: end of committed text (= start of preedit text)
        """
        l, i = self._sci.getCursorPosition()
        i += start
        self._sci.setSelection(l, i, l, i + repllen)
        self._sci.removeSelectedText()
        self._sci.insert(commitstr)
        self._sci.setCursorPosition(l, i + len(commitstr))
        if commitstr:
            self.endundo()

    def insertpreedit(self, text):
        """Insert preedit text

        original pos: start of preedit text
        final pos: start of preedit text (unchanged)
        """
        if text and not self._preeditlen:
            self.beginundo()
        l, i = self._sci.getCursorPosition()
        self._sci.insert(text)
        self._updatepreeditpos(l, i, len(text))
        if not self._preeditlen:
            self.endundo()

    def movepreeditcursor(self, pos):
        """Move the cursor to the relative pos inside preedit text"""
        self._preeditcursorpos = min(pos, self._preeditlen)
        l, i = self._preeditpos
        self._sci.setCursorPosition(l, i + self._preeditcursorpos)

    def beginundo(self):
        if self._undoactionbegun:
            return
        self._sci.beginUndoAction()
        self._undoactionbegun = True

    def endundo(self):
        if not self._undoactionbegun:
            return
        self._sci.endUndoAction()
        self._undoactionbegun = False

    def _updatepreeditpos(self, l, i, len):
        """Update the indicator and internal state for preedit text"""
        self._sci.SendScintilla(QsciScintilla.SCI_SETINDICATORCURRENT,
                                _IM_PREEDIT_INDIC_ID)
        self._preeditpos = (l, i)
        self._preeditlen = len
        if len <= 0:  # have problem on sci
            return
        p = self._sci.positionFromLineIndex(*self._preeditpos)
        q = self._sci.positionFromLineIndex(self._preeditpos[0],
                                            self._preeditpos[1] + len)
        self._sci.SendScintilla(QsciScintilla.SCI_INDICATORFILLRANGE,
                                p, q - p)  # q - p != len


class ScintillaCompat(QsciScintilla):
    """Scintilla widget with compatibility patches"""

    # QScintilla 2.8.4 still can't handle input method events properly.
    # For example, it fails to delete the last preedit text by ^H, and
    # editing position goes wrong. So we sticks to our version.
    if True:
        def __init__(self, parent=None):
            super(ScintillaCompat, self).__init__(parent)
            self._imsupport = _SciImSupport(self)

        def inputMethodQuery(self, query):
            if query == Qt.ImMicroFocus:
                # a rectangle (in viewport coords) including the cursor
                l, i = self.getCursorPosition()
                p = self.positionFromLineIndex(l, i)
                x = self.SendScintilla(QsciScintilla.SCI_POINTXFROMPOSITION,
                                       0, p)
                y = self.SendScintilla(QsciScintilla.SCI_POINTYFROMPOSITION,
                                       0, p)
                w = self.SendScintilla(QsciScintilla.SCI_GETCARETWIDTH)
                return QRect(x, y, w, self.textHeight(l))
            return super(ScintillaCompat, self).inputMethodQuery(query)

        def inputMethodEvent(self, event):
            if self.isReadOnly():
                return

            self.removeSelectedText()
            self._imsupport.removepreedit()
            self._imsupport.commitstr(event.replacementStart(),
                                      event.replacementLength(),
                                      event.commitString())
            self._imsupport.insertpreedit(event.preeditString())
            for a in event.attributes():
                if a.type == QInputMethodEvent.Cursor:
                    self._imsupport.movepreeditcursor(a.start)
                # TextFormat is not supported

            event.accept()

    # QScintilla 2.5 can translate Backtab to Shift+SCK_TAB (issue #82)
    if QSCINTILLA_VERSION < 0x20500:
        def keyPressEvent(self, event):
            if event.key() == Qt.Key_Backtab:
                event = QKeyEvent(event.type(), Qt.Key_Tab, Qt.ShiftModifier)
            super(ScintillaCompat, self).keyPressEvent(event)

    if not hasattr(QsciScintilla, 'createStandardContextMenu'):
        def createStandardContextMenu(self):
            """Create standard context menu; ownership is transferred to
            caller"""
            menu = QMenu(self)
            if not self.isReadOnly():
                a = menu.addAction(_('&Undo'), self.undo)
                a.setShortcuts(QKeySequence.Undo)
                a.setEnabled(self.isUndoAvailable())
                a = menu.addAction(_('&Redo'), self.redo)
                a.setShortcuts(QKeySequence.Redo)
                a.setEnabled(self.isRedoAvailable())
                menu.addSeparator()
                a = menu.addAction(_('Cu&t'), self.cut)
                a.setShortcuts(QKeySequence.Cut)
                a.setEnabled(self.hasSelectedText())
            a = menu.addAction(_('&Copy'), self.copy)
            a.setShortcuts(QKeySequence.Copy)
            a.setEnabled(self.hasSelectedText())
            if not self.isReadOnly():
                a = menu.addAction(_('&Paste'), self.paste)
                a.setShortcuts(QKeySequence.Paste)
                a = menu.addAction(_('&Delete'), self.removeSelectedText)
                a.setShortcuts(QKeySequence.Delete)
                a.setEnabled(self.hasSelectedText())
            menu.addSeparator()
            a = menu.addAction(_('Select &All'), self.selectAll)
            a.setShortcuts(QKeySequence.SelectAll)
            return menu

    # compability mode with QScintilla from Ubuntu 10.04
    if not hasattr(QsciScintilla, 'HiddenIndicator'):
        HiddenIndicator = QsciScintilla.INDIC_HIDDEN
    if not hasattr(QsciScintilla, 'PlainIndicator'):
        PlainIndicator = QsciScintilla.INDIC_PLAIN
    if not hasattr(QsciScintilla, 'StrikeIndicator'):
        StrikeIndicator = QsciScintilla.INDIC_STRIKE

    if not hasattr(QsciScintilla, 'indicatorDefine'):
        def indicatorDefine(self, style, indicatorNumber=-1):
            # compatibility layer allows only one indicator to be defined
            if indicatorNumber == -1:
                indicatorNumber = 1
            self.SendScintilla(self.SCI_INDICSETSTYLE, indicatorNumber, style)
            return indicatorNumber

    if not hasattr(QsciScintilla, 'setIndicatorDrawUnder'):
        def setIndicatorDrawUnder(self, under, indicatorNumber):
            self.SendScintilla(self.SCI_INDICSETUNDER, indicatorNumber, under)

    if not hasattr(QsciScintilla, 'setIndicatorForegroundColor'):
        def setIndicatorForegroundColor(self, color, indicatorNumber):
            self.SendScintilla(self.SCI_INDICSETFORE, indicatorNumber, color)
            self.SendScintilla(self.SCI_INDICSETALPHA, indicatorNumber,
                               color.alpha())

    if not hasattr(QsciScintilla, 'clearIndicatorRange'):
        def clearIndicatorRange(self, lineFrom, indexFrom, lineTo, indexTo,
                                indicatorNumber):
            start = self.positionFromLineIndex(lineFrom, indexFrom)
            finish = self.positionFromLineIndex(lineTo, indexTo)

            self.SendScintilla(self.SCI_SETINDICATORCURRENT, indicatorNumber)
            self.SendScintilla(self.SCI_INDICATORCLEARRANGE,
                               start, finish - start)

    if not hasattr(QsciScintilla, 'fillIndicatorRange'):
        def fillIndicatorRange(self, lineFrom, indexFrom, lineTo, indexTo,
                               indicatorNumber):
            start = self.positionFromLineIndex(lineFrom, indexFrom)
            finish = self.positionFromLineIndex(lineTo, indexTo)

            self.SendScintilla(self.SCI_SETINDICATORCURRENT, indicatorNumber)
            self.SendScintilla(self.SCI_INDICATORFILLRANGE,
                               start, finish - start)


class Scintilla(ScintillaCompat):
    """Scintilla widget for rich file view or editor"""

    def __init__(self, parent=None):
        super(Scintilla, self).__init__(parent)
        self.autoUseTabs = True
        self.setUtf8(True)
        self.setWrapVisualFlags(QsciScintilla.WrapFlagByBorder)
        self.textChanged.connect(self._resetfindcond)
        self._resetfindcond()
        self.highlightLines = set()
        self._setupHighlightIndicator()
        self._setMultipleSelectionOptions()
        unbindConflictedKeys(self)

    def _setMultipleSelectionOptions(self):
        if hasattr(QsciScintilla, 'SCI_SETMULTIPLESELECTION'):
            self.SendScintilla(QsciScintilla.SCI_SETMULTIPLESELECTION, True)
            self.SendScintilla(QsciScintilla.SCI_SETADDITIONALSELECTIONTYPING,
                               True)
            self.SendScintilla(QsciScintilla.SCI_SETMULTIPASTE,
                               QsciScintilla.SC_MULTIPASTE_EACH)
            self.SendScintilla(QsciScintilla.SCI_SETVIRTUALSPACEOPTIONS,
                               QsciScintilla.SCVS_RECTANGULARSELECTION)

    def contextMenuEvent(self, event):
        menu = self.createEditorContextMenu()
        menu.exec_(event.globalPos())
        menu.setParent(None)

    def createEditorContextMenu(self):
        """Create context menu with editor options; ownership is transferred
        to caller"""
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        editoptsmenu = menu.addMenu(_('&Editor Options'))
        self._buildEditorOptionsMenu(editoptsmenu)
        return menu

    def _buildEditorOptionsMenu(self, menu):
        qsci = QsciScintilla

        wrapmenu = menu.addMenu(_('&Wrap'))
        wrapmenu.triggered.connect(self._setWrapModeByMenu)
        for name, mode in ((_('&None', 'wrap mode'), qsci.WrapNone),
                           (_('&Word'), qsci.WrapWord),
                           (_('&Character'), qsci.WrapCharacter)):
            a = wrapmenu.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.wrapMode() == mode)
            a.setData(mode)

        menu.addSeparator()
        wsmenu = menu.addMenu(_('White&space'))
        wsmenu.triggered.connect(self._setWhitespaceVisibilityByMenu)
        for name, mode in ((_('&Visible'), qsci.WsVisible),
                           (_('&Invisible'), qsci.WsInvisible),
                           (_('&AfterIndent'), qsci.WsVisibleAfterIndent)):
            a = wsmenu.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.whitespaceVisibility() == mode)
            a.setData(mode)

        if not self.isReadOnly():
            tabindentsmenu = menu.addMenu(_('&TAB Inserts'))
            tabindentsmenu.triggered.connect(self._setIndentationsUseTabsByMenu)
            for name, mode in ((_('&Auto'), -1),
                               (_('&TAB'), True),
                               (_('&Spaces'), False)):
                a = tabindentsmenu.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.indentationsUseTabs() == mode
                             or (self.autoUseTabs and mode == -1))
                a.setData(mode)

        menu.addSeparator()
        vsmenu = menu.addMenu(_('EOL &Visibility'))
        vsmenu.triggered.connect(self._setEolVisibilityByMenu)
        for name, mode in ((_('&Visible'), True),
                           (_('&Invisible'), False)):
            a = vsmenu.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.eolVisibility() == mode)
            a.setData(mode)

        if not self.isReadOnly():
            eolmodemenu = menu.addMenu(_('EOL &Mode'))
            eolmodemenu.triggered.connect(self._setEolModeByMenu)
            for name, mode in ((_('&Windows'), qsci.EolWindows),
                               (_('&Unix'), qsci.EolUnix),
                               (_('&Mac'), qsci.EolMac)):
                a = eolmodemenu.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.eolMode() == mode)
                a.setData(mode)

            menu.addSeparator()
            a = menu.addAction(_('&Auto-Complete'))
            a.triggered.connect(self._setAutoCompletionEnabled)
            a.setCheckable(True)
            a.setChecked(self.autoCompletionThreshold() > 0)

    def saveSettings(self, qs, prefix):
        qs.setValue(prefix+'/wrap', self.wrapMode())
        qs.setValue(prefix+'/whitespace', self.whitespaceVisibility())
        qs.setValue(prefix+'/eol', self.eolVisibility())
        if self.autoUseTabs:
            qs.setValue(prefix+'/usetabs', -1)
        else:
            qs.setValue(prefix+'/usetabs', self.indentationsUseTabs())
        qs.setValue(prefix+'/autocomplete', self.autoCompletionThreshold())

    def loadSettings(self, qs, prefix):
        self.setWrapMode(qs.value(prefix+'/wrap').toInt()[0])
        self.setWhitespaceVisibility(qs.value(prefix+'/whitespace').toInt()[0])
        self.setEolVisibility(qs.value(prefix+'/eol').toBool())
        self.setIndentationsUseTabs(qs.value(prefix+'/usetabs').toInt()[0])
        self.setDefaultEolMode()
        self.setAutoCompletionThreshold(
            qs.value(prefix+'/autocomplete', -1).toInt()[0])


    @pyqtSlot(str, bool, bool, bool)
    def find(self, exp, icase=True, wrap=False, forward=True):
        """Find the next/prev occurence; returns True if found

        This method tries to imitate the behavior of QTextEdit.find(),
        unlike combo of QsciScintilla.findFirst() and findNext().
        """
        cond = (exp, True, not icase, False, wrap, forward)
        if cond == self.__findcond:
            return self.findNext()
        else:
            self.__findcond = cond
            return self.findFirst(*cond)

    @pyqtSlot()
    def _resetfindcond(self):
        self.__findcond = ()

    @pyqtSlot(str, bool)
    def highlightText(self, match, icase=False):
        """Highlight text matching to the given regexp pattern [unicode]

        The previous highlight is cleared automatically.
        """
        try:
            flags = 0
            if icase:
                flags |= re.IGNORECASE
            pat = re.compile(unicode(match).encode('utf-8'), flags)
        except re.error:
            return  # it could be partial pattern while user typing

        self.clearHighlightText()
        self.SendScintilla(self.SCI_SETINDICATORCURRENT, _HIGHLIGHT_INDIC_ID)

        if len(match) == 0:
            return

        # NOTE: pat and target text are *not* unicode because scintilla
        # requires positions in byte. For accuracy, it should do pattern
        # match in unicode, then calculating byte length of substring::
        #
        #     text = unicode(self.text())
        #     for m in pat.finditer(text):
        #         p = len(text[:m.start()].encode('utf-8'))
        #         self.SendScintilla(self.SCI_INDICATORFILLRANGE,
        #             p, len(m.group(0).encode('utf-8')))
        #
        # but it doesn't to avoid possible performance issue.
        for m in pat.finditer(unicode(self.text()).encode('utf-8')):
            self.SendScintilla(self.SCI_INDICATORFILLRANGE,
                               m.start(), m.end() - m.start())
            line = self.lineIndexFromPosition(m.start())[0]
            self.highlightLines.add(line)

    @pyqtSlot()
    def clearHighlightText(self):
        self.SendScintilla(self.SCI_SETINDICATORCURRENT, _HIGHLIGHT_INDIC_ID)
        self.SendScintilla(self.SCI_INDICATORCLEARRANGE, 0, self.length())
        self.highlightLines.clear()

    def _setupHighlightIndicator(self):
        id = _HIGHLIGHT_INDIC_ID
        self.SendScintilla(self.SCI_INDICSETSTYLE, id, self.INDIC_ROUNDBOX)
        self.SendScintilla(self.SCI_INDICSETUNDER, id, True)
        self.SendScintilla(self.SCI_INDICSETFORE, id, 0x00ffff) # 0xbbggrr
        # alpha range is 0 to 255, but old Scintilla rejects value > 100
        self.SendScintilla(self.SCI_INDICSETALPHA, id, 100)

    def showHScrollBar(self, show=True):
        self.SendScintilla(self.SCI_SETHSCROLLBAR, show)

    def setDefaultEolMode(self):
        if self.lines():
            mode = qsciEolModeFromLine(unicode(self.text(0)))
        else:
            mode = qsciEolModeFromOs()
        self.setEolMode(mode)
        return mode

    @pyqtSlot(QAction)
    def _setWrapModeByMenu(self, action):
        mode, _ok = action.data().toInt()
        self.setWrapMode(mode)

    @pyqtSlot(QAction)
    def _setWhitespaceVisibilityByMenu(self, action):
        mode, _ok = action.data().toInt()
        self.setWhitespaceVisibility(mode)

    @pyqtSlot(QAction)
    def _setEolVisibilityByMenu(self, action):
        visible = action.data().toBool()
        self.setEolVisibility(visible)

    @pyqtSlot(QAction)
    def _setEolModeByMenu(self, action):
        mode, _ok = action.data().toInt()
        self.setEolMode(mode)

    @pyqtSlot(QAction)
    def _setIndentationsUseTabsByMenu(self, action):
        mode, _ok = action.data().toInt()
        self.setIndentationsUseTabs(mode)

    def setIndentationsUseTabs(self, tabs):
        self.autoUseTabs = (tabs == -1)
        if self.autoUseTabs and self.lines():
            tabs = findTabIndentsInLines(hglib.fromunicode(self.text()))
        super(Scintilla, self).setIndentationsUseTabs(tabs)

    @pyqtSlot(bool)
    def _setAutoCompletionEnabled(self, enabled):
        self.setAutoCompletionThreshold(enabled and 2 or -1)

    def lineNearPoint(self, point):
        """Return the closest line to the pixel position; similar to lineAt(),
        but returns valid line number even if no character fount at point"""
        # lineAt() uses the strict request, SCI_POSITIONFROMPOINTCLOSE
        chpos = self.SendScintilla(self.SCI_POSITIONFROMPOINT,
                                   # no implicit cast to ulong in old QScintilla
                                   # unsigned long wParam, long lParam
                                   max(point.x(), 0), point.y())
        return self.SendScintilla(self.SCI_LINEFROMPOSITION, chpos)


class SearchToolBar(QToolBar):
    conditionChanged = pyqtSignal(str, bool, bool)
    """Emitted (pattern, icase, wrap) when search condition changed"""

    searchRequested = pyqtSignal(str, bool, bool, bool)
    """Emitted (pattern, icase, wrap, forward) when requested"""

    def __init__(self, parent=None):
        super(SearchToolBar, self).__init__(_('Search'), parent,
                                            objectName='search')
        self.setIconSize(qtlib.smallIconSize())

        a = self.addAction(qtlib.geticon('window-close'), '')
        a.setShortcut(Qt.Key_Escape)
        a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.triggered.connect(self.hide)
        self.addWidget(qtlib.Spacer(2, 2))

        self._le = QLineEdit()
        if hasattr(self._le, 'setPlaceholderText'): # Qt >= 4.7
            self._le.setPlaceholderText(_('### regular expression ###'))
        else:
            self._lbl = QLabel(_('Regexp:'),
                               toolTip=_('Regular expression search pattern'))
            self.addWidget(self._lbl)
            self._lbl.setBuddy(self._le)
        self._le.returnPressed.connect(self._emitSearchRequested)
        self.addWidget(self._le)
        self.addWidget(qtlib.Spacer(4, 4))
        self._chk = QCheckBox(_('Ignore case'))
        self.addWidget(self._chk)
        self._wrapchk = QCheckBox(_('Wrap search'))
        self.addWidget(self._wrapchk)

        self._prevact = self.addAction(qtlib.geticon('go-up'), _('Prev'))
        self._prevact.setShortcuts(QKeySequence.FindPrevious)
        self._nextact = self.addAction(qtlib.geticon('go-down'), _('Next'))
        self._nextact.setShortcuts(QKeySequence.FindNext)
        for a in [self._prevact, self._nextact]:
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            a.triggered.connect(self._emitSearchRequested)
            w = self.widgetForAction(a)
            w.setAutoRaise(False)  # no flat button
            w.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._le.textChanged.connect(self._updateSearchButtons)

        self.setFocusProxy(self._le)
        self.setStyleSheet(qtlib.tbstylesheet)

        self._settings = QSettings()
        self._settings.beginGroup('searchtoolbar')
        self.searchRequested.connect(self._writesettings)
        self._readsettings()

        self._le.textChanged.connect(self._emitConditionChanged)
        self._chk.toggled.connect(self._emitConditionChanged)
        self._wrapchk.toggled.connect(self._emitConditionChanged)

        self._updateSearchButtons()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            return  # handled by returnPressed
        super(SearchToolBar, self).keyPressEvent(event)

    def wheelEvent(self, event):
        if event.delta() > 0:
            self._prevact.trigger()
            return
        if event.delta() < 0:
            self._nextact.trigger()
            return
        super(SearchToolBar, self).wheelEvent(event)

    def setVisible(self, visible=True):
        super(SearchToolBar, self).setVisible(visible)
        if visible:
            self._le.setFocus()
            self._le.selectAll()

    def _readsettings(self):
        self.setCaseInsensitive(self._settings.value('icase', False).toBool())
        self.setWrapAround(self._settings.value('wrap', False).toBool())

    @pyqtSlot()
    def _writesettings(self):
        self._settings.setValue('icase', self.caseInsensitive())
        self._settings.setValue('wrap', self.wrapAround())

    @pyqtSlot()
    def _emitConditionChanged(self):
        self.conditionChanged.emit(self.pattern(), self.caseInsensitive(),
                                   self.wrapAround())

    @qtlib.senderSafeSlot()
    def _emitSearchRequested(self):
        forward = self.sender() is not self._prevact
        self.searchRequested.emit(self.pattern(), self.caseInsensitive(),
                                  self.wrapAround(), forward)

    def editorActions(self):
        """List of actions that should be available in main editor widget"""
        return [self._prevact, self._nextact]

    @pyqtSlot()
    def _updateSearchButtons(self):
        enabled = bool(self._le.text())
        for a in [self._prevact, self._nextact]:
            a.setEnabled(enabled)

    def pattern(self):
        """Returns the current search pattern [unicode]"""
        return self._le.text()

    def setPattern(self, text):
        """Set the search pattern [unicode]"""
        self._le.setText(text)

    def caseInsensitive(self):
        """True if case-insensitive search is requested"""
        return self._chk.isChecked()

    def setCaseInsensitive(self, icase):
        self._chk.setChecked(icase)

    def wrapAround(self):
        """True if wrap search is requested"""
        return self._wrapchk.isChecked()

    def setWrapAround(self, wrap):
        self._wrapchk.setChecked(wrap)

    @pyqtSlot(str)
    def search(self, text):
        """Request search with the given pattern"""
        self.setPattern(text)
        self._emitSearchRequested()

class KeyPressInterceptor(QObject):
    """Grab key press events important for dialogs

    Usage::
        sci = qscilib.Scintilla(self)
        sci.installEventFilter(KeyPressInterceptor(self))
    """

    def __init__(self, parent=None, keys=None, keyseqs=None):
        super(KeyPressInterceptor, self).__init__(parent)
        self._keys = set((Qt.Key_Escape,))
        self._keyseqs = set((QKeySequence.Refresh,))
        if keys:
            self._keys.update(keys)
        if keyseqs:
            self._keyseqs.update(keyseqs)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.KeyPress:
            return super(KeyPressInterceptor, self).eventFilter(
                watched, event)
        if self._isinterceptable(event):
            event.ignore()
            return True
        return False

    def _isinterceptable(self, event):
        if event.key() in self._keys:
            return True
        if any(event.matches(e) for e in self._keyseqs):
            return True
        return False

def unbindConflictedKeys(sci):
    cmdset = sci.standardCommands()
    try:
        cmd = cmdset.boundTo(QKeySequence('CTRL+L'))
        if cmd:
            cmd.setKey(0)
    except AttributeError:  # old QScintilla does not have boundTo()
        pass

def qsciEolModeFromOs():
    if os.name.startswith('nt'):
        return QsciScintilla.EolWindows
    else:
        return QsciScintilla.EolUnix

def qsciEolModeFromLine(line):
    if line.endswith('\r\n'):
        return QsciScintilla.EolWindows
    elif line.endswith('\r'):
        return QsciScintilla.EolMac
    elif line.endswith('\n'):
        return QsciScintilla.EolUnix
    else:
        return qsciEolModeFromOs()

def findTabIndentsInLines(lines, linestocheck=100):
    for line in lines[:linestocheck]:
        if line.startswith(' '):
            return False
        elif line.startswith('\t'):
            return True
    return False # Use spaces for indents default

def readFile(editor, filename, encoding=None):
    f = QFile(filename)
    if not f.open(QIODevice.ReadOnly):
        qtlib.WarningMsgBox(_('Unable to read file'),
                            _('Could not open the specified file for reading.'),
                            f.errorString(), parent=editor)
        return False
    try:
        earlybytes = f.read(4096)
        if '\0' in earlybytes:
            qtlib.WarningMsgBox(_('Unable to read file'),
                                _('This appears to be a binary file.'),
                                parent=editor)
            return False

        f.seek(0)
        data = str(f.readAll())
        if f.error():
            qtlib.WarningMsgBox(_('Unable to read file'),
                                _('An error occurred while reading the file.'),
                                f.errorString(), parent=editor)
            return False
    finally:
        f.close()

    if encoding:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError, inst:
            qtlib.WarningMsgBox(_('Text Translation Failure'),
                                _('Could not translate the file content from '
                                  'native encoding.'),
                                (_('Several characters would be lost.')
                                 + '\n\n' + hglib.tounicode(str(inst))),
                                parent=editor)
            text = data.decode(encoding, 'replace')
    else:
        text = hglib.tounicode(data)
    editor.setText(text)
    editor.setDefaultEolMode()
    editor.setModified(False)
    return True

def writeFile(editor, filename, encoding=None):
    text = editor.text()
    try:
        if encoding:
            data = unicode(text).encode(encoding)
        else:
            data = hglib.fromunicode(text)
    except UnicodeEncodeError, inst:
        qtlib.WarningMsgBox(_('Unable to write file'),
                            _('Could not translate the file content to '
                              'native encoding.'),
                            hglib.tounicode(str(inst)), parent=editor)
        return False

    f = QFile(filename)
    if not f.open(QIODevice.WriteOnly):
        qtlib.WarningMsgBox(_('Unable to write file'),
                            _('Could not open the specified file for writing.'),
                            f.errorString(), parent=editor)
        return False
    try:
        if f.write(data) < 0:
            qtlib.WarningMsgBox(_('Unable to write file'),
                                _('An error occurred while writing the file.'),
                                f.errorString(), parent=editor)
            return False
    finally:
        f.close()
    return True

def fileEditor(filename, **opts):
    'Open a simple modal file editing dialog'
    dialog = QDialog()
    dialog.setWindowFlags(dialog.windowFlags()
                          & ~Qt.WindowContextHelpButtonHint
                          | Qt.WindowMaximizeButtonHint)
    dialog.setWindowTitle(filename)
    dialog.setLayout(QVBoxLayout())
    editor = Scintilla()
    editor.setBraceMatching(QsciScintilla.SloppyBraceMatch)
    editor.installEventFilter(KeyPressInterceptor(dialog))
    editor.setMarginLineNumbers(1, True)
    editor.setMarginWidth(1, '000')
    editor.setLexer(QsciLexerProperties())
    if opts.get('foldable'):
        editor.setFolding(QsciScintilla.BoxedTreeFoldStyle)
    dialog.layout().addWidget(editor)

    searchbar = SearchToolBar(dialog)
    searchbar.searchRequested.connect(editor.find)
    searchbar.conditionChanged.connect(editor.highlightText)
    searchbar.hide()
    def showsearchbar():
        text = editor.selectedText()
        if text:
            searchbar.setPattern(text)
        searchbar.show()
        searchbar.setFocus(Qt.OtherFocusReason)
    qtlib.newshortcutsforstdkey(QKeySequence.Find, dialog, showsearchbar)
    dialog.addActions(searchbar.editorActions())
    dialog.layout().addWidget(searchbar)

    BB = QDialogButtonBox
    bb = QDialogButtonBox(BB.Save|BB.Cancel)
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    dialog.layout().addWidget(bb)

    s = QSettings()
    geomname = 'editor-geom'
    desktopgeom = qApp.desktop().availableGeometry()
    dialog.resize(desktopgeom.size() * 0.5)
    dialog.restoreGeometry(s.value(geomname).toByteArray())

    if not readFile(editor, filename):
        return QDialog.Rejected
    ret = dialog.exec_()
    if ret != QDialog.Accepted:
        return ret
    if not writeFile(editor, filename):
        return QDialog.Rejected
    s.setValue(geomname, dialog.saveGeometry())
    return ret
