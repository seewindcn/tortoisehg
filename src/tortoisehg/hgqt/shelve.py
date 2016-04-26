# shelve.py - TortoiseHg shelve and patch tool
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import os
import time

from mercurial import commands, error, util

from tortoisehg.util import hglib
from tortoisehg.util.patchctx import patchctx
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, chunks

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class ShelveDialog(QDialog):

    wdir = _('Working Directory')

    def __init__(self, repoagent, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)

        self.setWindowIcon(qtlib.geticon('hg-shelve'))

        self._repoagent = repoagent
        self.shelves = []
        self.patches = []
        self._patchnames = {}  # path: mq patch name

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self.setLayout(layout)

        self.tbarhbox = hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        self.layout().addLayout(self.tbarhbox)

        self.splitter = QSplitter(self)
        self.splitter.setOrientation(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setObjectName('splitter')
        self.layout().addWidget(self.splitter, 1)

        aframe = QFrame(self.splitter)
        avbox = QVBoxLayout()
        avbox.setSpacing(2)
        avbox.setMargin(2)
        avbox.setContentsMargins(2, 2, 2, 2)
        aframe.setLayout(avbox)
        ahbox = QHBoxLayout()
        ahbox.setSpacing(2)
        ahbox.setMargin(2)
        ahbox.setContentsMargins(2, 2, 2, 2)
        avbox.addLayout(ahbox)
        self.comboa = QComboBox(self)
        self.comboa.setMinimumContentsLength(10)  # allow to cut long content
        self.comboa.currentIndexChanged.connect(self.comboAChanged)
        self.clearShelfButtonA = QPushButton(_('Clear'))
        self.clearShelfButtonA.setToolTip(_('Clear the current shelf file'))
        self.clearShelfButtonA.clicked.connect(self.clearShelfA)
        self.delShelfButtonA = QPushButton(_('Delete'))
        self.delShelfButtonA.setToolTip(_('Delete the current shelf file'))
        self.delShelfButtonA.clicked.connect(self.deleteShelfA)
        ahbox.addWidget(self.comboa, 1)
        ahbox.addWidget(self.clearShelfButtonA)
        ahbox.addWidget(self.delShelfButtonA)

        self.browsea = chunks.ChunksWidget(self._repoagent, self)
        self.browsea.splitter.splitterMoved.connect(self.linkSplitters)
        self.browsea.linkActivated.connect(self.linkActivated)
        self.browsea.showMessage.connect(self.showMessage)
        avbox.addWidget(self.browsea)

        bframe = QFrame(self.splitter)
        bvbox = QVBoxLayout()
        bvbox.setSpacing(2)
        bvbox.setMargin(2)
        bvbox.setContentsMargins(2, 2, 2, 2)
        bframe.setLayout(bvbox)
        bhbox = QHBoxLayout()
        bhbox.setSpacing(2)
        bhbox.setMargin(2)
        bhbox.setContentsMargins(2, 2, 2, 2)
        bvbox.addLayout(bhbox)
        self.combob = QComboBox(self)
        self.combob.setMinimumContentsLength(10)  # allow to cut long content
        self.combob.currentIndexChanged.connect(self.comboBChanged)
        self.clearShelfButtonB = QPushButton(_('Clear'))
        self.clearShelfButtonB.setToolTip(_('Clear the current shelf file'))
        self.clearShelfButtonB.clicked.connect(self.clearShelfB)
        self.delShelfButtonB = QPushButton(_('Delete'))
        self.delShelfButtonB.setToolTip(_('Delete the current shelf file'))
        self.delShelfButtonB.clicked.connect(self.deleteShelfB)
        bhbox.addWidget(self.combob, 1)
        bhbox.addWidget(self.clearShelfButtonB)
        bhbox.addWidget(self.delShelfButtonB)

        self.browseb = chunks.ChunksWidget(self._repoagent, self)
        self.browseb.splitter.splitterMoved.connect(self.linkSplitters)
        self.browseb.linkActivated.connect(self.linkActivated)
        self.browseb.showMessage.connect(self.showMessage)
        bvbox.addWidget(self.browseb)

        self.lefttbar = QToolBar(_('Left Toolbar'), objectName='lefttbar')
        self.lefttbar.setIconSize(qtlib.toolBarIconSize())
        self.lefttbar.setStyleSheet(qtlib.tbstylesheet)
        self.tbarhbox.addWidget(self.lefttbar)
        self.deletea = a = QAction(_('Delete selected chunks'), self)
        self.deletea.triggered.connect(self.deleteChunksA)
        a.setIcon(qtlib.geticon('thg-shelve-delete-left'))
        self.lefttbar.addAction(self.deletea)
        self.allright = a = QAction(_('Move all files right'), self)
        self.allright.triggered.connect(self.moveFilesRight)
        a.setIcon(qtlib.geticon('thg-shelve-move-right-all'))
        self.lefttbar.addAction(self.allright)
        self.fileright = a = QAction(_('Move selected file right'), self)
        self.fileright.triggered.connect(self.moveFileRight)
        a.setIcon(qtlib.geticon('thg-shelve-move-right-file'))
        self.lefttbar.addAction(self.fileright)
        self.editfilea = a = QAction(_('Edit file'), self)
        a.setIcon(qtlib.geticon('edit-file'))
        self.lefttbar.addAction(self.editfilea)
        self.chunksright = a = QAction(_('Move selected chunks right'), self)
        self.chunksright.triggered.connect(self.moveChunksRight)
        a.setIcon(qtlib.geticon('thg-shelve-move-right-chunks'))
        self.lefttbar.addAction(self.chunksright)

        self.rbar = QToolBar(_('Refresh Toolbar'), objectName='rbar')
        self.rbar.setIconSize(qtlib.toolBarIconSize())
        self.rbar.setStyleSheet(qtlib.tbstylesheet)
        self.tbarhbox.addStretch(1)
        self.tbarhbox.addWidget(self.rbar)
        self.refreshAction = a = QAction(_('Refresh'), self)
        a.setIcon(qtlib.geticon('view-refresh'))
        a.setShortcuts(QKeySequence.Refresh)
        a.triggered.connect(self.refreshCombos)
        self.rbar.addAction(self.refreshAction)
        self.actionNew = a = QAction(_('New Shelf'), self)
        a.setIcon(qtlib.geticon('document-new'))
        a.triggered.connect(self.newShelfPressed)
        self.rbar.addAction(self.actionNew)

        self.righttbar = QToolBar(_('Right Toolbar'), objectName='righttbar')
        self.righttbar.setIconSize(qtlib.toolBarIconSize())
        self.righttbar.setStyleSheet(qtlib.tbstylesheet)
        self.tbarhbox.addStretch(1)
        self.tbarhbox.addWidget(self.righttbar)
        self.chunksleft = a = QAction(_('Move selected chunks left'), self)
        self.chunksleft.triggered.connect(self.moveChunksLeft)
        a.setIcon(qtlib.geticon('thg-shelve-move-left-chunks'))
        self.righttbar.addAction(self.chunksleft)
        self.editfileb = a = QAction(_('Edit file'), self)
        a.setIcon(qtlib.geticon('edit-file'))
        self.righttbar.addAction(self.editfileb)
        self.fileleft = a = QAction(_('Move selected file left'), self)
        self.fileleft.triggered.connect(self.moveFileLeft)
        a.setIcon(qtlib.geticon('thg-shelve-move-left-file'))
        self.righttbar.addAction(self.fileleft)
        self.allleft = a = QAction(_('Move all files left'), self)
        self.allleft.triggered.connect(self.moveFilesLeft)
        a.setIcon(qtlib.geticon('thg-shelve-move-left-all'))
        self.righttbar.addAction(self.allleft)
        self.deleteb = a = QAction(_('Delete selected chunks'), self)
        self.deleteb.triggered.connect(self.deleteChunksB)
        a.setIcon(qtlib.geticon('thg-shelve-delete-right'))
        self.righttbar.addAction(self.deleteb)

        self.editfilea.triggered.connect(self.browsea.editCurrentFile)
        self.editfileb.triggered.connect(self.browseb.editCurrentFile)

        self.browsea.chunksSelected.connect(self.chunksright.setEnabled)
        self.browsea.chunksSelected.connect(self.deletea.setEnabled)
        self.browsea.fileSelected.connect(self.fileright.setEnabled)
        self.browsea.fileSelected.connect(self.editfilea.setEnabled)
        self.browsea.fileModified.connect(self.refreshCombos)
        self.browsea.fileModelEmpty.connect(self.allright.setDisabled)
        self.browseb.chunksSelected.connect(self.chunksleft.setEnabled)
        self.browseb.chunksSelected.connect(self.deleteb.setEnabled)
        self.browseb.fileSelected.connect(self.fileleft.setEnabled)
        self.browseb.fileSelected.connect(self.editfileb.setEnabled)
        self.browseb.fileModified.connect(self.refreshCombos)
        self.browseb.fileModelEmpty.connect(self.allleft.setDisabled)

        self.statusbar = cmdui.ThgStatusBar(self)
        self.layout().addWidget(self.statusbar)
        self.showMessage(_('Backup copies of modified files can be found '
                           'in .hg/Trashcan/'))

        self.refreshCombos()
        repoagent.repositoryChanged.connect(self.refreshCombos)

        self.setWindowTitle(_('TortoiseHg Shelve - %s')
                            % repoagent.displayName())
        self.restoreSettings()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    @pyqtSlot()
    def moveFileRight(self):
        if self.combob.currentIndex() == -1:
            self.newShelf(False)
        for file in self.browsea.getSelectedFiles():
            chunks = self.browsea.getChunksForFile(file)
            if chunks and self.browseb.mergeChunks(file, chunks):
                self.browsea.removeFile(file)

    @pyqtSlot()
    def moveFileLeft(self):
        for file in self.browseb.getSelectedFiles():
            chunks = self.browseb.getChunksForFile(file)
            if chunks and self.browsea.mergeChunks(file, chunks):
                self.browseb.removeFile(file)

    @pyqtSlot()
    def moveFilesRight(self):
        if self.combob.currentIndex() == -1:
            self.newShelf(False)
        for file in self.browsea.getFileList():
            chunks = self.browsea.getChunksForFile(file)
            if chunks and self.browseb.mergeChunks(file, chunks):
                self.browsea.removeFile(file)

    @pyqtSlot()
    def moveFilesLeft(self):
        for file in self.browseb.getFileList():
            chunks = self.browseb.getChunksForFile(file)
            if chunks and self.browsea.mergeChunks(file, chunks):
                self.browseb.removeFile(file)

    @pyqtSlot()
    def moveChunksRight(self):
        if self.combob.currentIndex() == -1:
            self.newShelf(False)
        file, chunks = self.browsea.getSelectedFileAndChunks()
        if self.browseb.mergeChunks(file, chunks):
            self.browsea.deleteSelectedChunks()

    @pyqtSlot()
    def moveChunksLeft(self):
        file, chunks = self.browseb.getSelectedFileAndChunks()
        if self.browsea.mergeChunks(file, chunks):
            self.browseb.deleteSelectedChunks()

    @pyqtSlot()
    def deleteChunksA(self):
        if self.comboa.currentIndex() == 0:
            msg = _('Delete selected chunks from working copy?')
        else:
            f = hglib.tounicode(os.path.basename(self.currentPatchA()))
            msg = _('Delete selected chunks from shelf file %s?') % f
        if qtlib.QuestionMsgBox(_('Are you sure?'), msg, parent=self):
            self.browsea.deleteSelectedChunks()

    @pyqtSlot()
    def deleteChunksB(self):
        f = hglib.tounicode(os.path.basename(self.currentPatchB()))
        msg = _('Delete selected chunks from shelf file %s?') % f
        if qtlib.QuestionMsgBox(_('Are you sure?'), msg, parent=self):
            self.browseb.deleteSelectedChunks()

    @pyqtSlot()
    def newShelfPressed(self):
        self.newShelf(True)

    def newShelf(self, interactive):
        shelve = time.strftime('%Y-%m-%d_%H-%M-%S') + \
                 '_parent_rev_%d' % self.repo['.'].rev()
        if interactive:
            name, ok = qtlib.getTextInput(self,
                         _('TortoiseHg New Shelf Name'),
                         _('Specify name of new shelf'),
                         text=shelve)
            if not ok:
                return
            shelve = hglib.fromunicode(name)
            invalids = (':', '#', '/', '\\')
            bads = [c for c in shelve if c in invalids]
            if bads:
                qtlib.ErrorMsgBox(_('Bad filename'),
                                  _('A shelf name cannot contain %s')
                                  % ''.join(bads))
                return
            badmsg = util.checkosfilename(shelve)
            if badmsg:
                qtlib.ErrorMsgBox(_('Bad filename'), hglib.tounicode(badmsg))
                return
        try:
            fn = os.path.join('shelves', shelve)
            shelfpath = self.repo.join(fn)
            if os.path.exists(shelfpath):
                qtlib.ErrorMsgBox(_('File already exists'),
                                  _('A shelf file of that name already exists'))
                return
            self.repo.makeshelf(shelve)
            self.showMessage(_('New shelf created'))
            self.refreshCombos()
            if shelfpath in self.shelves:
                self.combob.setCurrentIndex(self.shelves.index(shelfpath))
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))

    @pyqtSlot()
    def deleteShelfA(self):
        shelf = self.currentPatchA()
        ushelf = hglib.tounicode(os.path.basename(shelf))
        if not qtlib.QuestionMsgBox(_('Are you sure?'),
                                    _('Delete shelf file %s?') % ushelf):
            return
        try:
            os.unlink(shelf)
            self.showMessage(_('Shelf deleted'))
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))
        self.refreshCombos()

    @pyqtSlot()
    def clearShelfA(self):
        if self.comboa.currentIndex() == 0:
            if not qtlib.QuestionMsgBox(_('Are you sure?'),
                                        _('Revert all working copy changes?')):
                return
            try:
                self.repo.ui.quiet = True
                commands.revert(self.repo.ui, self.repo, all=True)
                self.repo.ui.quiet = False
            except (EnvironmentError, error.Abort), e:
                self.showMessage(hglib.tounicode(str(e)))
                self.refreshCombos()
            return
        shelf = self.currentPatchA()
        ushelf = hglib.tounicode(os.path.basename(shelf))
        if not qtlib.QuestionMsgBox(_('Are you sure?'),
                                _('Clear contents of shelf file %s?') % ushelf):
            return
        try:
            f = open(shelf, "w")
            f.close()
            self.showMessage(_('Shelf cleared'))
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))
        self.refreshCombos()

    @pyqtSlot()
    def deleteShelfB(self):
        shelf = self.currentPatchB()
        ushelf = hglib.tounicode(os.path.basename(shelf))
        if not qtlib.QuestionMsgBox(_('Are you sure?'),
                                    _('Delete shelf file %s?') % ushelf):
            return
        try:
            os.unlink(shelf)
            self.showMessage(_('Shelf deleted'))
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))
        self.refreshCombos()

    @pyqtSlot()
    def clearShelfB(self):
        shelf = self.currentPatchB()
        ushelf = hglib.tounicode(os.path.basename(shelf))
        if not qtlib.QuestionMsgBox(_('Are you sure?'),
                                _('Clear contents of shelf file %s?') % ushelf):
            return
        try:
            f = open(shelf, "w")
            f.close()
            self.showMessage(_('Shelf cleared'))
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))
        self.refreshCombos()

    def currentPatchA(self):
        idx = self.comboa.currentIndex()
        if idx == -1:
            return None
        if idx == 0:
            return self.wdir
        idx -= 1
        if idx < len(self.shelves):
            return self.shelves[idx]
        idx -= len(self.shelves)
        if idx < len(self.patches):
            return self.patches[idx]
        return None

    def currentPatchB(self):
        idx = self.combob.currentIndex()
        if idx == -1:
            return None
        if idx < len(self.shelves):
            return self.shelves[idx]
        idx -= len(self.shelves)
        if idx < len(self.patches):
            return self.patches[idx]
        return None

    @pyqtSlot()
    def refreshCombos(self):
        shelvea, shelveb = self.currentPatchA(), self.currentPatchB()

        # Note that thgshelves returns the shelve list ordered from newest to
        # oldest
        shelves = self.repo.thgshelves()
        disp = [_('Shelf: %s') % hglib.tounicode(s) for s in shelves]

        patches = self.repo.thgmqunappliedpatches
        disp += [_('Patch: %s') % hglib.tounicode(p) for p in patches]

        # store fully qualified paths
        self.shelves = [os.path.join(self.repo.shelfdir, s) for s in shelves]
        self.patches = [self.repo.mq.join(p) for p in patches]
        self._patchnames = dict(zip(self.patches, patches))

        self.comboRefreshInProgress = True
        self.comboa.clear()
        self.combob.clear()
        self.comboa.addItems([self.wdir] + disp)
        self.combob.addItems(disp)

        # attempt to restore selection
        if shelvea == self.wdir:
            idxa = 0
        elif shelvea in self.shelves:
            idxa = self.shelves.index(shelvea) + 1
        elif shelvea in self.patches:
            idxa = len(self.shelves) + self.patches.index(shelvea) + 1
        else:
            idxa = 0
        self.comboa.setCurrentIndex(idxa)

        if shelveb in self.shelves:
            idxb = self.shelves.index(shelveb)
        elif shelveb in self.patches:
            idxb = len(self.shelves) + self.patches.index(shelveb)
        else:
            idxb = 0
        self.combob.setCurrentIndex(idxb)
        self.comboRefreshInProgress = False

        self.comboAChanged(idxa)
        self.comboBChanged(idxb)
        if not patches and not shelves:
            self.delShelfButtonB.setEnabled(False)
            self.clearShelfButtonB.setEnabled(False)
            self.browseb.setContext(patchctx('', self.repo, None))

    @pyqtSlot(int)
    def comboAChanged(self, index):
        if self.comboRefreshInProgress:
            return
        assert index >= 0  # side A should always have "Working Directory"
        if index == 0:
            rev = None
            self.delShelfButtonA.setEnabled(False)
            self.clearShelfButtonA.setEnabled(True)
        else:
            rev = self.currentPatchA()
            rev = self._patchnames.get(rev, rev)
            self.delShelfButtonA.setEnabled(index <= len(self.shelves))
            self.clearShelfButtonA.setEnabled(index <= len(self.shelves))
        self.browsea.setContext(self.repo.changectx(rev))
        self._deselectSamePatch(self.combob)

    @pyqtSlot(int)
    def comboBChanged(self, index):
        if self.comboRefreshInProgress:
            return
        rev = self.currentPatchB()
        rev = self._patchnames.get(rev, rev)
        self.delShelfButtonB.setEnabled(0 <= index < len(self.shelves))
        self.clearShelfButtonB.setEnabled(0 <= index < len(self.shelves))
        self.browseb.setContext(self.repo.changectx(rev))
        self._deselectSamePatch(self.comboa)

    def _deselectSamePatch(self, combo):
        # if the same patch or shelve is selected by both sides, "move" action
        # will corrupt patch content.
        if self.currentPatchA() != self.currentPatchB():
            return
        if combo.count() > 1:
            combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
        else:
            combo.setCurrentIndex(-1)

    @pyqtSlot(int, int)
    def linkSplitters(self, pos, index):
        if self.browsea.splitter.sizes()[0] != pos:
            self.browsea.splitter.moveSplitter(pos, index)
        if self.browseb.splitter.sizes()[0] != pos:
            self.browseb.splitter.moveSplitter(pos, index)

    @pyqtSlot(str)
    def linkActivated(self, linktext):
        pass

    @pyqtSlot(str)
    def showMessage(self, message):
        self.statusbar.showMessage(message)

    def storeSettings(self):
        s = QSettings()
        wb = "shelve/"
        s.setValue(wb + 'geometry', self.saveGeometry())
        s.setValue(wb + 'panesplitter', self.splitter.saveState())
        s.setValue(wb + 'filesplitter', self.browsea.splitter.saveState())
        self.browsea.saveSettings(s, wb + 'fileviewa')
        self.browseb.saveSettings(s, wb + 'fileviewb')

    def restoreSettings(self):
        s = QSettings()
        wb = "shelve/"
        self.restoreGeometry(s.value(wb + 'geometry').toByteArray())
        self.splitter.restoreState(s.value(wb + 'panesplitter').toByteArray())
        self.browsea.splitter.restoreState(
                          s.value(wb + 'filesplitter').toByteArray())
        self.browseb.splitter.restoreState(
                          s.value(wb + 'filesplitter').toByteArray())
        self.browsea.loadSettings(s, wb + 'fileviewa')
        self.browseb.loadSettings(s, wb + 'fileviewb')

    def reject(self):
        self.storeSettings()
        super(ShelveDialog, self).reject()
