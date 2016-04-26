# rupdate.py - Remote Update dialog for TortoiseHg
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2011 Ryan Seto <mr.werewolf@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

"""Remote Update dialog for TortoiseHg

This dialog lets users update a remote ssh repository.

Requires a copy of the rupdate plugin found at:
http://bitbucket.org/MrWerewolf/rupdate

Also, enable the plugin with the following in mercurial.ini::

    [extensions]
    rupdate = /path/to/rupdate
"""

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdui, csinfo, qtlib

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class RemoteUpdateWidget(cmdui.AbstractCmdWidget):

    def __init__(self, repoagent, rev=None, parent=None):
        super(RemoteUpdateWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._repoagent = repoagent
        repo = repoagent.rawRepo()

        ## main layout
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.setLayout(form)

        ### target path combo
        self.path_combo = pcombo = QComboBox()
        pcombo.setEditable(True)
        pcombo.addItems([hglib.tounicode(path)
                         for _name, path in repo.ui.configitems('paths')])
        form.addRow(_('Location:'), pcombo)

        ### target revision combo
        self.rev_combo = combo = QComboBox()
        combo.setEditable(True)
        form.addRow(_('Update to:'), combo)

        combo.addItems(map(hglib.tounicode, hglib.namedbranches(repo)))
        tags = list(self.repo.tags()) + repo._bookmarks.keys()
        tags.sort(reverse=True)
        combo.addItems(map(hglib.tounicode, tags))

        if rev is None:
            selecturev = hglib.tounicode(self.repo.dirstate.branch())
        else:
            selecturev = hglib.tounicode(str(rev))
        selectindex = combo.findText(selecturev)
        if selectindex >= 0:
            combo.setCurrentIndex(selectindex)
        else:
            combo.setEditText(selecturev)

        ### target revision info
        items = ('%(rev)s', ' %(branch)s', ' %(tags)s', '<br />%(summary)s')
        style = csinfo.labelstyle(contents=items, width=350, selectable=True)
        factory = csinfo.factory(self.repo, style=style)
        self.target_info = factory()
        form.addRow(_('Target:'), self.target_info)

        ### Options
        self.optbox = QVBoxLayout()
        self.optbox.setSpacing(6)
        self.optexpander = expander = qtlib.ExpanderLabel(_('Options:'), False)
        expander.expanded.connect(self.show_options)
        form.addRow(expander, self.optbox)

        self.discard_chk = QCheckBox(_('Discard remote changes, no backup '
                                       '(-C/--clean)'))
        self.push_chk = QCheckBox(_('Perform a push before updating'
                                        ' (-p/--push)'))
        self.newbranch_chk = QCheckBox(_('Allow pushing new branches'
                                        ' (--new-branch)'))
        self.force_chk = QCheckBox(_('Force push to remote location'
                                        ' (-f/--force)'))
        self.optbox.addWidget(self.discard_chk)
        self.optbox.addWidget(self.push_chk)
        self.optbox.addWidget(self.newbranch_chk)
        self.optbox.addWidget(self.force_chk)

        # signal handlers
        self.rev_combo.editTextChanged.connect(self.update_info)

        # prepare to show
        self.push_chk.setHidden(True)
        self.newbranch_chk.setHidden(True)
        self.force_chk.setHidden(True)
        self.update_info()

    def readSettings(self, qs):
        self.push_chk.setChecked(qs.value('push').toBool())
        self.newbranch_chk.setChecked(qs.value('newbranch').toBool())

        self.optexpander.set_expanded(self.push_chk.isChecked()
                                      or self.newbranch_chk.isChecked()
                                      or self.force_chk.isChecked())

    def writeSettings(self, qs):
        qs.setValue('push', self.push_chk.isChecked())
        qs.setValue('newbranch', self.newbranch_chk.isChecked())

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    @pyqtSlot()
    def update_info(self):
        new_rev = hglib.fromunicode(self.rev_combo.currentText())
        if new_rev == 'null':
            self.target_info.setText(_('remove working directory'))
            self.commandChanged.emit()
            return
        try:
            self.target_info.update(self.repo[new_rev])
        except (error.LookupError, error.RepoLookupError, error.RepoError):
            self.target_info.setText(_('unknown revision!'))
        self.commandChanged.emit()

    def canRunCommand(self):
        rev = hglib.fromunicode(self.rev_combo.currentText())
        try:
            return rev in self.repo
        except error.LookupError:
            # ambiguous changeid
            return False

    def runCommand(self):
        opts = {
            'clean': self.discard_chk.isChecked(),
            'push': self.push_chk.isChecked(),
            'new_branch': self.newbranch_chk.isChecked(),
            'force': self.force_chk.isChecked(),
            'd': self.path_combo.currentText(),
            }

        # Refer to the revision by the short hash.
        rev = hglib.fromunicode(self.rev_combo.currentText())
        ctx = self.repo[rev]

        cmdline = hglib.buildcmdargs('rupdate', ctx.hex(), **opts)
        return self._repoagent.runCommand(cmdline, self)

    ### Signal Handlers ###

    def show_options(self, visible):
        self.push_chk.setVisible(visible)
        self.newbranch_chk.setVisible(visible)
        self.force_chk.setVisible(visible)


def createRemoteUpdateDialog(repoagent, rev=None, parent=None):
    dlg = cmdui.CmdControlDialog(parent)
    dlg.setWindowTitle(_('Remote Update - %s') % repoagent.displayName())
    dlg.setWindowIcon(qtlib.geticon('hg-update'))
    dlg.setObjectName('rupdate')
    dlg.setRunButtonText(_('&Update'))
    dlg.setCommandWidget(RemoteUpdateWidget(repoagent, rev, dlg))
    return dlg
