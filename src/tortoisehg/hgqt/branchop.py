# branchop.py - branch operations dialog for TortoiseHg commit tool
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util.i18n import _
from tortoisehg.util import hglib

from tortoisehg.hgqt import qtlib

class BranchOpDialog(QDialog):
    'Dialog for manipulating wctx.branch()'
    def __init__(self, repoagent, oldbranchop, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('%s - branch operation') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-branch'))
        layout = QVBoxLayout()
        self.setLayout(layout)
        repo = repoagent.rawRepo()
        wctx = repo[None]

        if len(wctx.parents()) == 2:
            lbl = QLabel('<b>'+_('Select branch of merge commit')+'</b>')
            layout.addWidget(lbl)
            branchCombo = QComboBox()
            # If both parents belong to the same branch, do not duplicate the
            # branch name in the branch select combo
            branchlist = [p.branch() for p in wctx.parents()]
            if branchlist[0] == branchlist[1]:
                branchlist = [branchlist[0]]
            for b in branchlist:
                branchCombo.addItem(hglib.tounicode(b))
            layout.addWidget(branchCombo)
        else:
            text = '<b>'+_('Changes take effect on next commit')+'</b>'
            lbl = QLabel(text)
            layout.addWidget(lbl)

            grid = QGridLayout()
            nochange = QRadioButton(_('No branch changes'))
            newbranch = QRadioButton(_('Open a new named branch'))
            closebranch = QRadioButton(_('Close current branch'))
            branchCombo = QComboBox()
            branchCombo.setEditable(True)
            qtlib.allowCaseChangingInput(branchCombo)

            wbu = wctx.branch()
            for name in hglib.namedbranches(repo):
                if name == wbu:
                    continue
                branchCombo.addItem(hglib.tounicode(name))
            branchCombo.activated.connect(self.accept)

            grid.addWidget(nochange, 0, 0)
            grid.addWidget(newbranch, 1, 0)
            grid.addWidget(branchCombo, 1, 1)
            grid.addWidget(closebranch, 2, 0)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)
            layout.addStretch()

            newbranch.toggled.connect(branchCombo.setEnabled)
            branchCombo.setEnabled(False)
            if oldbranchop is None:
                nochange.setChecked(True)
            elif oldbranchop == False:
                closebranch.setChecked(True)
            else:
                bc = branchCombo
                i = bc.findText(oldbranchop)
                if i >= 0:
                    bc.setCurrentIndex(i)
                else:
                    bc.addItem(oldbranchop)
                    bc.setCurrentIndex(bc.count() - 1)
                newbranch.setChecked(True)
            self.closebranch = closebranch

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setAutoDefault(True)
        layout.addWidget(bb)
        self.bb = bb
        self.branchCombo = branchCombo
        QShortcut(QKeySequence('Ctrl+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)
        QShortcut(QKeySequence('Escape'), self, self.reject)

    def accept(self):
        '''Branch operation is one of:
            None  - leave wctx branch name untouched
            False - close current branch
            unicode - open new named branch
        '''
        if self.branchCombo.isEnabled():
            # branch name cannot start/end with whitespace (see dirstate._branch)
            self.branchop = unicode(self.branchCombo.currentText()).strip()
        elif self.closebranch.isChecked():
            self.branchop = False
        else:
            self.branchop = None
        QDialog.accept(self)
