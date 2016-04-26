# docklog.py - Log dock widget for the TortoiseHg Workbench
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciScintilla

from mercurial import commands, util

from tortoisehg.hgqt import cmdui, qtlib
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

class _LogWidgetForConsole(cmdui.LogWidget):
    """Wrapped LogWidget for ConsoleWidget"""

    returnPressed = pyqtSignal(str)
    """Return key pressed when cursor is on prompt line"""
    historyRequested = pyqtSignal(str, int)  # keyword, direction
    completeRequested = pyqtSignal(str)

    _prompt = '% '

    def __init__(self, parent=None):
        super(_LogWidgetForConsole, self).__init__(parent)
        self._prompt_marker = self.markerDefine(QsciScintilla.Background)
        self.setMarkerBackgroundColor(QColor('#e8f3fe'), self._prompt_marker)
        self.cursorPositionChanged.connect(self._updatePrompt)
        # ensure not moving prompt line even if completion list get shorter,
        # by allowing to scroll one page below the last line
        self.SendScintilla(QsciScintilla.SCI_SETENDATLASTLINE, False)
        # don't reserve "slop" area at top/bottom edge on ensureFooVisible()
        self.SendScintilla(QsciScintilla.SCI_SETVISIBLEPOLICY, 0, 0)

        self._savedcommands = []  # temporarily-invisible command
        self._origcolor = None
        self._flashtimer = QTimer(self, interval=100, singleShot=True)
        self._flashtimer.timeout.connect(self._restoreColor)

    def keyPressEvent(self, event):
        cursoronprompt = not self.isReadOnly()
        if cursoronprompt:
            if event.key() == Qt.Key_Up:
                return self.historyRequested.emit(self.commandText(), -1)
            elif event.key() == Qt.Key_Down:
                return self.historyRequested.emit(self.commandText(), +1)
            del self._savedcommands[:]  # settle candidate by user input
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                return self.returnPressed.emit(self.commandText())
            if event.key() == Qt.Key_Tab:
                return self.completeRequested.emit(self.commandText())
        if event.key() == Qt.Key_Escape:
            # When ESC is pressed, if the cursor is on the prompt,
            # this clears it, if not, this moves the cursor to the prompt
            self.setCommandText('')

        super(_LogWidgetForConsole, self).keyPressEvent(event)

    def setPrompt(self, text):
        if text == self._prompt:
            return
        if self._findPromptLine() < 0:
            self._prompt = text
            return
        self.clearPrompt()
        self._prompt = text
        self.openPrompt()

    @pyqtSlot()
    def openPrompt(self):
        """Show prompt line and enable user input"""
        self.closePrompt()
        line = self.lines() - 1
        self.markerAdd(line, self._prompt_marker)
        self.append(self._prompt)
        if self._savedcommands:
            self.append(self._savedcommands.pop())
        self.setCursorPosition(line, len(self.text(line)))
        self.setReadOnly(False)

        # make sure the prompt line is visible. Because QsciScintilla may
        # delay line wrapping, setCursorPosition() doesn't always scrolls
        # to the correct position.
        # http://www.scintilla.org/ScintillaDoc.html#LineWrapping
        self.SCN_PAINTED.connect(self._scrollCaretOnPainted)

    @pyqtSlot()
    def _scrollCaretOnPainted(self):
        self.SCN_PAINTED.disconnect(self._scrollCaretOnPainted)
        self.SendScintilla(self.SCI_SCROLLCARET)

    def _removeTrailingText(self, line, index):
        visline = self.firstVisibleLine()
        lastline = self.lines() - 1
        self.setSelection(line, index, lastline, len(self.text(lastline)))
        self.removeSelectedText()
        # restore scroll position changed by setSelection()
        self.verticalScrollBar().setValue(visline)

    def _findPromptLine(self):
        return self.markerFindPrevious(self.lines() - 1,
                                       1 << self._prompt_marker)

    @pyqtSlot()
    def clearLog(self):
        wasopen = self._findPromptLine() >= 0
        self.clear()
        if wasopen:
            self.openPrompt()

    @pyqtSlot()
    def closePrompt(self):
        """Disable user input"""
        line = self._findPromptLine()
        if line >= 0:
            if self.commandText():
                self._setmarker((line,), 'control')
            self.markerDelete(line, self._prompt_marker)
            self._removeTrailingText(line + 1, 0)  # clear completion
        self._newline()
        self.setCursorPosition(self.lines() - 1, 0)
        self.setReadOnly(True)

    @pyqtSlot()
    def clearPrompt(self):
        """Clear prompt line and subsequent text"""
        line = self._findPromptLine()
        if line < 0:
            return
        self._savedcommands = [self.commandText()]
        self.markerDelete(line)
        self._removeTrailingText(line, 0)

    @pyqtSlot(int, int)
    def _updatePrompt(self, line, pos):
        """Update availability of user input"""
        if self.markersAtLine(line) & (1 << self._prompt_marker):
            self.setReadOnly(pos < len(self._prompt))
            self._ensurePrompt(line)
            if pos < len(self._prompt):
                # avoid inconsistency caused by changing pos inside
                # cursorPositionChanged
                QTimer.singleShot(0, self._moveCursorToPromptHome)
        else:
            self.setReadOnly(True)

    @pyqtSlot()
    def _moveCursorToPromptHome(self):
        line = self._findPromptLine()
        if line >= 0:
            self.setCursorPosition(line, len(self._prompt))

    def _ensurePrompt(self, line):
        """Insert prompt string if not available"""
        s = unicode(self.text(line))
        if s.startswith(self._prompt):
            return
        for i, c in enumerate(self._prompt):
            if s[i:i + 1] != c:
                self.insertAt(self._prompt[i:], line, i)
                break

    def commandText(self):
        """Return the current command text"""
        if self._savedcommands:
            return self._savedcommands[-1]
        l = self._findPromptLine()
        if l >= 0:
            return unicode(self.text(l))[len(self._prompt):].rstrip('\n')
        else:
            return ''

    def setCommandText(self, text, candidate=False):
        """Replace the current command text; subsequent text is also removed.

        If candidate, the specified text is displayed but does not replace
        commandText() until the user takes some action.
        """
        line = self._findPromptLine()
        if line < 0:
            return
        if candidate:
            self._savedcommands = [self.commandText()]
        else:
            del self._savedcommands[:]
        self._ensurePrompt(line)
        self._removeTrailingText(line, len(self._prompt))
        self.insert(text)
        self.setCursorPosition(line, len(self.text(line)))

    def _newline(self):
        if self.text(self.lines() - 1):
            self.append('\n')

    def flash(self, color='brown'):
        """Briefly change the text color to catch the user attention"""
        if self._flashtimer.isActive():
            return
        self._origcolor = self.color()
        self.setColor(QColor(color))
        self._flashtimer.start()

    @pyqtSlot()
    def _restoreColor(self):
        assert self._origcolor
        self.setColor(self._origcolor)

