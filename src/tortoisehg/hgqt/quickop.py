# quickop.py - TortoiseHg's dialog for quick dirstate operations
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, sys

from mercurial import util

from tortoisehg.util import hglib, shlib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, status, cmdcore, cmdui, lfprompt

from PyQt4.QtCore import *
from PyQt4.QtGui import *

LABELS = { 'add': (_('Checkmark files to add'), _('Add')),
           'forget': (_('Checkmark files to forget'), _('Forget')),
           'revert': (_('Checkmark files to revert'), _('Revert')),
           'remove': (_('Checkmark files to remove'), _('Remove')),}

ICONS = { 'add': 'hg-add',
           'forget': 'hg-remove',
           'revert': 'hg-revert',
           'remove': 'hg-remove',}

class QuickOpDialog(QDialog):
    """ Dialog for performing quick dirstate operations """
    def __init__(self, repoagent, command, pats, parent):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.pats = pats
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._cmddialog = cmdui.CmdSessionDialog(self)

        # Handle rm alias
        if command == 'rm':
            command = 'remove'
        self.command = command

        self.setWindowTitle(_('%s - hg %s')
                            % (repoagent.displayName(), command))
        self.setWindowIcon(qtlib.geticon(ICONS[command]))

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(5, 5, 5, 0)
        layout.addLayout(toplayout)

        hbox = QHBoxLayout()
        lbl = QLabel(LABELS[command][0])
        slbl = QLabel()
        hbox.addWidget(lbl)
        hbox.addStretch(1)
        hbox.addWidget(slbl)
        self.status_label = slbl
        toplayout.addLayout(hbox)

        types = { 'add'    : 'I?',
                  'forget' : 'MAR!C',
                  'revert' : 'MAR!',
                  'remove' : 'MAR!CI?',
                }
        filetypes = types[self.command]

        checktypes = { 'add'    : '?',
                       'forget' : '',
                       'revert' : 'MAR!',
                       'remove' : '',
                     }
        defcheck = checktypes[self.command]

        opts = {}
        for s, val in status.statusTypes.iteritems():
            opts[val.name] = s in filetypes

        opts['checkall'] = True # pre-check all matching files
        stwidget = status.StatusWidget(repoagent, pats, opts, self,
                                       defcheck=defcheck)
        toplayout.addWidget(stwidget, 1)

        hbox = QHBoxLayout()
        if self.command == 'revert':
            ## no backup checkbox
            chk = QCheckBox(_('Do not save backup files (*.orig)'))
        elif self.command == 'remove':
            ## force checkbox
            chk = QCheckBox(_('Force removal of modified files (--force)'))
        else:
            chk = None
        if chk:
            self.chk = chk
            hbox.addWidget(chk)

        self.statusbar = cmdui.ThgStatusBar(self)
        stwidget.showMessage.connect(self.statusbar.showMessage)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setDefault(True)
        bb.button(BB.Ok).setText(LABELS[command][1])
        hbox.addStretch()
        hbox.addWidget(bb)
        toplayout.addLayout(hbox)
        self.bb = bb

        if self.command == 'add':
            if 'largefiles' in self.repo.extensions():
                self.addLfilesButton = QPushButton(_('Add &Largefiles'))
            else:
                self.addLfilesButton = None
            if self.addLfilesButton:
                self.addLfilesButton.clicked.connect(self.addLfiles)
                bb.addButton(self.addLfilesButton, BB.ActionRole)

        layout.addWidget(self.statusbar)

        s = QSettings()
        stwidget.loadSettings(s, 'quickop')
        self.restoreGeometry(s.value('quickop/geom').toByteArray())
        if hasattr(self, 'chk'):
            if self.command == 'revert':
                self.chk.setChecked(s.value('quickop/nobackup', True).toBool())
            elif self.command == 'remove':
                self.chk.setChecked(
                    s.value('quickop/forceremove', False).toBool())
        self.stwidget = stwidget
        self.stwidget.refreshWctx()
        QShortcut(QKeySequence('Ctrl+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)
        qtlib.newshortcutsforstdkey(QKeySequence.Refresh, self,
                                    self.stwidget.refreshWctx)
        QShortcut(QKeySequence('Escape'), self, self.reject)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _runCommand(self, files, lfiles, opts):
        cmdlines = []
        if files:
            cmdlines.append(hglib.buildcmdargs(self.command, *files, **opts))
        if lfiles:
            assert self.command == 'add'
            lopts = opts.copy()
            lopts['large'] = True
            cmdlines.append(hglib.buildcmdargs(self.command, *lfiles, **lopts))
        self.files = files + lfiles

        ucmdlines = [map(hglib.tounicode, xs) for xs in cmdlines]
        self._cmdsession = sess = self._repoagent.runCommandSequence(ucmdlines,
                                                                     self)
        sess.commandFinished.connect(self.commandFinished)
        sess.progressReceived.connect(self.statusbar.setProgress)
        self._cmddialog.setSession(sess)
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)

    def commandFinished(self, ret):
        self.bb.button(QDialogButtonBox.Ok).setEnabled(True)
        self.statusbar.clearProgress()
        if ret == 0:
            shlib.shell_notify(self.files)
            self.reject()
        else:
            self._cmddialog.show()

    def accept(self):
        cmdopts = {}
        if hasattr(self, 'chk'):
            if self.command == 'revert':
                cmdopts['no_backup'] = self.chk.isChecked()
            elif self.command == 'remove':
                cmdopts['force'] = self.chk.isChecked()
        files = self.stwidget.getChecked()
        if not files:
            qtlib.WarningMsgBox(_('No files selected'),
                                _('No operation to perform'),
                                parent=self)
            return
        if self.command == 'remove':
            self.repo.lfstatus = True
            try:
                repostate = self.repo.status()
            except (EnvironmentError, util.Abort), e:
                qtlib.WarningMsgBox(_('Unable to read repository status'),
                                    hglib.tounicode(str(e)), parent=self)
                return
            finally:
                self.repo.lfstatus = False
            if not self.chk.isChecked():
                modified = repostate[0]
                selmodified = []
                for wfile in files:
                    if wfile in modified:
                        selmodified.append(wfile)
                if selmodified:
                    prompt = qtlib.CustomPrompt(
                        _('Confirm Remove'),
                        _('You have selected one or more files that have been '
                          'modified.  By default, these files will not be '
                          'removed.  What would you like to do?'),
                        self,
                        (_('Remove &Unmodified Files'),
                         _('Remove &All Selected Files'),
                         _('Cancel')),
                        0, 2, selmodified)
                    ret = prompt.run()
                    if ret == 1:
                        cmdopts['force'] = True
                    elif ret == 2:
                        return
            unknown, ignored = repostate[4:6]
            for wfile in files:
                if wfile in unknown or wfile in ignored:
                    try:
                        util.unlink(wfile)
                    except EnvironmentError:
                        pass
                    files.remove(wfile)
        elif self.command == 'add':
            if 'largefiles' in self.repo.extensions():
                self.addWithPrompt(files)
                return
        if files:
            self._runCommand(files, [], cmdopts)
        else:
            self.reject()

    def reject(self):
        if not self._cmdsession.isFinished():
            self._cmdsession.abort()
        elif not self.stwidget.canExit():
            return
        else:
            s = QSettings()
            self.stwidget.saveSettings(s, 'quickop')
            s.setValue('quickop/geom', self.saveGeometry())
            if hasattr(self, 'chk'):
                if self.command == 'revert':
                    s.setValue('quickop/nobackup', self.chk.isChecked())
                elif self.command == 'remove':
                    s.setValue('quickop/forceremove', self.chk.isChecked())
            QDialog.reject(self)

    def addLfiles(self):
        files = self.stwidget.getChecked()
        if not files:
            qtlib.WarningMsgBox(_('No files selected'),
                                _('No operation to perform'),
                                parent=self)
            return
        self._runCommand([], files, {})

    def addWithPrompt(self, files):
        result = lfprompt.promptForLfiles(self, self.repo.ui, self.repo, files)
        if not result:
            return
        files, lfiles = result
        self._runCommand(files, lfiles, {})

class HeadlessQuickop(QObject):
    def __init__(self, repoagent, cmdline):
        QObject.__init__(self)
        self.files = cmdline[1:]
        self._cmddialog = cmdui.CmdSessionDialog()
        sess = repoagent.runCommand(map(hglib.tounicode, cmdline))
        sess.commandFinished.connect(self.commandFinished)
        self._cmddialog.setSession(sess)

    def commandFinished(self, ret):
        if ret == 0:
            shlib.shell_notify(self.files)
            sys.exit(0)
        else:
            self._cmddialog.show()

    # dummy methods to act as QWidget (see run.qtrun)
    def show(self):
        pass
    def raise_(self):
        pass

def run(ui, repoagent, *pats, **opts):
    repo = repoagent.rawRepo()
    pats = hglib.canonpaths(pats)
    command = opts['alias']
    imm = repo.ui.config('tortoisehg', 'immediate', '')
    if opts.get('headless') or command in imm.lower():
        cmdline = [command] + pats
        return HeadlessQuickop(repoagent, cmdline)
    else:
        os.chdir(repo.root)  # for scmutil.match() in StatusThread
        return QuickOpDialog(repoagent, command, pats, None)
