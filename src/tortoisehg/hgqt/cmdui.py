# cmdui.py - A widget to execute Mercurial command for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import weakref

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciScintilla

from tortoisehg.util.i18n import _
from tortoisehg.util import hglib
from tortoisehg.hgqt import cmdcore, qtlib, qscilib

def startProgress(topic, status):
    topic, item, pos, total, unit = topic, '...', status, None, ''
    return (topic, pos, item, unit, total)

def stopProgress(topic):
    topic, item, pos, total, unit = topic, '', None, None, ''
    return (topic, pos, item, unit, total)

class ProgressMonitor(QWidget):
    'Progress bar for use in workbench status bar'
    def __init__(self, topic, parent):
        super(ProgressMonitor, self).__init__(parent)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*(0,)*4)
        self.setLayout(hbox)
        self.idle = False

        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setMinimum(0)
        hbox.addWidget(self.pbar)

        self.topic = QLabel(topic)
        hbox.addWidget(self.topic, 0)

        self.status = QLabel()
        hbox.addWidget(self.status, 1)

        self.pbar.setMaximum(100)
        self.pbar.reset()
        self.status.setText('')

    def clear(self):
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(100)
        self.pbar.setValue(100)
        self.status.setText('')
        self.idle = True

    def setcounts(self, cur, max):
        # cur and max may exceed INT_MAX, which confuses QProgressBar
        assert max != 0
        self.pbar.setMaximum(100)
        self.pbar.setValue(int(cur * 100 / max))

    def unknown(self):
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(0)


class ThgStatusBar(QStatusBar):
    linkActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        QStatusBar.__init__(self, parent)
        self.topics = {}
        self.lbl = QLabel()
        self.lbl.linkActivated.connect(self.linkActivated)
        self.addWidget(self.lbl)
        self._busyrepos = set()
        self._busypbar = QProgressBar(self, minimum=0, maximum=0)
        self.addWidget(self._busypbar)
        self.setStyleSheet('QStatusBar::item { border: none }')
        self._updateBusyProgress()

    @pyqtSlot(str)
    def showMessage(self, ustr, error=False):
        self.lbl.setText(ustr)
        if error:
            self.lbl.setStyleSheet('QLabel { color: red }')
        else:
            self.lbl.setStyleSheet('')

    def setRepoBusy(self, root, busy):
        root = unicode(root)
        if busy:
            self._busyrepos.add(root)
        else:
            self._busyrepos.discard(root)
        self._updateBusyProgress()

    def _updateBusyProgress(self):
        # busy indicator is the last option, which is visible only if no
        # progress information is available
        visible = bool(self._busyrepos and not self.topics)
        self._busypbar.setVisible(visible)
        if visible:
            self._busypbar.setMaximumSize(150, self.lbl.sizeHint().height())

    @pyqtSlot()
    def clearProgress(self):
        keys = self.topics.keys()
        for key in keys:
            self._removeProgress(key)

    @pyqtSlot(str)
    def clearRepoProgress(self, root):
        root = unicode(root)
        keys = [k for k in self.topics if k[0] == root]
        for key in keys:
            self._removeProgress(key)

    def _removeProgress(self, key):
        pm = self.topics[key]
        self.removeWidget(pm)
        pm.setParent(None)
        del self.topics[key]
        self._updateBusyProgress()

    # TODO: migrate to setProgress() API
    @pyqtSlot(str, object, str, str, object)
    def progress(self, topic, pos, item, unit, total, root=None):
        'Progress signal received from repowidget'
        # topic is current operation
        # pos is the current numeric position (revision, bytes)
        # item is a non-numeric marker of current position (current file)
        # unit is a string label
        # total is the highest expected pos
        #
        # All topics should be marked closed by setting pos to None
        key = (root, topic)
        if pos is None or (not pos and not total):
            if key in self.topics:
                self._removeProgress(key)
            return
        if key not in self.topics:
            pm = ProgressMonitor(topic, self)
            pm.setMaximumHeight(self.lbl.sizeHint().height())
            self.addWidget(pm)
            self.topics[key] = pm
            self._updateBusyProgress()
        else:
            pm = self.topics[key]
        if total:
            fmt = '%s / %s ' % (unicode(pos), unicode(total))
            if unit:
                fmt += unit
            pm.status.setText(fmt)
            pm.setcounts(pos, total)
        else:
            if item:
                item = item[-30:]
            pm.status.setText('%s %s' % (unicode(pos), item))
            pm.unknown()

    @pyqtSlot(cmdcore.ProgressMessage)
    def setProgress(self, progress):
        self.progress(*progress)

    @pyqtSlot(str, cmdcore.ProgressMessage)
    def setRepoProgress(self, root, progress):
        self.progress(*(progress + (unicode(root),)))


