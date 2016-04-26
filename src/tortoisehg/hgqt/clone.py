# clone.py - Clone dialog for TortoiseHg
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import cmdutil, commands, hg

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib

def _startrev_available():
    entry = cmdutil.findcmd('clone', commands.table)[1]
    longopts = set(e[1] for e in entry[1])
    return 'startrev' in longopts

def _suggesteddest(src, basedest):
    if '://' in basedest:
        return basedest
    try:
        if not os.listdir(basedest):
            # premade empty directory, just use it
            return basedest
    except OSError:
        # guess existing base assuming "{basedest}/{name}"
        basedest = os.path.dirname(basedest)
    name = hglib.tounicode(hg.defaultdest(hglib.fromunicode(src, 'replace')))
    if not name or name == '.':
        return basedest
    newdest = os.path.join(basedest, name)
    if os.path.exists(newdest):
        newdest += '-clone'
    return newdest


class CloneWidget(cmdui.AbstractCmdWidget):

    def __init__(self, ui, cmdagent, args=None, opts={}, parent=None):
        super(CloneWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cmdagent = cmdagent
        self.ui = ui

        dest = src = os.getcwd()
        if args:
            if len(args) > 1:
                src = args[0]
                dest = args[1]
            else:
                src = args[0]
        udest = hglib.tounicode(dest)
        usrc = hglib.tounicode(src)

        ## main layout
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.setLayout(form)

        ### source combo and button
        self.src_combo = QComboBox()
        self.src_combo.setEditable(True)
        self.src_combo.setMinimumContentsLength(30)  # cut long path
        self.src_btn = QPushButton(_('Browse...'))
        self.src_btn.setAutoDefault(False)
        self.src_btn.clicked.connect(self._browseSource)
        srcbox = QHBoxLayout()
        srcbox.addWidget(self.src_combo, 1)
        srcbox.addWidget(self.src_btn)
        form.addRow(_('Source:'), srcbox)

        ### destination combo and button
        self.dest_combo = QComboBox()
        self.dest_combo.setEditable(True)
        self.dest_combo.setMinimumContentsLength(30)  # cut long path
        self.dest_btn = QPushButton(_('Browse...'))
        self.dest_btn.setAutoDefault(False)
        self.dest_btn.clicked.connect(self._browseDestination)
        destbox = QHBoxLayout()
        destbox.addWidget(self.dest_combo, 1)
        destbox.addWidget(self.dest_btn)
        form.addRow(_('Destination:'), destbox)

        for combo in (self.src_combo, self.dest_combo):
            qtlib.allowCaseChangingInput(combo)
            combo.installEventFilter(qtlib.BadCompletionBlocker(combo))

        self.setSource(usrc)
        self.setDestination(udest)

        ### options
        expander = qtlib.ExpanderLabel(_('Options'), False)
        optwidget = QWidget(self)
        expander.expanded.connect(optwidget.setVisible)
        optbox = QVBoxLayout()
        optbox.setContentsMargins(0, 0, 0, 0)
        optbox.setSpacing(6)
        optwidget.setLayout(optbox)
        form.addRow(expander, optwidget)

        def chktext(chklabel, btnlabel=None, btnslot=None, stretch=None):
            hbox = QHBoxLayout()
            hbox.setSpacing(0)
            optbox.addLayout(hbox)
            chk = QCheckBox(chklabel)
            text = QLineEdit(enabled=False)
            chk.toggled.connect(text.setEnabled)
            chk.toggled.connect(text.setFocus)
            hbox.addWidget(chk)
            hbox.addWidget(text)
            if stretch is not None:
                hbox.addStretch(stretch)
            if btnlabel:
                btn = QPushButton(btnlabel)
                btn.setEnabled(False)
                btn.setAutoDefault(False)
                btn.clicked.connect(btnslot)
                chk.toggled.connect(btn.setEnabled)
                hbox.addSpacing(6)
                hbox.addWidget(btn)
                return chk, text, btn
            else:
                return chk, text

        self.rev_chk, self.rev_text = chktext(_('Clone to revision:'),
                                              stretch=40)
        self.rev_text.setToolTip(_('A revision identifier, bookmark, tag or '
                                   'branch name'))

        self.noupdate_chk = QCheckBox(_('Do not update the new working directory'))
        self.pproto_chk = QCheckBox(_('Use pull protocol to copy metadata'))
        self.uncomp_chk = QCheckBox(_('Use uncompressed transfer'))
        optbox.addWidget(self.noupdate_chk)
        optbox.addWidget(self.pproto_chk)
        optbox.addWidget(self.uncomp_chk)

        self.qclone_chk, self.qclone_txt, self.qclone_btn = \
                chktext(_('Include patch queue'), btnlabel=_('Browse...'),
                        btnslot=self._browsePatchQueue)

        self.proxy_chk = QCheckBox(_('Use proxy server'))
        optbox.addWidget(self.proxy_chk)
        useproxy = bool(self.ui.config('http_proxy', 'host'))
        self.proxy_chk.setEnabled(useproxy)
        self.proxy_chk.setChecked(useproxy)

        self.insecure_chk = QCheckBox(_('Do not verify host certificate'))
        optbox.addWidget(self.insecure_chk)
        self.insecure_chk.setEnabled(False)

        self.remote_chk, self.remote_text = chktext(_('Remote command:'))

        # allow to specify start revision for p4 & svn repos.
        self.startrev_chk, self.startrev_text = chktext(_('Start revision:'),
                                                        stretch=40)

        self.hgcmd_txt = QLineEdit()
        self.hgcmd_txt.setReadOnly(True)
        form.addRow(_('Hg command:'), self.hgcmd_txt)

        # connect extra signals
        self.src_combo.editTextChanged.connect(self._onSourceChanged)
        self.src_combo.currentIndexChanged.connect(self._suggestDestination)
        t = QTimer(self, interval=200, singleShot=True)
        t.timeout.connect(self._suggestDestination)
        le = self.src_combo.lineEdit()
        le.editingFinished.connect(t.stop)  # only while it has focus
        le.textEdited.connect(t.start)
        self.dest_combo.editTextChanged.connect(self._composeCommand)
        self.rev_chk.toggled.connect(self._composeCommand)
        self.rev_text.textChanged.connect(self._composeCommand)
        self.noupdate_chk.toggled.connect(self._composeCommand)
        self.pproto_chk.toggled.connect(self._composeCommand)
        self.uncomp_chk.toggled.connect(self._composeCommand)
        self.qclone_chk.toggled.connect(self._composeCommand)
        self.qclone_txt.textChanged.connect(self._composeCommand)
        self.proxy_chk.toggled.connect(self._composeCommand)
        self.insecure_chk.toggled.connect(self._composeCommand)
        self.remote_chk.toggled.connect(self._composeCommand)
        self.remote_text.textChanged.connect(self._composeCommand)
        self.startrev_chk.toggled.connect(self._composeCommand)

        # prepare to show
        optwidget.hide()

        rev = opts.get('rev')
        if rev:
            self.rev_chk.setChecked(True)
            self.rev_text.setText(hglib.tounicode(rev))
        self.noupdate_chk.setChecked(bool(opts.get('noupdate')))
        self.pproto_chk.setChecked(bool(opts.get('pull')))
        self.uncomp_chk.setChecked(bool(opts.get('uncompressed')))
        self.startrev_chk.setVisible(_startrev_available())
        self.startrev_text.setVisible(_startrev_available())

        self._composeCommand()

    def readSettings(self, qs):
        for key, combo in [('source', self.src_combo),
                           ('dest', self.dest_combo)]:
            # addItems() can overwrite temporary edit text
            edittext = combo.currentText()
            combo.blockSignals(True)
            combo.addItems(qs.value(key).toStringList())
            combo.setCurrentIndex(combo.findText(edittext))
            combo.setEditText(edittext)
            combo.blockSignals(False)

        self.src_combo.lineEdit().selectAll()

    def writeSettings(self, qs):
        for key, combo in [('source', self.src_combo),
                           ('dest', self.dest_combo)]:
            l = [combo.currentText()]
            l.extend(combo.itemText(i) for i in xrange(combo.count())
                     if combo.itemText(i) != combo.currentText())
            qs.setValue(key, l[:10])

    def source(self):
        return unicode(self.src_combo.currentText()).strip()

    def setSource(self, url):
        self.src_combo.setCurrentIndex(self.src_combo.findText(url))
        self.src_combo.setEditText(url)

    def destination(self):
        return unicode(self.dest_combo.currentText()).strip()

    def setDestination(self, url):
        self.dest_combo.setCurrentIndex(self.dest_combo.findText(url))
        self.dest_combo.setEditText(url)

    @pyqtSlot()
    def _suggestDestination(self):
        self.setDestination(_suggesteddest(self.source(), self.destination()))

    @pyqtSlot()
    def _composeCommand(self):
        opts = {
            'noupdate': self.noupdate_chk.isChecked(),
            'uncompressed': self.uncomp_chk.isChecked(),
            'pull': self.pproto_chk.isChecked(),
            'verbose': True,
            }
        if (self.ui.config('http_proxy', 'host')
            and not self.proxy_chk.isChecked()):
            opts['config'] = 'http_proxy.host='
        if self.remote_chk.isChecked():
            opts['remotecmd'] = unicode(self.remote_text.text()).strip() or None
        if self.rev_chk.isChecked():
            opts['rev'] = unicode(self.rev_text.text()).strip() or None
        if self.startrev_chk.isChecked():
            opts['startrev'] = (unicode(self.startrev_text.text()).strip()
                                or None)

        src = self.source()
        dest = self.destination()
        if src.startswith('https://'):
            opts['insecure'] = self.insecure_chk.isChecked()

        if self.qclone_chk.isChecked():
            name = 'qclone'
            opts['patches'] = unicode(self.qclone_txt.text()).strip() or None
        else:
            name = 'clone'

        cmdline = hglib.buildcmdargs(name, src, dest or None, **opts)
        self.hgcmd_txt.setText('hg ' + hglib.prettifycmdline(cmdline))
        self.commandChanged.emit()
        return cmdline

    def canRunCommand(self):
        src, dest = self.source(), self.destination()
        return bool(src and dest and src != dest)

    def runCommand(self):
        cmdline = self._composeCommand()
        return self._cmdagent.runCommand(cmdline, self)

    @pyqtSlot()
    def _browseSource(self):
        FD = QFileDialog
        caption = _("Select source repository")
        path = FD.getExistingDirectory(self, caption, \
            self.src_combo.currentText(), QFileDialog.ShowDirsOnly)
        if path:
            self.src_combo.setEditText(QDir.toNativeSeparators(path))
            self._suggestDestination()
            self.dest_combo.setFocus()

    @pyqtSlot()
    def _browseDestination(self):
        FD = QFileDialog
        caption = _("Select destination repository")
        path = FD.getExistingDirectory(self, caption, \
            self.dest_combo.currentText(), QFileDialog.ShowDirsOnly)
        if path:
            self.dest_combo.setEditText(QDir.toNativeSeparators(path))
            self._suggestDestination()  # in case existing dir is selected
            self.dest_combo.setFocus()

    @pyqtSlot()
    def _browsePatchQueue(self):
        FD = QFileDialog
        caption = _("Select patch folder")
        upatchroot = os.path.join(unicode(self.src_combo.currentText()), '.hg')
        upath = FD.getExistingDirectory(self, caption, upatchroot,
                                        QFileDialog.ShowDirsOnly)
        if upath:
            self.qclone_txt.setText(QDir.toNativeSeparators(upath))
            self.qclone_txt.setFocus()

    @pyqtSlot()
    def _onSourceChanged(self):
        self.insecure_chk.setEnabled(self.source().startswith('https://'))
        self._composeCommand()


class CloneDialog(cmdui.CmdControlDialog):

    clonedRepository = pyqtSignal(str, str)

    def __init__(self, ui, args=None, opts={}, parent=None):
        super(CloneDialog, self).__init__(parent)

        cwd = os.getcwd()
        ucwd = hglib.tounicode(cwd)

        self.setWindowTitle(_('Clone - %s') % ucwd)
        self.setWindowIcon(qtlib.geticon('hg-clone'))
        self.setObjectName('clone')
        self.setRunButtonText(_('&Clone'))
        self._cmdagent = cmdagent = cmdcore.CmdAgent(ui, self)
        cmdagent.serviceStopped.connect(self.reject)
        self.setCommandWidget(CloneWidget(ui, cmdagent, args, opts, self))
        self.commandFinished.connect(self._emitCloned)

    def source(self):
        return self.commandWidget().source()

    def setSource(self, url):
        assert self.isCommandFinished()
        self.commandWidget().setSource(url)

    def destination(self):
        return self.commandWidget().destination()

    def setDestination(self, url):
        assert self.isCommandFinished()
        self.commandWidget().setDestination(url)

    @pyqtSlot(int)
    def _emitCloned(self, ret):
        if ret == 0:
            self.clonedRepository.emit(self.destination(), self.source())

    def done(self, r):
        if self._cmdagent.isServiceRunning():
            self._cmdagent.stopService()
            return  # postponed until serviceStopped
        super(CloneDialog, self).done(r)
