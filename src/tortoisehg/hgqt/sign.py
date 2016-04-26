# sign.py - Sign dialog for TortoiseHg
#
# Copyright 2013 Elson Wei <elson.wei@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib

class SignDialog(QDialog):

    def __init__(self, repoagent, rev='tip', parent=None, opts={}):
        super(SignDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() &
                            ~Qt.WindowContextHelpButtonHint)

        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self.rev = rev

        # base layout box
        base = QVBoxLayout()
        base.setSpacing(0)
        base.setContentsMargins(*(0,)*4)
        base.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setLayout(base)

        ## main layout grid
        formwidget = QWidget(self)
        formwidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form = QFormLayout(fieldGrowthPolicy=QFormLayout.AllNonFixedFieldsGrow)
        formwidget.setLayout(form)
        base.addWidget(formwidget)

        repo = repoagent.rawRepo()
        form.addRow(_('Revision:'), QLabel('%s (%s)' % (rev, repo[rev])))

        ### key line edit
        self.keyLineEdit = QLineEdit()
        form.addRow(_('Key:'), self.keyLineEdit)

        ### options
        expander = qtlib.ExpanderLabel(_('Options'), False)
        expander.expanded.connect(self.show_options)
        optbox = QVBoxLayout()
        optbox.setSpacing(6)
        form.addRow(expander, optbox)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        optbox.addLayout(hbox)

        self.localCheckBox = QCheckBox(_('Local sign'))
        self.localCheckBox.toggled.connect(self.updateStates)
        optbox.addWidget(self.localCheckBox)

        self.replaceCheckBox = QCheckBox(_('Sign even if the sigfile is '
                                           'modified (-f/--force)'))
        self.replaceCheckBox.toggled.connect(self.updateStates)
        optbox.addWidget(self.replaceCheckBox)

        self.nocommitCheckBox = QCheckBox(_('No commit'))
        self.nocommitCheckBox.toggled.connect(self.updateStates)
        optbox.addWidget(self.nocommitCheckBox)

        self.customCheckBox = QCheckBox(_('Use custom commit message:'))
        self.customCheckBox.toggled.connect(self.customMessageToggle)
        optbox.addWidget(self.customCheckBox)

        self.customTextLineEdit = QLineEdit()
        optbox.addWidget(self.customTextLineEdit)

        ## bottom buttons
        BB = QDialogButtonBox
        bbox = QDialogButtonBox()
        self.signBtn = bbox.addButton(_('&Sign'), BB.ActionRole)
        bbox.addButton(BB.Close)
        bbox.rejected.connect(self.reject)
        form.addRow(bbox)

        self.signBtn.clicked.connect(self.onSign)

        ## horizontal separator
        self.sep = QFrame()
        self.sep.setFrameShadow(QFrame.Sunken)
        self.sep.setFrameShape(QFrame.HLine)
        self.layout().addWidget(self.sep)

        ## status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        self.layout().addWidget(self.status)

        # prepare to show
        self.setWindowTitle(_('Sign - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-sign'))

        self.clear_status()
        key = opts.get('key', '')
        if not key:
            key = repo.ui.config("gpg", "key", '')
        self.keyLineEdit.setText(hglib.tounicode(key))
        self.replaceCheckBox.setChecked(bool(opts.get('force')))
        self.localCheckBox.setChecked(bool(opts.get('local')))
        self.nocommitCheckBox.setChecked(bool(opts.get('no_commit')))
        msg = opts.get('message', '')
        self.customTextLineEdit.setText(hglib.tounicode(msg))
        if msg:
            self.customCheckBox.setChecked(True)
            self.customMessageToggle(True)
        else:
            self.customCheckBox.setChecked(False)
            self.customMessageToggle(False)
        self.keyLineEdit.setFocus()

        expanded = any([self.replaceCheckBox.isChecked(),
                        self.localCheckBox.isChecked(),
                        self.nocommitCheckBox.isChecked(),
                        self.customCheckBox.isChecked()])
        expander.set_expanded(expanded)
        self.show_options(expanded)

        self.updateStates()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def show_options(self, visible):
        self.localCheckBox.setVisible(visible)
        self.replaceCheckBox.setVisible(visible)
        self.nocommitCheckBox.setVisible(visible)
        self.customCheckBox.setVisible(visible)
        self.customTextLineEdit.setVisible(visible)

    def commandFinished(self, ret):
        if ret == 0:
            self.set_status(_("Signature has been added"))
        else:
            self.set_status(self._cmdsession.errorString(), False)

    @pyqtSlot()
    def updateStates(self):
        nocommit = self.nocommitCheckBox.isChecked()
        custom = self.customCheckBox.isChecked()
        self.customCheckBox.setEnabled(not nocommit)
        self.customTextLineEdit.setEnabled(not nocommit and custom)

    def onSign(self):
        if not self._cmdsession.isFinished():
            self.set_status(_('Repository command still running'), False)
            return

        opts = {
            'key': self.keyLineEdit.text() or None,
            'local': self.localCheckBox.isChecked(),
            'force': self.replaceCheckBox.isChecked(),
            'no_commit': self.nocommitCheckBox.isChecked(),
            }
        if self.customCheckBox.isChecked() and not opts['no_commit']:
            opts['message'] = self.customTextLineEdit.text() or None

        user = qtlib.getCurrentUsername(self, self.repo)
        if not user:
            return
        opts['user'] = hglib.tounicode(user)

        cmdline = hglib.buildcmdargs('sign', self.rev, **opts)
        sess = self._repoagent.runCommand(cmdline, self)
        self._cmdsession = sess
        sess.commandFinished.connect(self.commandFinished)

    def customMessageToggle(self, checked):
        self.customTextLineEdit.setEnabled(checked)
        if checked:
            self.customTextLineEdit.setFocus()

    def set_status(self, text, icon=None):
        self.status.setVisible(True)
        self.sep.setVisible(True)
        self.status.set_status(text, icon)

    def clear_status(self):
        self.status.setHidden(True)
        self.sep.setHidden(True)