def updateStatusMessage(stbar, session):
    """Update status bar to show the status of the given session"""
    if not session.isFinished():
        stbar.showMessage(_('Running...'))
    elif session.isAborted():
        stbar.showMessage(_('Terminated by user'))
    elif session.exitCode() == 0:
        stbar.showMessage(_('Finished'))
    else:
        stbar.showMessage(_('Failed!'), True)


class LogWidget(qscilib.ScintillaCompat):
    """Output log viewer"""

    def __init__(self, parent=None):
        super(LogWidget, self).__init__(parent)
        self.setReadOnly(True)
        self.setUtf8(True)
        self.setMarginWidth(1, 0)
        self.setWrapMode(QsciScintilla.WrapCharacter)
        self._initfont()
        self._initmarkers()
        qscilib.unbindConflictedKeys(self)

    def _initfont(self):
        tf = qtlib.getfont('fontoutputlog')
        tf.changed.connect(self.forwardFont)
        self.setFont(tf.font())

    @pyqtSlot(QFont)
    def forwardFont(self, font):
        self.setFont(font)

    def _initmarkers(self):
        self._markers = {}
        for l in ('ui.error', 'ui.warning', 'control'):
            self._markers[l] = m = self.markerDefine(QsciScintilla.Background)
            c = QColor(qtlib.getbgcoloreffect(l))
            if c.isValid():
                self.setMarkerBackgroundColor(c, m)
            # NOTE: self.setMarkerForegroundColor() doesn't take effect,
            # because it's a *Background* marker.

    @pyqtSlot(str, str)
    def appendLog(self, msg, label):
        """Append log text to the last line; scrolls down to there"""
        self.append(msg)
        self._setmarker(xrange(self.lines() - unicode(msg).count('\n') - 1,
                               self.lines() - 1), unicode(label))
        self.setCursorPosition(self.lines() - 1, 0)

    def _setmarker(self, lines, label):
        for m in self._markersforlabel(label):
            for i in lines:
                self.markerAdd(i, m)

    def _markersforlabel(self, label):
        return iter(self._markers[l] for l in label.split()
                    if l in self._markers)

    @pyqtSlot()
    def clearLog(self):
        """This slot can be overridden by subclass to do more actions"""
        self.clear()

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction(_('Clea&r Log'), self.clearLog)
        menu.exec_(event.globalPos())
        menu.setParent(None)

    def keyPressEvent(self, event):
        # propagate key events important for dialog
        if event.key() == Qt.Key_Escape:
            event.ignore()
            return
        super(LogWidget, self).keyPressEvent(event)


class InteractiveUiHandler(cmdcore.UiHandler):
    """Handle user interaction of Mercurial commands with GUI prompt"""

    # Unlike QObject, "uiparent" does not own this handler
    def __init__(self, uiparent=None):
        super(InteractiveUiHandler, self).__init__()
        self._prompttext = ''
        self._promptmode = cmdcore.UiHandler.NoInput
        self._promptdefault = ''
        self._uiparentref = uiparent and weakref.ref(uiparent)

    def setPrompt(self, text, mode, default=None):
        self._prompttext = unicode(text)
        self._promptmode = mode
        self._promptdefault = unicode(default or '')

    def getLineInput(self):
        mode = self._promptmode
        if mode == cmdcore.UiHandler.TextInput:
            return self._getTextInput(QLineEdit.Normal)
        elif mode == cmdcore.UiHandler.PasswordInput:
            return self._getTextInput(QLineEdit.Password)
        elif mode == cmdcore.UiHandler.ChoiceInput:
            return self._getChoiceInput()
        else:
            return ''

    def _getTextInput(self, echomode):
        text, ok = qtlib.getTextInput(self._parentWidget(),
                                      _('TortoiseHg Prompt'),
                                      self._prompttext, echomode)
        if ok:
            return text

    def _getChoiceInput(self):
        msg, choicepairs = hglib.extractchoices(self._prompttext)
        dlg = QMessageBox(QMessageBox.Question, _('TortoiseHg Prompt'), msg,
                          QMessageBox.NoButton, self._parentWidget())
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        for r, t in choicepairs:
            button = dlg.addButton(t, QMessageBox.ActionRole)
            button.response = r
            if r == self._promptdefault:
                dlg.setDefaultButton(button)
        # cancel button is necessary to close prompt dialog with empty response
        dlg.addButton(QMessageBox.Cancel).hide()
        dlg.exec_()
        button = dlg.clickedButton()
        if button and dlg.buttonRole(button) == QMessageBox.ActionRole:
            return button.response

    def _parentWidget(self):
        p = self._uiparentref and self._uiparentref()
        while p and not p.isWidgetType():
            p = p.parent()
        return p


