# thgstrip.py - MQ strip dialog for TortoiseHg
#
# Copyright 2009 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 David Wilhelm <dave@jumbledpile.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _, ngettext
from tortoisehg.hgqt import cmdcore, cmdui, cslist, qtlib

class StripWidget(cmdui.AbstractCmdWidget):
    """Command widget to strip changesets"""

    def __init__(self, repoagent, rev=None, parent=None, opts={}):
        super(StripWidget, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._repoagent = repoagent

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.setLayout(grid)

        ### target revision combo
        self.rev_combo = combo = QComboBox()
        combo.setEditable(True)
        grid.addWidget(QLabel(_('Strip:')), 0, 0)
        grid.addWidget(combo, 0, 1)
        grid.addWidget(QLabel(_('Preview:')), 1, 0, Qt.AlignLeft | Qt.AlignTop)
        self.status = QLabel("")
        grid.addWidget(self.status, 1, 1, Qt.AlignLeft | Qt.AlignTop)

        if rev is None:
            rev = self.repo.dirstate.branch()
        else:
            rev = str(rev)
        combo.addItem(hglib.tounicode(rev))
        combo.setCurrentIndex(0)
        for name in hglib.namedbranches(self.repo):
            combo.addItem(hglib.tounicode(name))

        tags = list(self.repo.tags())
        tags.sort(reverse=True)
        for tag in tags:
            combo.addItem(hglib.tounicode(tag))

        ### preview box, contained in scroll area, contains preview grid
        self.cslist = cslist.ChangesetList(self.repo)
        cslistrow = 2
        cslistcol = 1
        grid.addWidget(self.cslist, cslistrow, cslistcol)

        ### options
        optbox = QVBoxLayout()
        optbox.setSpacing(6)
        grid.addWidget(QLabel(_('Options:')), 3, 0, Qt.AlignLeft | Qt.AlignTop)
        grid.addLayout(optbox, 3, 1)

        self._optchks = {}
        for name, text in [
                ('force', _('Discard local changes, no backup (-f/--force)')),
                ('nobackup', _('No backup (-n/--nobackup)')),
                ('keep', _('Do not modify working copy during strip '
                           '(-k/--keep)')),
                ]:
            self._optchks[name] = w = QCheckBox(text)
            w.setChecked(bool(opts.get(name)))
            optbox.addWidget(w)

        grid.setRowStretch(cslistrow, 1)
        grid.setColumnStretch(cslistcol, 1)

        # signal handlers
        self.rev_combo.editTextChanged.connect(self.preview)

        # prepare to show
        self.rev_combo.lineEdit().selectAll()
        self.cslist.setHidden(False)
        self.preview()

    ### Private Methods ###

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def get_rev(self):
        """Return the integer revision number of the input or None"""
        revstr = hglib.fromunicode(self.rev_combo.currentText())
        if not revstr:
            return None
        try:
            rev = self.repo[revstr].rev()
        except (error.RepoError, error.LookupError):
            return None
        return rev

    def updatecslist(self, uselimit=True):
        """Update the cs list and return the success status as a bool"""
        rev = self.get_rev()
        if rev is None:
            return False
        striprevs = list(self.repo.changelog.descendants([rev]))
        striprevs.append(rev)
        striprevs.sort()
        self.cslist.clear()
        self.cslist.update(striprevs)
        return True

    @pyqtSlot()
    def preview(self):
        if self.updatecslist():
            striprevs = self.cslist.curitems
            cstext = ngettext(
                "<b>%d changeset</b> will be stripped",
                "<b>%d changesets</b> will be stripped",
                len(striprevs)) % len(striprevs)
            self.status.setText(cstext)
        else:
            self.cslist.clear()
            self.cslist.updatestatus()
            cstext = qtlib.markup(_('Unknown revision!'), fg='red',
                                  weight='bold')
            self.status.setText(cstext)
        self.commandChanged.emit()

    def canRunCommand(self):
        return self.get_rev() is not None

    def runCommand(self):
        opts = {'verbose': True}
        opts.update((n, w.isChecked()) for n, w in self._optchks.iteritems())

        wc = self.repo[None]
        wcparents = wc.parents()
        wcp1rev = wcparents[0].rev()
        wcp2rev = None
        if len(wcparents) > 1:
            wcp2rev = wcparents[1].rev()
        if not opts['force'] and not opts['keep'] and \
                (wcp1rev in self.cslist.curitems or
                         wcp2rev in self.cslist.curitems) and \
                (wc.modified() or wc.added() or wc.removed()):
            main = _("Detected uncommitted local changes.")
            text = _("Do you want to keep them or discard them?")
            choices = (_('&Keep (--keep)'),
                      _('&Discard (--force)'),
                      _('&Cancel'),
            )
            resp = qtlib.CustomPrompt(_('Confirm Strip'),
                '<b>%s</b><p>%s' % (main, text),
                self, choices, default=0, esc=2).run()
            if resp == 0:
                opts['keep'] = True
            elif resp == 1:
                opts['force'] = True
            else:
                return cmdcore.nullCmdSession()

        rev = self.rev_combo.currentText()
        cmdline = hglib.buildcmdargs('strip', rev, **opts)
        return self._repoagent.runCommand(cmdline, self)


def createStripDialog(repoagent, rev=None, parent=None, opts={}):
    dlg = cmdui.CmdControlDialog(parent)
    dlg.setWindowIcon(qtlib.geticon('hg-strip'))
    dlg.setWindowTitle(_('Strip - %s') % repoagent.displayName())
    dlg.setObjectName('strip')
    dlg.setRunButtonText(_('&Strip'))
    dlg.setCommandWidget(StripWidget(repoagent, rev, dlg, opts))
    return dlg
