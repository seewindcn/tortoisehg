# hgemail.py - TortoiseHg's dialog for sending patches via email
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, tempfile, re
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from mercurial import error, util
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, lexers, qtlib
from tortoisehg.hgqt.hgemail_ui import Ui_EmailDialog

class EmailDialog(QDialog):
    """Dialog for sending patches via email"""

    def __init__(self, repoagent, revs, parent=None, outgoing=False,
                 outgoingrevs=None):
        """Create EmailDialog for the given repo and revs

        :revs: List of revisions to be sent.
        :outgoing: Enable outgoing bundle support. You also need to set
                   outgoing revisions to `revs`.
        :outgoingrevs: Target revision of outgoing bundle.
                       (Passed as `hg email --bundle --rev {rev}`)
        """
        super(EmailDialog, self).__init__(parent)
        self.setWindowFlags(Qt.Window)
        self._repoagent = repoagent
        self._cmdsession = cmdcore.nullCmdSession()
        self._outgoing = outgoing
        self._outgoingrevs = outgoingrevs or []

        self._qui = Ui_EmailDialog()
        self._qui.setupUi(self)

        self._initchangesets(revs)
        self._initpreviewtab()
        self._initenvelopebox()
        self._qui.bundle_radio.toggled.connect(self._updateforms)
        self._qui.attach_check.toggled.connect(self._updateattachmodes)
        self._qui.inline_check.toggled.connect(self._updateattachmodes)
        self._initintrobox()
        self._readhistory()
        self._filldefaults()
        self._updateforms()
        self._updateattachmodes()
        self._readsettings()
        QShortcut(QKeySequence('CTRL+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)

    def closeEvent(self, event):
        self._writesettings()
        super(EmailDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('email/geom').toByteArray())
        self._qui.intro_changesets_splitter.restoreState(
            s.value('email/intro_changesets_splitter').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('email/geom', self.saveGeometry())
        s.setValue('email/intro_changesets_splitter',
                   self._qui.intro_changesets_splitter.saveState())

    def _readhistory(self):
        s = QSettings()
        for k in ('to', 'cc', 'from', 'flag', 'subject'):
            w = getattr(self._qui, '%s_edit' % k)
            w.addItems(s.value('email/%s_history' % k).toStringList())
            w.setCurrentIndex(-1)  # unselect
        for k in ('body', 'attach', 'inline', 'diffstat'):
            w = getattr(self._qui, '%s_check' % k)
            w.setChecked(s.value('email/%s' % k).toBool())

    def _writehistory(self):
        def itercombo(w):
            if w.currentText():
                yield w.currentText()
            for i in xrange(w.count()):
                if w.itemText(i) != w.currentText():
                    yield w.itemText(i)

        s = QSettings()
        for k in ('to', 'cc', 'from', 'flag', 'subject'):
            w = getattr(self._qui, '%s_edit' % k)
            s.setValue('email/%s_history' % k, list(itercombo(w))[:10])
        for k in ('body', 'attach', 'inline', 'diffstat'):
            w = getattr(self._qui, '%s_check' % k)
            s.setValue('email/%s' % k, w.isChecked())

    def _initchangesets(self, revs):
        self._changesets = _ChangesetsModel(self._repo,
                                            revs=revs or list(self._repo),
                                            selectedrevs=revs,
                                            parent=self)
        self._changesets.dataChanged.connect(self._updateforms)
        self._qui.changesets_view.setModel(self._changesets)

    @property
    def _repo(self):
        return self._repoagent.rawRepo()

    @property
    def _ui(self):
        return self._repo.ui

    @property
    def _revs(self):
        """Returns list of revisions to be sent"""
        return self._changesets.selectedrevs

    def _filldefaults(self):
        """Fill form by default values"""
        def getfromaddr(ui):
            """Get sender address in the same manner as patchbomb"""
            addr = ui.config('email', 'from') or ui.config('patchbomb', 'from')
            if addr:
                return addr
            try:
                return ui.username()
            except error.Abort:
                return ''

        self._qui.to_edit.setEditText(
            hglib.tounicode(self._ui.config('email', 'to', '')))
        self._qui.cc_edit.setEditText(
            hglib.tounicode(self._ui.config('email', 'cc', '')))
        self._qui.from_edit.setEditText(hglib.tounicode(getfromaddr(self._ui)))

        self.setdiffformat(self._ui.configbool('diff', 'git') and 'git' or 'hg')

    def setdiffformat(self, format):
        """Set diff format, 'hg', 'git' or 'plain'"""
        try:
            radio = getattr(self._qui, '%spatch_radio' % format)
        except AttributeError:
            raise ValueError('unknown diff format: %r' % format)

        radio.setChecked(True)

    def getdiffformat(self):
        """Selected diff format"""
        for e in self._qui.patch_frame.children():
            m = re.match(r'(\w+)patch_radio', str(e.objectName()))
            if m and e.isChecked():
                return m.group(1)

        return 'hg'

    def getextraopts(self):
        """Dict of extra options"""
        opts = {}
        for e in self._qui.extra_frame.children():
            m = re.match(r'(\w+)_check', str(e.objectName()))
            if m:
                opts[m.group(1)] = e.isChecked()

        return opts

    def _patchbombopts(self, **opts):
        """Generate opts for patchbomb by form values"""
        def headertext(s):
            # QLineEdit may contain newline character
            return re.sub(r'\s', ' ', unicode(s))

        opts['to'] = headertext(self._qui.to_edit.currentText())
        opts['cc'] = headertext(self._qui.cc_edit.currentText())
        opts['from'] = headertext(self._qui.from_edit.currentText())
        opts['in_reply_to'] = headertext(self._qui.inreplyto_edit.text())
        opts['flag'] = headertext(self._qui.flag_edit.currentText())

        if self._qui.bundle_radio.isChecked():
            assert self._outgoing  # only outgoing bundle is supported
            opts['rev'] = hglib.compactrevs(self._outgoingrevs)
            opts['bundle'] = True
        else:
            opts['rev'] = hglib.compactrevs(self._revs)

        fmt = self.getdiffformat()
        if fmt != 'hg':
            opts[fmt] = True

        opts.update(self.getextraopts())

        def writetempfile(s):
            fd, fname = tempfile.mkstemp(prefix='thg_emaildesc_',
                                         dir=qtlib.gettempdir())
            try:
                os.write(fd, s)
                return hglib.tounicode(fname)
            finally:
                os.close(fd)

        opts['intro'] = self._qui.writeintro_check.isChecked()
        if opts['intro']:
            opts['subject'] = headertext(self._qui.subject_edit.currentText())
            opts['desc'] = writetempfile(
                hglib.fromunicode(self._qui.body_edit.toPlainText()))

        # The email dialog is available no matter if patchbomb extension isn't
        # enabled.  The extension name makes it unlikely first-time users
        # would discover that Mercurial ships with a functioning patch MTA.
        # Since patchbomb doesn't monkey patch any Mercurial code, it's safe
        # to enable it on demand.
        opts['config'] = 'extensions.patchbomb='

        return opts

    def _isvalid(self):
        """Filled all required values?"""
        for e in ('to_edit', 'from_edit'):
            if not getattr(self._qui, e).currentText():
                return False

        if (self._qui.writeintro_check.isChecked()
            and not self._qui.subject_edit.currentText()):
            return False

        if not self._revs:
            return False

        return True

    @pyqtSlot()
    def _updateforms(self):
        """Update availability of form widgets"""
        valid = self._isvalid()
        self._qui.send_button.setEnabled(valid)
        self._qui.main_tabs.setTabEnabled(self._previewtabindex(), valid)
        self._qui.writeintro_check.setEnabled(not self._introrequired())

        self._qui.bundle_radio.setEnabled(
            self._outgoing and self._changesets.isselectedall())
        self._changesets.setReadOnly(self._qui.bundle_radio.isChecked())
        if self._qui.bundle_radio.isChecked():
            # workaround to disable preview for outgoing bundle because it
            # may freeze main thread
            self._qui.main_tabs.setTabEnabled(self._previewtabindex(), False)

        if self._introrequired():
            self._qui.writeintro_check.setChecked(True)

    @qtlib.senderSafeSlot()
    def _updateattachmodes(self):
        """Update checkboxes to select the embedding style of the patch"""
        attachmodes = [self._qui.attach_check, self._qui.inline_check]
        body = self._qui.body_check

        # --attach and --inline are exclusive
        if self.sender() in attachmodes and self.sender().isChecked():
            for w in attachmodes:
                if w is not self.sender():
                    w.setChecked(False)

        # --body is mandatory if no attach modes are specified
        body.setEnabled(any(w.isChecked() for w in attachmodes))
        if not body.isEnabled():
            body.setChecked(True)

    def _initenvelopebox(self):
        for e in ('to_edit', 'from_edit'):
            getattr(self._qui, e).editTextChanged.connect(self._updateforms)

    def accept(self):
        opts = self._patchbombopts()
        cmdline = hglib.buildcmdargs('email', **opts)
        cmd = cmdui.CmdSessionDialog(self)
        cmd.setWindowTitle(_('Sending Email'))
        cmd.setLogVisible(False)
        uih = cmdui.PasswordUiHandler(cmd)  # skip "intro" and "diffstat" prompt
        cmd.setSession(self._repoagent.runCommand(cmdline, uih))
        if cmd.exec_() == 0:
            self._writehistory()

    def _initintrobox(self):
        self._qui.intro_box.hide()  # hidden by default
        self._qui.subject_edit.editTextChanged.connect(self._updateforms)
        self._qui.writeintro_check.toggled.connect(self._updateforms)

    def _introrequired(self):
        """Is intro message required?"""
        return self._qui.bundle_radio.isChecked()

    def _initpreviewtab(self):
        def initqsci(w):
            w.setUtf8(True)
            w.setReadOnly(True)
            w.setMarginWidth(1, 0)  # hide area for line numbers
            self.lexer = lex = lexers.difflexer(self)
            fh = qtlib.getfont('fontdiff')
            fh.changed.connect(self.forwardFont)
            lex.setFont(fh.font())
            w.setLexer(lex)
            # TODO: better way to setup diff lexer

        initqsci(self._qui.preview_edit)

        self._qui.main_tabs.currentChanged.connect(self._refreshpreviewtab)
        self._refreshpreviewtab(self._qui.main_tabs.currentIndex())

    def forwardFont(self, font):
        if self.lexer:
            self.lexer.setFont(font)

    @pyqtSlot(int)
    def _refreshpreviewtab(self, index):
        """Generate preview text if current tab is preview"""
        if self._previewtabindex() != index:
            return

        self._qui.preview_edit.clear()
        opts = self._patchbombopts(test=True)
        cmdline = hglib.buildcmdargs('email', **opts)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._updatepreview)

    @pyqtSlot()
    def _updatepreview(self):
        msg = hglib.tounicode(str(self._cmdsession.readAll()))
        self._qui.preview_edit.append(msg)

    def _previewtabindex(self):
        """Index of preview tab"""
        return self._qui.main_tabs.indexOf(self._qui.preview_tab)

    @pyqtSlot()
    def on_settings_button_clicked(self):
        from tortoisehg.hgqt import settings
        if settings.SettingsDialog(parent=self, focus='email.from').exec_():
            # not use repo.configChanged because it can clobber user input
            # accidentally.
            self._repo.invalidateui()  # force reloading config immediately
            self._filldefaults()

    @pyqtSlot()
    def on_selectall_button_clicked(self):
        self._changesets.selectAll()

    @pyqtSlot()
    def on_selectnone_button_clicked(self):
        self._changesets.selectNone()


# TODO: use component of log viewer?
class _ChangesetsModel(QAbstractTableModel):
    _COLUMNS = [('rev', lambda ctx: '%d:%s' % (ctx.rev(), ctx)),
                ('author', lambda ctx: hglib.username(ctx.user())),
                ('date', lambda ctx: util.shortdate(ctx.date())),
                ('description', lambda ctx: ctx.longsummary())]

    def __init__(self, repo, revs, selectedrevs, parent=None):
        super(_ChangesetsModel, self).__init__(parent)
        self._repo = repo
        self._revs = list(reversed(sorted(revs)))
        self._selectedrevs = set(selectedrevs)
        self._readonly = False

    @property
    def revs(self):
        return self._revs

    @property
    def selectedrevs(self):
        """Return the list of selected revisions"""
        return list(sorted(self._selectedrevs))

    def isselectedall(self):
        return len(self._revs) == len(self._selectedrevs)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()

        rev = self._revs[index.row()]
        if index.column() == 0 and role == Qt.CheckStateRole:
            return rev in self._selectedrevs and Qt.Checked or Qt.Unchecked
        if role == Qt.DisplayRole:
            coldata = self._COLUMNS[index.column()][1]
            return QVariant(hglib.tounicode(coldata(self._repo.changectx(rev))))

        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or self._readonly:
            return False

        rev = self._revs[index.row()]
        if index.column() == 0 and role == Qt.CheckStateRole:
            origvalue = rev in self._selectedrevs
            if value == Qt.Checked:
                self._selectedrevs.add(rev)
            else:
                self._selectedrevs.remove(rev)

            if origvalue != (rev in self._selectedrevs):
                self.dataChanged.emit(index, index)

            return True

        return False

    def setReadOnly(self, readonly):
        self._readonly = readonly

    def flags(self, index):
        v = super(_ChangesetsModel, self).flags(index)
        if index.column() == 0 and not self._readonly:
            return Qt.ItemIsUserCheckable | v
        else:
            return v

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._revs)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._COLUMNS)

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()

        return QVariant(self._COLUMNS[section][0].capitalize())

    def selectAll(self):
        self._selectedrevs = set(self._revs)
        self.updateAll()

    def selectNone(self):
        self._selectedrevs = set()
        self.updateAll()

    def updateAll(self):
        first = self.createIndex(0, 0)
        last = self.createIndex(len(self._revs) - 1, 0)
        self.dataChanged.emit(first, last)