def _searchhistory(items, text, direction, idx):
    """Search history items and return (item, index_of_item)

    Valid index is zero or negative integer. Zero is reserved for non-history
    item.

    >>> def searchall(items, text, direction, idx=0):
    ...     matched = []
    ...     while True:
    ...         it, idx = _searchhistory(items, text, direction, idx)
    ...         if not it:
    ...             return matched, idx
    ...         matched.append(it)

    >>> searchall('foo bar baz'.split(), '', direction=-1)
    (['baz', 'bar', 'foo'], -4)
    >>> searchall('foo bar baz'.split(), '', direction=+1, idx=-3)
    (['bar', 'baz'], 0)

    search by keyword:

    >>> searchall('foo bar baz'.split(), 'b', direction=-1)
    (['baz', 'bar'], -4)
    >>> searchall('foo bar baz'.split(), 'inexistent', direction=-1)
    ([], -4)

    empty history:

    >>> searchall([], '', direction=-1)
    ([], -1)

    initial index out of range:

    >>> searchall('foo bar baz'.split(), '', direction=-1, idx=-3)
    ([], -4)
    >>> searchall('foo bar baz'.split(), '', direction=+1, idx=0)
    ([], 1)
    """
    assert direction != 0
    idx += direction
    while -len(items) <= idx < 0:
        curcmdline = items[idx]
        if curcmdline.startswith(text):
            return curcmdline, idx
        idx += direction
    return None, idx