class PasswordUiHandler(InteractiveUiHandler):
    """Handle no user interaction of Mercurial commands but password input"""

    def getLineInput(self):
        mode = self._promptmode
        if mode == cmdcore.UiHandler.PasswordInput:
            return self._getTextInput(QLineEdit.Password)
        else:
            return ''


_detailbtntextmap = {
    # current state: action text
    False: _('Show Detail'),
    True: _('Hide Detail')}


class CmdSessionControlWidget(QWidget):
    """Helper widget to implement dialog to run Mercurial commands"""

    finished = pyqtSignal(int)
    linkActivated = pyqtSignal(str)
    logVisibilityChanged = pyqtSignal(bool)

    # this won't provide commandFinished signal because the client code
    # should know the running session.

    def __init__(self, parent=None, logVisible=False):
        super(CmdSessionControlWidget, self).__init__(parent)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        vbox.setContentsMargins(0, 0, 0, 0)

        # command output area
        self._outputLog = LogWidget(self)
        self._outputLog.setVisible(logVisible)
        vbox.addWidget(self._outputLog, 1)

        ## status and progress labels
        self._stbar = ThgStatusBar()
        self._stbar.setSizeGripEnabled(False)
        self._stbar.linkActivated.connect(self.linkActivated)
        vbox.addWidget(self._stbar)

        # bottom buttons
        self._buttonbox = buttons = QDialogButtonBox()
        self._cancelBtn = buttons.addButton(QDialogButtonBox.Cancel)
        self._cancelBtn.clicked.connect(self.abortCommand)

        self._closeBtn = buttons.addButton(QDialogButtonBox.Close)
        self._closeBtn.clicked.connect(self.reject)

        self._detailBtn = buttons.addButton(_detailbtntextmap[logVisible],
                                            QDialogButtonBox.ResetRole)
        self._detailBtn.setAutoDefault(False)
        self._detailBtn.setCheckable(True)
        self._detailBtn.setChecked(logVisible)
        self._detailBtn.toggled.connect(self.setLogVisible)
        vbox.addWidget(buttons)

        self.setLayout(vbox)

        self._session = cmdcore.nullCmdSession()
        self._stbar.hide()
        self._updateSizePolicy()
        self._updateUi()

    def session(self):
        return self._session

    def setSession(self, sess):
        """Start watching the given command session"""
        assert self._session.isFinished()
        self._session = sess
        sess.commandFinished.connect(self._onCommandFinished)
        sess.outputReceived.connect(self._outputLog.appendLog)
        sess.progressReceived.connect(self._stbar.setProgress)
        self._cancelBtn.setEnabled(True)
        self._updateStatus()

    @pyqtSlot()
    def abortCommand(self):
        self._session.abort()
        self._cancelBtn.setDisabled(True)

    @pyqtSlot()
    def _onCommandFinished(self):
        self._updateStatus()
        self._stbar.clearProgress()

    def addButton(self, text, role):
        """Add custom button which will typically start Mercurial command"""
        button = self._buttonbox.addButton(text, role)
        self._updateUi()
        return button

    @pyqtSlot()
    def setFocusToCloseButton(self):
        self._closeBtn.setFocus()

    def showStatusMessage(self, message):
        """Display the given message in status bar; the message remains until
        the command status is changed"""
        self._stbar.showMessage(message)
        self._stbar.show()

    def isLogVisible(self):
        return self._outputLog.isVisibleTo(self)

    @pyqtSlot(bool)
    def setLogVisible(self, visible):
        """show/hide command output"""
        if visible == self.isLogVisible():
            return
        self._outputLog.setVisible(visible)
        self._detailBtn.setChecked(visible)
        self._detailBtn.setText(_detailbtntextmap[visible])
        self._updateSizePolicy()
        self.logVisibilityChanged.emit(visible)

    @pyqtSlot()
    def reject(self):
        """Request to close the dialog or abort the running command"""
        if not self._session.isFinished():
            ret = QMessageBox.question(self, _('Confirm Exit'),
                        _('Mercurial command is still running.\n'
                          'Are you sure you want to terminate?'),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.abortCommand()
            return

        self.finished.emit(self._session.exitCode())

    def _updateSizePolicy(self):
        if self.testAttribute(Qt.WA_WState_OwnSizePolicy):
            return
        if self.isLogVisible():
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_WState_OwnSizePolicy, False)

    def _updateStatus(self):
        self._stbar.show()
        self._updateUi()

    def _updateUi(self):
        updateStatusMessage(self._stbar, self._session)
        self._cancelBtn.setVisible(not self._session.isFinished())
        self._closeBtn.setVisible(self._session.isFinished())


