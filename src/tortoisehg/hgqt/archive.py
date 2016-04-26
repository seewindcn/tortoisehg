# archive.py - TortoiseHg's dialog for archiving a repo revision
#
# Copyright 2009 Emmanuel Rosa <goaway1000@gmail.com>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, cmdui, qtlib

WD_PARENT = _('= Working Directory Parent =')

_ARCHIVE_TYPES = [
    {'type': 'files', 'ext': '', 'label': _('Directory of files'),
     'desc': _('Directory of files')},
    {'type': 'tar', 'ext': '.tar', 'label': _('Tar archives'),
     'desc': _('Uncompressed tar archive')},
    {'type': 'tbz2', 'ext': '.tar.bz2', 'label': _('Bzip2 tar archives'),
     'desc': _('Tar archive compressed using bzip2')},
    {'type': 'tgz', 'ext': '.tar.gz', 'label': _('Gzip tar archives'),
     'desc': _('Tar archive compressed using gzip')},
    {'type': 'uzip', 'ext': '.zip', 'label': _('Zip archives'),
     'desc': _('Uncompressed zip archive')},
    {'type': 'zip', 'ext': '.zip', 'label': _('Zip archives'),
     'desc': _('Zip archive compressed using deflate')},
    ]

class ArchiveWidget(cmdui.AbstractCmdWidget):
    """Command widget to archive a particular Mercurial revision"""

    def __init__(self, repoagent, rev=None, parent=None):
        super(ArchiveWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._repoagent = repoagent

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.setLayout(form)

        # content selection
        self.rev_combo = QComboBox()
        self.rev_combo.setEditable(True)
        self.rev_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.files_in_rev_chk = QCheckBox(
                _('Only files modified/created in this revision'))
        self.subrepos_chk = QCheckBox(_('Recurse into subrepositories'))
        form.addRow(_('Revision:'), self.rev_combo)
        form.addRow('', self.files_in_rev_chk)
        form.addRow('', self.subrepos_chk)

        # selecting a destination
        self.dest_edit = QLineEdit()
        self.dest_edit.setMinimumWidth(300)
        self.dest_btn = QPushButton(_('Browse...'))
        self.dest_btn.setAutoDefault(False)
        box = QHBoxLayout()
        box.addWidget(self.dest_edit)
        box.addWidget(self.dest_btn)
        form.addRow(_('Destination path:'), box)

        # archive type selection
        self._typesradios = QButtonGroup(self)
        box = QVBoxLayout()
        for i, spec in enumerate(_ARCHIVE_TYPES):
            w = QRadioButton(spec['desc'], self)
            self._typesradios.addButton(w, i)
            box.addWidget(w)
        form.addRow(_('Archive types:'), box)

        # some extras
        self.hgcmd_txt = QLineEdit()
        self.hgcmd_txt.setReadOnly(True)
        form.addRow(_('Hg command:'), self.hgcmd_txt)

        # set default values
        self.prevtarget = None
        self.rev_combo.addItem(WD_PARENT)
        self.rev_combo.addItems(map(hglib.tounicode,
                                    hglib.namedbranches(self.repo)))
        tags = list(self.repo.tags())
        tags.sort(reverse=True)
        for t in tags:
            self.rev_combo.addItem(hglib.tounicode(t))
        if rev:
            text = hglib.tounicode(str(rev))
            selectindex = self.rev_combo.findText(text)
            if selectindex >= 0:
                self.rev_combo.setCurrentIndex(selectindex)
            else:
                self.rev_combo.insertItem(0, text)
                self.rev_combo.setCurrentIndex(0)
        self.rev_combo.setMaxVisibleItems(self.rev_combo.count())
        self.subrepos_chk.setChecked(self.get_subrepos_present())
        self.dest_edit.setText(hglib.tounicode(self.repo.root))
        self._typesradios.button(0).setChecked(True)
        self.update_path()

        # connecting slots
        self.dest_edit.textEdited.connect(self.compose_command)
        self.rev_combo.editTextChanged.connect(self.rev_combo_changed)
        self.dest_btn.clicked.connect(self.browse_clicked)
        self.files_in_rev_chk.stateChanged.connect(self.compose_command)
        self.subrepos_chk.toggled.connect(self.compose_command)
        self._typesradios.buttonClicked.connect(self.update_path)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def rev_combo_changed(self):
        self.subrepos_chk.setChecked(self.get_subrepos_present())
        self.update_path()

    def browse_clicked(self):
        """Select the destination directory or file"""
        dest = unicode(self.dest_edit.text())
        if not os.path.exists(dest):
            dest = os.path.dirname(dest)
        select = self.get_selected_archive_type()
        FD = QFileDialog
        if select['type'] == 'files':
            caption = _('Select Destination Folder')
            filter = ''
        else:
            caption = _('Select Destination File')
            ext = '*' + select['ext']
            filter = ';;'.join(['%s (%s)' % (select['label'], ext),
                                _('All files (*)')])
        response = FD.getSaveFileName(self, caption, dest, filter, None,
                                      FD.ReadOnly)
        if response:
            self.dest_edit.setText(response)
            self.update_path()

    def get_subrepos_present(self):
        rev = self.get_selected_rev()
        try:
            ctx = self.repo[rev]
        except (error.LookupError, error.RepoLookupError):
            return False
        return '.hgsubstate' in ctx

    def get_selected_rev(self):
        rev = self.rev_combo.currentText()
        if rev == WD_PARENT:
            rev = '.'
        else:
            rev = hglib.fromunicode(rev)
        return rev

    def get_selected_archive_type(self):
        """Return a dictionary describing the selected archive type"""
        return _ARCHIVE_TYPES[self._typesradios.checkedId()]

    def update_path(self):
        def remove_ext(path):
            for ext in ('.tar', '.tar.bz2', '.tar.gz', '.zip'):
                if path.endswith(ext):
                    return path.replace(ext, '')
            return path
        def remove_rev(path):
            l = ''
            for i in xrange(self.rev_combo.count() - 1):
                l += unicode(self.rev_combo.itemText(i))
            revs = [rev[0] for rev in l]
            revs.append(wdrev)
            if not self.prevtarget is None:
                revs.append(self.prevtarget)
            for rev in ['_' + rev for rev in revs]:
                if path.endswith(rev):
                    return path.replace(rev, '')
            return path
        def add_rev(path, rev):
            return '%s_%s' % (path, rev)
        def add_ext(path):
            select = self.get_selected_archive_type()
            if select['type'] != 'files':
                path += select['ext']
            return path
        text = unicode(self.rev_combo.currentText())
        if len(text) == 0:
            self.commandChanged.emit()
            return
        wdrev = str(self.repo['.'].rev())
        if text == WD_PARENT:
            text = wdrev
        else:
            try:
                self.repo[hglib.fromunicode(text)]
            except (error.RepoError, error.LookupError):
                self.commandChanged.emit()
                return
        path = unicode(self.dest_edit.text())
        path = remove_ext(path)
        path = remove_rev(path)
        path = add_rev(path, text)
        path = add_ext(path)
        self.dest_edit.setText(path)
        self.prevtarget = text
        self.compose_command()

    @pyqtSlot()
    def compose_command(self):
        if self.files_in_rev_chk.isChecked():
            incl = 'set:added() or modified()'
        else:
            incl = None
        cmdline = hglib.buildcmdargs('archive', self.dest_edit.text(),
                                     r=hglib.tounicode(self.get_selected_rev()),
                                     S=self.subrepos_chk.isChecked(), I=incl,
                                     t=self.get_selected_archive_type()['type'])
        self.hgcmd_txt.setText('hg ' + hglib.prettifycmdline(cmdline))
        self.commandChanged.emit()
        return cmdline

    def canRunCommand(self):
        rev = self.get_selected_rev()
        if not rev or not self.dest_edit.text():
            return False
        try:
            return rev in self.repo
        except error.LookupError:
            # ambiguous changeid
            return False

    def runCommand(self):
        # verify input
        type = self.get_selected_archive_type()['type']
        dest = unicode(self.dest_edit.text())
        if os.path.exists(dest):
            if type == 'files':
                if os.path.isfile(dest):
                    qtlib.WarningMsgBox(_('Duplicate Name'),
                            _('The destination "%s" already exists as '
                              'a file!') % dest)
                    return cmdcore.nullCmdSession()
                elif os.listdir(dest):
                    if not qtlib.QuestionMsgBox(_('Confirm Overwrite'),
                                 _('The directory "%s" is not empty!\n\n'
                                   'Do you want to overwrite it?') % dest,
                                 parent=self):
                        return cmdcore.nullCmdSession()
            else:
                if os.path.isfile(dest):
                    if not qtlib.QuestionMsgBox(_('Confirm Overwrite'),
                                 _('The file "%s" already exists!\n\n'
                                   'Do you want to overwrite it?') % dest,
                                 parent=self):
                        return cmdcore.nullCmdSession()
                else:
                    qtlib.WarningMsgBox(_('Duplicate Name'),
                          _('The destination "%s" already exists as '
                            'a folder!') % dest)
                    return cmdcore.nullCmdSession()

        cmdline = self.compose_command()
        return self._repoagent.runCommand(cmdline, self)


def createArchiveDialog(repoagent, rev=None, parent=None):
    dlg = cmdui.CmdControlDialog(parent)
    dlg.setWindowTitle(_('Archive - %s') % repoagent.displayName())
    dlg.setWindowIcon(qtlib.geticon('hg-archive'))
    dlg.setObjectName('archive')
    dlg.setRunButtonText(_('&Archive'))
    dlg.setCommandWidget(ArchiveWidget(repoagent, rev, dlg))
    return dlg