class ConsoleWidget(QWidget, qtlib.TaskWidget):
    """Console to run hg/thg command and show output"""
    closeRequested = pyqtSignal()

    def __init__(self, agent, parent=None):
        QWidget.__init__(self, parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._initlogwidget()
        self.setFocusProxy(self._logwidget)
        self._agent = agent
        agent.busyChanged.connect(self._suppressPromptOnBusy)
        agent.outputReceived.connect(self.appendLog)
        if util.safehasattr(agent, 'displayName'):
            self._logwidget.setPrompt('%s%% ' % agent.displayName())
        self.openPrompt()
        self._commandHistory = []
        self._commandIdx = 0

    def _initlogwidget(self):
        self._logwidget = _LogWidgetForConsole(self)
        self._logwidget.returnPressed.connect(self._runcommand)
        self._logwidget.historyRequested.connect(self.historySearch)
        self._logwidget.completeRequested.connect(self.completeCommandText)
        self.layout().addWidget(self._logwidget)

        # compatibility methods with LogWidget
        for name in ('openPrompt', 'closePrompt', 'clear'):
            setattr(self, name, getattr(self._logwidget, name))

    @pyqtSlot(str, int)
    def historySearch(self, text, direction):
        cmdline, idx = _searchhistory(self._commandHistory, unicode(text),
                                      direction, self._commandIdx)
        if cmdline:
            self._commandIdx = idx
            self._logwidget.setCommandText(cmdline, candidate=True)
        else:
            self._logwidget.flash()

    def _commandComplete(self, cmdtype, cmdline):
        from tortoisehg.hgqt import run
        matches = []
        cmd = cmdline.split()
        if cmdtype == 'hg':
            cmdtable = commands.table
        else:
            cmdtable = run.table
        subcmd = ''
        if len(cmd) >= 2:
            subcmd = cmd[1].lower()
        def findhgcmd(cmdstart):
            matchinfo = {}
            for cmdspec in cmdtable:
                for cmdname in cmdspec.split('|'):
                    if cmdname[0] == '^':
                        cmdname = cmdname[1:]
                    if cmdname.startswith(cmdstart):
                        matchinfo[cmdname] = cmdspec
            return matchinfo
        matchingcmds = findhgcmd(subcmd)
        if not matchingcmds:
            return matches
        if len(matchingcmds) > 1:
            basecmdline = '%s %%s' % (cmdtype)
            matches = [basecmdline % c for c in matchingcmds]
        else:
            scmdtype = matchingcmds.keys()[0]
            cmdspec = matchingcmds[scmdtype]
            opts = cmdtable[cmdspec][1]
            def findcmdopt(cmdopt):
                cmdopt = cmdopt.lower()
                while(cmdopt.startswith('-')):
                    cmdopt = cmdopt[1:]
                matchingopts = []
                for opt in opts:
                    if opt[1].startswith(cmdopt):
                        matchingopts.append(opt)
                return matchingopts
            basecmdline = '%s %s --%%s' % (cmdtype, scmdtype)
            if len(cmd) == 2:
                matches = ['%s %s ' % (cmdtype, scmdtype)]
                matches += [basecmdline % opt[1] for opt in opts]
            else:
                cmdopt = cmd[-1]
                if cmdopt.startswith('-'):
                    # find the matching options
                    basecmdline = ' '.join(cmd[:-1]) + ' --%s'
                    cmdopts = findcmdopt(cmdopt)
                    matches = [basecmdline % opt[1] for opt in cmdopts]
        return sorted(matches)

    @pyqtSlot(str)
    def completeCommandText(self, text):
        """Show the list of history or known commands matching the search text

        Also complete the prompt with the common prefix to the matching items
        """
        text = unicode(text).strip()
        if not text:
            self._logwidget.flash()
            return
        history = set(self._commandHistory)
        commonprefix = ''
        matches = []
        for cmdline in history:
            if cmdline.startswith(text):
                matches.append(cmdline)
        if matches:
            matches.sort()
            commonprefix = os.path.commonprefix(matches)
        cmd = text.split()
        cmdtype = cmd[0].lower()
        if cmdtype in ('hg', 'thg'):
            hgcommandmatches = self._commandComplete(cmdtype, text)
            if hgcommandmatches:
                if not commonprefix:
                    commonprefix = os.path.commonprefix(hgcommandmatches)
                if matches:
                    matches.append('------ %s commands ------' % cmdtype)
                matches += hgcommandmatches
        if not matches:
            self._logwidget.flash()
            return
        self._logwidget.setCommandText(commonprefix)
        if len(matches) > 1:
            self._logwidget.append('\n' + '\n'.join(matches) + '\n')
            self._logwidget.ensureLineVisible(self._logwidget.lines() - 1)
            self._logwidget.ensureCursorVisible()

    @util.propertycache
    def _extproc(self):
        extproc = QProcess(self)
        extproc.started.connect(self.closePrompt)
        extproc.finished.connect(self.openPrompt)
        extproc.error.connect(self._handleExtprocError)
        extproc.readyReadStandardOutput.connect(self._appendExtprocStdout)
        extproc.readyReadStandardError.connect(self._appendExtprocStderr)
        return extproc

    @pyqtSlot()
    def _handleExtprocError(self):
        if self._extproc.state() == QProcess.NotRunning:
            self._logwidget.closePrompt()
        msg = self._extproc.errorString()
        self._logwidget.appendLog(msg + '\n', 'ui.error')
        if self._extproc.state() == QProcess.NotRunning:
            self._logwidget.openPrompt()

    @pyqtSlot()
    def _appendExtprocStdout(self):
        text = hglib.tounicode(self._extproc.readAllStandardOutput().data())
        self._logwidget.appendLog(text, '')

    @pyqtSlot()
    def _appendExtprocStderr(self):
        text = hglib.tounicode(self._extproc.readAllStandardError().data())
        self._logwidget.appendLog(text, 'ui.warning')

    @pyqtSlot(str, str)
    def appendLog(self, msg, label):
        """Append log text to the last line while keeping the prompt line"""
        self._logwidget.clearPrompt()
        try:
            self._logwidget.appendLog(msg, label)
        finally:
            if not self._agent.isBusy():
                self.openPrompt()

    def repoRootPath(self):
        if util.safehasattr(self._agent, 'rootPath'):
            return self._agent.rootPath()

    @property
    def _repo(self):
        if util.safehasattr(self._agent, 'rawRepo'):
            return self._agent.rawRepo()

    def _workingDirectory(self):
        return self.repoRootPath() or os.getcwdu()

    @pyqtSlot(bool)
    def _suppressPromptOnBusy(self, busy):
        if busy:
            self._logwidget.clearPrompt()
        else:
            self.openPrompt()

    @pyqtSlot(str)
    def _runcommand(self, cmdline):
        cmdline = unicode(cmdline)
        self._commandIdx = 0
        try:
            args = hglib.parsecmdline(cmdline, self._workingDirectory())
        except ValueError, e:
            self.closePrompt()
            self._logwidget.appendLog(unicode(e) + '\n', 'ui.error')
            self.openPrompt()
            return
        if not args:
            self.openPrompt()
            return
        # add command to command history
        if not self._commandHistory or self._commandHistory[-1] != cmdline:
            self._commandHistory.append(cmdline)
        # execute the command
        cmd = args.pop(0)
        try:
            self._cmdtable[cmd](self, args)
        except KeyError:
            return self._runextcommand(cmdline)

    def _runextcommand(self, cmdline):
        self._extproc.setWorkingDirectory(self._workingDirectory())
        self._extproc.start(cmdline, QIODevice.ReadOnly)

    def _cmd_hg(self, args):
        self.closePrompt()
        self._agent.runCommand(args, self)

    def _cmd_thg(self, args):
        from tortoisehg.hgqt import run
        self.closePrompt()
        try:
            if self.repoRootPath():
                args = ['-R', self.repoRootPath()] + args
            # TODO: show errors
            run.dispatch(map(hglib.fromunicode, args))
        finally:
            self.openPrompt()

    def _cmd_clear(self, args):
        self._logwidget.clearLog()

    def _cmd_exit(self, args):
        self._logwidget.clearLog()
        self.closeRequested.emit()

    _cmdtable = {
        'hg':    _cmd_hg,
        'thg':   _cmd_thg,
        'clear': _cmd_clear,
        'cls':   _cmd_clear,
        'exit':  _cmd_exit,
        }


class LogDockWidget(QDockWidget):

    def __init__(self, repomanager, cmdagent, parent=None):
        super(LogDockWidget, self).__init__(parent)

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Console'))
        # Not enabled until we have a way to make it configurable
        #self.setWindowFlags(Qt.Drawer)
        self.dockLocationChanged.connect(self._updateTitleBarStyle)

        self._repomanager = repomanager
        self._repomanager.repositoryOpened.connect(self._createConsoleFor)
        self._repomanager.repositoryClosed.connect(self._destroyConsoleFor)

        self._consoles = QStackedWidget(self)
        self.setWidget(self._consoles)
        self._createConsole(cmdagent)
        for root in self._repomanager.repoRootPaths():
            self._createConsoleFor(root)

    def setCurrentRepoRoot(self, root):
        w = self._findConsoleFor(root)
        self._consoles.setCurrentWidget(w)
        self.setFocusProxy(w)

    def _findConsoleFor(self, root):
        for i in xrange(self._consoles.count()):
            w = self._consoles.widget(i)
            if w.repoRootPath() == root:
                return w
        raise ValueError('no console found for %r' % root)

    def _createConsole(self, agent):
        w = ConsoleWidget(agent, self)
        w.closeRequested.connect(self.close)
        self._consoles.addWidget(w)
        return w

    @pyqtSlot(str)
    def _createConsoleFor(self, root):
        root = unicode(root)
        repoagent = self._repomanager.repoAgent(root)
        assert repoagent
        self._createConsole(repoagent)

    @pyqtSlot(str)
    def _destroyConsoleFor(self, root):
        root = unicode(root)
        w = self._findConsoleFor(root)
        self._consoles.removeWidget(w)
        w.setParent(None)

    def setVisible(self, visible):
        super(LogDockWidget, self).setVisible(visible)
        if visible:
            self.raise_()

    @pyqtSlot(Qt.DockWidgetArea)
    def _updateTitleBarStyle(self, area):
        f = self.features()
        if area & (Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea):
            f |= QDockWidget.DockWidgetVerticalTitleBar  # saves vertical space
        else:
            f &= ~QDockWidget.DockWidgetVerticalTitleBar
        self.setFeatures(f)