class AbstractCmdWidget(QWidget):
    """Widget to prepare Mercurial command controlled by CmdControlDialog"""

    # signal to update "Run" button, etc.
    commandChanged = pyqtSignal()

    def readSettings(self, qs):
        pass
    def writeSettings(self, qs):
        pass
    def canRunCommand(self):
        # True if all command parameters are valid
        raise NotImplementedError
    def runCommand(self):
        # return new CmdSession or nullCmdSession on error
        raise NotImplementedError


class CmdControlDialog(QDialog):
    """Dialog to run one-shot Mercurial command prepared by embedded widget

    The embedded widget must implement AbstractCmdWidget or provide signals
    and methods defined by it.

    Settings are prefixed by the objectName() group, so you should specify
    unique name by setObjectName().

    You don't need to extend this class unless you want to provide additional
    public methods/signals, or implement custom error handling.

    Unlike QDialog, the result code is set to the exit code of the last
    command.  exec_() returns 0 on success.
    """

    commandFinished = pyqtSignal(int)

    def __init__(self, parent=None):
        super(CmdControlDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint)

        vbox = QVBoxLayout()
        vbox.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setLayout(vbox)

        self.__cmdwidget = None

        self.__cmdcontrol = cmd = CmdSessionControlWidget(self)
        cmd.finished.connect(self.done)
        vbox.addWidget(cmd)
        self.__runbutton = cmd.addButton(_('&Run'), QDialogButtonBox.AcceptRole)
        self.__runbutton.clicked.connect(self.runCommand)

        self.__updateUi()

    # use __-prefix, name mangling, to avoid name conflicts in derived classes

    def __readSettings(self):
        if not self.objectName():
            return
        assert self.__cmdwidget
        qs = QSettings()
        qs.beginGroup(self.objectName())
        self.__cmdwidget.readSettings(qs)
        self.restoreGeometry(qs.value('geom').toByteArray())
        qs.endGroup()

    def __writeSettings(self):
        if not self.objectName():
            return
        assert self.__cmdwidget
        qs = QSettings()
        qs.beginGroup(self.objectName())
        self.__cmdwidget.writeSettings(qs)
        qs.setValue('geom', self.saveGeometry())
        qs.endGroup()

    def commandWidget(self):
        return self.__cmdwidget

    def setCommandWidget(self, widget):
        oldwidget = self.__cmdwidget
        if oldwidget is widget:
            return
        if oldwidget:
            oldwidget.commandChanged.disconnect(self.__updateUi)
            self.layout().removeWidget(oldwidget)
            oldwidget.setParent(None)

        self.__cmdwidget = widget
        if widget:
            self.layout().insertWidget(0, widget, 1)
            widget.commandChanged.connect(self.__updateUi)
            self.__readSettings()
            self.__fixInitialFocus()
        self.__updateUi()

    def __fixInitialFocus(self):
        if self.focusWidget():
            # do not change if already set
            return

        # set focus to the first item of the command widget
        fw = self.__cmdwidget
        while fw.focusPolicy() == Qt.NoFocus or not fw.isVisibleTo(self):
            fw = fw.nextInFocusChain()
            if fw is self.__cmdwidget or fw is self.__cmdcontrol:
                # no candidate available
                return
        fw.setFocus()

    def runButtonText(self):
        return self.__runbutton.text()

    def setRunButtonText(self, text):
        self.__runbutton.setText(text)

    def isLogVisible(self):
        return self.__cmdcontrol.isLogVisible()

    def setLogVisible(self, visible):
        self.__cmdcontrol.setLogVisible(visible)

    def isCommandFinished(self):
        """True if no pending or running command exists (but might not be
        ready to run command because of incomplete user input)"""
        return self.__cmdcontrol.session().isFinished()

    def canRunCommand(self):
        """True if everything's ready to run command"""
        return (bool(self.__cmdwidget) and self.__cmdwidget.canRunCommand()
                and self.isCommandFinished())

    @pyqtSlot()
    def runCommand(self):
        if not self.canRunCommand():
            return
        sess = self.__cmdwidget.runCommand()
        if sess.isFinished():
            return
        self.__cmdcontrol.setSession(sess)
        sess.commandFinished.connect(self.__onCommandFinished)
        self.__updateUi()

    @pyqtSlot(int)
    def __onCommandFinished(self, ret):
        self.__updateUi()
        if ret == 0:
            self.__runbutton.hide()
            self.__cmdcontrol.setFocusToCloseButton()
        elif ret == 255 and not self.__cmdcontrol.session().isAborted():
            errorMessageBox(self.__cmdcontrol.session(), self)

        # handle command-specific error if any
        self.commandFinished.emit(ret)

        if ret != 255:
            self.__writeSettings()
        if ret == 0 and not self.isLogVisible():
            self.__cmdcontrol.reject()

    def lastFinishedSession(self):
        """Session of the last executed command; can be used in commandFinished
        handler"""
        sess = self.__cmdcontrol.session()
        if not sess.isFinished():
            # do not expose running session because this dialog should have
            # full responsibility to control running command
            return cmdcore.nullCmdSession()
        return sess

    def reject(self):
        self.__cmdcontrol.reject()

    @pyqtSlot()
    def __updateUi(self):
        if self.__cmdwidget:
            self.__cmdwidget.setEnabled(self.isCommandFinished())
        self.__runbutton.setEnabled(self.canRunCommand())


class CmdSessionDialog(QDialog):
    """Dialog to monitor running Mercurial commands

    Unlike QDialog, the result code is set to the exit code of the last
    command.  exec_() returns 0 on success.
    """

    # this won't provide commandFinished signal because the client code
    # should know the running session.

    def __init__(self, parent=None):
        super(CmdSessionDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(_('TortoiseHg Command Dialog'))
        self.resize(540, 420)

        vbox = QVBoxLayout()
        self.setLayout(vbox)
        vbox.setContentsMargins(5, 5, 5, 5)
        vbox.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._cmdcontrol = cmd = CmdSessionControlWidget(self, logVisible=True)
        cmd.finished.connect(self.done)
        vbox.addWidget(cmd)

    def setSession(self, sess):
        """Start watching the given command session"""
        self._cmdcontrol.setSession(sess)
        sess.commandFinished.connect(self._cmdcontrol.setFocusToCloseButton)

    def isLogVisible(self):
        return self._cmdcontrol.isLogVisible()

    def setLogVisible(self, visible):
        """show/hide command output"""
        self._cmdcontrol.setLogVisible(visible)

    def reject(self):
        self._cmdcontrol.reject()


def errorMessageBox(session, parent=None, title=None):
    """Open a message box to report the error of the given session"""
    if not title:
        title = _('Command Error')
    reason = session.errorString()
    text = session.warningString()
    if text:
        text += '\n\n'
    text += _('[Code: %d]') % session.exitCode()
    return qtlib.WarningMsgBox(title, reason, text, parent=parent)
