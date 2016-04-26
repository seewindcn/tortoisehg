# bookmark.py - Bookmark dialog for TortoiseHg
#
# Copyright 2010 Michal De Wildt <michael.dewildt@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import cmdcore, qtlib

class BookmarkDialog(QDialog):

    def __init__(self, repoagent, rev, parent=None):
        super(BookmarkDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)
        self._repoagent = repoagent
        repo = repoagent.rawRepo()
        self._cmdsession = cmdcore.nullCmdSession()
        self.rev = rev
        self.node = repo[rev].node()

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

        form.addRow(_('Revision:'), QLabel('%d (%s)' % (rev, repo[rev])))

        ### bookmark combo
        self.bookmarkCombo = QComboBox()
        self.bookmarkCombo.setEditable(True)
        self.bookmarkCombo.setMinimumContentsLength(30)  # cut long name
        self.bookmarkCombo.currentIndexChanged.connect(self.bookmarkTextChanged)
        self.bookmarkCombo.editTextChanged.connect(self.bookmarkTextChanged)
        qtlib.allowCaseChangingInput(self.bookmarkCombo)
        form.addRow(_('Bookmark:'), self.bookmarkCombo)

        ### Rename input
        self.newNameEdit = QLineEdit()
        self.newNameEdit.textEdited.connect(self.bookmarkTextChanged)
        form.addRow(_('New Name:'), self.newNameEdit)

        ### Activate checkbox
        self.activateCheckBox = QCheckBox()
        if self.node == self.repo['.'].node():
            self.activateCheckBox.setChecked(True)
        else:
            self.activateCheckBox.setChecked(False)
            self.activateCheckBox.setEnabled(False)
        form.addRow(_('Activate:'), self.activateCheckBox)

        ## bottom buttons
        BB = QDialogButtonBox
        bbox = QDialogButtonBox()
        self.addBtn = bbox.addButton(_('&Add'), BB.ActionRole)
        self.renameBtn = bbox.addButton(_('Re&name'), BB.ActionRole)
        self.removeBtn = bbox.addButton(_('&Remove'), BB.ActionRole)
        self.moveBtn = bbox.addButton(_('&Move'), BB.ActionRole)
        bbox.addButton(BB.Close)
        bbox.rejected.connect(self.reject)
        form.addRow(bbox)

        self.addBtn.clicked.connect(self.add_bookmark)
        self.renameBtn.clicked.connect(self.rename_bookmark)
        self.removeBtn.clicked.connect(self.remove_bookmark)
        self.moveBtn.clicked.connect(self.move_bookmark)

        ## horizontal separator
        self.sep = QFrame()
        self.sep.setFrameShadow(QFrame.Sunken)
        self.sep.setFrameShape(QFrame.HLine)
        self.layout().addWidget(self.sep)

        ## status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        self.layout().addWidget(self.status)
        self._finishmsg = None

        # dialog setting
        self.setWindowTitle(_('Bookmark - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-bookmarks'))

        # prepare to show
        self.clear_status()
        self.refresh()
        self._repoagent.repositoryChanged.connect(self.refresh)
        self.bookmarkCombo.setFocus()
        self.bookmarkTextChanged()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def _allBookmarks(self):
        return map(hglib.tounicode, self.repo._bookmarks)

    @pyqtSlot()
    def refresh(self):
        """ update display on dialog with recent repo data """
        # add bookmarks to drop-down list
        cur = self.bookmarkCombo.currentText()
        self.bookmarkCombo.clear()
        self.bookmarkCombo.addItems(sorted(self._allBookmarks()))
        if cur:
            self.bookmarkCombo.setEditText(cur)
        else:
            ctx = self.repo[self.rev]
            cs_bookmarks = ctx.bookmarks()
            if hglib.activebookmark(self.repo) in cs_bookmarks:
                bm = hglib.tounicode(hglib.activebookmark(self.repo))
                self.bookmarkCombo.setEditText(bm)
            elif cs_bookmarks:
                bm = hglib.tounicode(cs_bookmarks[0])
                self.bookmarkCombo.setEditText(bm)
            else:
                self.bookmarkTextChanged()

    @pyqtSlot()
    def bookmarkTextChanged(self):
        bookmark = self.bookmarkCombo.currentText()
        bookmarklocal = hglib.fromunicode(bookmark)
        if bookmarklocal in self.repo._bookmarks:
            curnode = self.repo._bookmarks[bookmarklocal]
            self.addBtn.setEnabled(False)
            self.newNameEdit.setEnabled(True)
            self.removeBtn.setEnabled(True)
            self.renameBtn.setEnabled(bool(self.newNameEdit.text()))
            self.moveBtn.setEnabled(self.node != curnode)
        else:
            self.addBtn.setEnabled(bool(bookmark))
            self.removeBtn.setEnabled(False)
            self.moveBtn.setEnabled(False)
            self.renameBtn.setEnabled(False)
            self.newNameEdit.setEnabled(False)

    def setBookmarkName(self, name):
        self.bookmarkCombo.setEditText(name)

    def set_status(self, text, icon=None):
        self.status.setVisible(True)
        self.sep.setVisible(True)
        self.status.set_status(text, icon)

    def clear_status(self):
        self.status.setHidden(True)
        self.sep.setHidden(True)

    def _runBookmark(self, *args, **opts):
        self._finishmsg = opts.pop('finishmsg')
        cmdline = hglib.buildcmdargs('bookmarks', *args, **opts)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onBookmarkFinished)

    @pyqtSlot(int)
    def _onBookmarkFinished(self, ret):
        if ret == 0:
            self.bookmarkCombo.clearEditText()
            self.newNameEdit.setText('')
            self.set_status(self._finishmsg, True)
        else:
            self.set_status(self._cmdsession.errorString(), False)

    @pyqtSlot()
    def add_bookmark(self):
        bookmark = unicode(self.bookmarkCombo.currentText())
        if bookmark in self._allBookmarks():
            self.set_status(_('A bookmark named "%s" already exists') %
                            bookmark, False)
            return

        finishmsg = _("Bookmark '%s' has been added") % bookmark
        rev = None
        if not self.activateCheckBox.isChecked():
            rev = self.rev
        self._runBookmark(bookmark, rev=rev, finishmsg=finishmsg)

    @pyqtSlot()
    def move_bookmark(self):
        bookmark = unicode(self.bookmarkCombo.currentText())
        if bookmark not in self._allBookmarks():
            self.set_status(_('Bookmark named "%s" does not exist') %
                            bookmark, False)
            return

        finishmsg = _("Bookmark '%s' has been moved") % bookmark
        rev = None
        if not self.activateCheckBox.isChecked():
            rev = self.rev
        self._runBookmark(bookmark, rev=rev, force=True, finishmsg=finishmsg)

    @pyqtSlot()
    def remove_bookmark(self):
        bookmark = unicode(self.bookmarkCombo.currentText())
        if bookmark not in self._allBookmarks():
            self.set_status(_("Bookmark '%s' does not exist") % bookmark, False)
            return

        finishmsg = _("Bookmark '%s' has been removed") % bookmark
        self._runBookmark(bookmark, delete=True, finishmsg=finishmsg)

    @pyqtSlot()
    def rename_bookmark(self):
        name = unicode(self.bookmarkCombo.currentText())
        if name not in self._allBookmarks():
            self.set_status(_("Bookmark '%s' does not exist") % name, False)
            return

        newname = unicode(self.newNameEdit.text())
        if newname in self._allBookmarks():
            self.set_status(_('A bookmark named "%s" already exists') %
                            newname, False)
            return

        finishmsg = (_("Bookmark '%s' has been renamed to '%s'")
                     % (name, newname))
        self._runBookmark(name, newname, rename=True, finishmsg=finishmsg)


_extractbookmarknames = re.compile(r'(.*) [0-9a-f]{12,}$',
                                   re.MULTILINE).findall

class SyncBookmarkDialog(QDialog):

    def __init__(self, repoagent, syncurl=None, parent=None):
        QDialog.__init__(self, parent)
        self._repoagent = repoagent
        self._syncurl = syncurl
        self._cmdsession = cmdcore.nullCmdSession()
        self._insess = cmdcore.nullCmdSession()
        self._outsess = cmdcore.nullCmdSession()

        self.setWindowTitle(_('TortoiseHg Bookmark Sync'))
        self.setWindowIcon(qtlib.geticon('thg-sync-bookmarks'))

        base = QVBoxLayout()
        base.setSpacing(0)
        base.setContentsMargins(2, 2, 2, 2)
        self.setLayout(base)

        # horizontal splitter
        self.splitter = QSplitter(self)
        self.splitter.setOrientation(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setObjectName('splitter')
        self.layout().addWidget(self.splitter)

        # outgoing frame
        outgoingFrame = QFrame(self.splitter)
        outgoingLayout = QVBoxLayout()
        outgoingLayout.setSpacing(2)
        outgoingLayout.setMargin(2)
        outgoingLayout.setContentsMargins(2, 2, 2, 2)
        outgoingFrame.setLayout(outgoingLayout)
        outgoingLabel = QLabel(_('Outgoing Bookmarks'))
        outgoingLayout.addWidget(outgoingLabel)
        self.outgoingList = QListWidget(self)
        self.outgoingList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.outgoingList.setSelectionMode(QListWidget.ExtendedSelection)
        self.outgoingList.customContextMenuRequested.connect(
            self._onOutgoingMenuRequested)
        self.outgoingList.itemSelectionChanged.connect(self._updateActions)
        outgoingLayout.addWidget(self.outgoingList)

        self._outactions = []
        a = QAction(_('&Push Bookmark'), self)
        a.triggered.connect(self.push_bookmark)
        self._outactions.append(a)
        a = QAction(_('&Remove Bookmark'), self)
        a.triggered.connect(self.remove_outgoing)
        self._outactions.append(a)
        self.addActions(self._outactions)
        outgoingBtnLayout = QHBoxLayout()
        outgoingBtnLayout.setSpacing(2)
        outgoingBtnLayout.setMargin(2)
        outgoingBtnLayout.setContentsMargins(2, 2, 2, 2)
        for a in self._outactions:
            outgoingBtnLayout.addWidget(qtlib.ActionPushButton(a, self))
        outgoingLayout.addLayout(outgoingBtnLayout)

        # incoming frame
        incomingFrame = QFrame(self.splitter)
        incomingLayout = QVBoxLayout()
        incomingLayout.setSpacing(2)
        incomingLayout.setMargin(2)
        incomingLayout.setContentsMargins(2, 2, 2, 2)
        incomingFrame.setLayout(incomingLayout)
        incomingLabel = QLabel(_('Incoming Bookmarks'))
        incomingLayout.addWidget(incomingLabel)
        self.incomingList = QListWidget(self)
        self.incomingList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.incomingList.setSelectionMode(QListWidget.ExtendedSelection)
        self.incomingList.customContextMenuRequested.connect(
            self._onIncomingMenuRequested)
        self.incomingList.itemSelectionChanged.connect(self._updateActions)
        incomingLayout.addWidget(self.incomingList)

        self._inactions = []
        a = QAction(_('P&ull Bookmark'), self)
        a.triggered.connect(self.pull_bookmark)
        self._inactions.append(a)
        a = QAction(_('R&emove Bookmark'), self)
        a.triggered.connect(self.remove_incoming)
        self._inactions.append(a)
        self.addActions(self._inactions)
        incomingBtnLayout = QHBoxLayout()
        incomingBtnLayout.setSpacing(2)
        incomingBtnLayout.setMargin(2)
        incomingBtnLayout.setContentsMargins(2, 2, 2, 2)
        for a in self._inactions:
            incomingBtnLayout.addWidget(qtlib.ActionPushButton(a, self))
        incomingLayout.addLayout(incomingBtnLayout)

        # status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        self.layout().addWidget(self.status)
        self._finishmsg = None

        self.refresh()

    def set_status(self, text, icon=None):
        self.status.set_status(text, icon)

    @pyqtSlot()
    def refresh(self):
        """ update the bookmark lists """
        cmdline = hglib.buildcmdargs('outgoing', self._syncurl, bookmarks=True)
        self._outsess = sess = self._repoagent.runCommand(cmdline, self)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._onListLocalBookmarksFinished)
        cmdline = hglib.buildcmdargs('incoming', self._syncurl, bookmarks=True)
        self._insess = sess = self._repoagent.runCommand(cmdline, self)
        sess.setCaptureOutput(True)
        sess.commandFinished.connect(self._onListRemoteBookmarksFinished)
        self._updateActions()

    @pyqtSlot()
    def _onListLocalBookmarksFinished(self):
        self._onListBookmarksFinished(self._outsess, self.outgoingList)

    @pyqtSlot()
    def _onListRemoteBookmarksFinished(self):
        self._onListBookmarksFinished(self._insess, self.incomingList)

    def _onListBookmarksFinished(self, sess, worklist):
        ret = sess.exitCode()
        if ret == 0:
            bookmarks = _extractbookmarknames(str(sess.readAll()))
            self._updateBookmarkList(worklist, bookmarks)
        elif ret == 1:
            self._updateBookmarkList(worklist, [])
        else:
            self.set_status(sess.errorString(), False)
        self._updateActions()

    def selectedOutgoingBookmarks(self):
        return [unicode(x.text()) for x in self.outgoingList.selectedItems()]

    def selectedIncomingBookmarks(self):
        return [unicode(x.text()) for x in self.incomingList.selectedItems()]

    @pyqtSlot()
    def push_bookmark(self):
        self._sync('push', self.selectedOutgoingBookmarks(),
                   _('Pushed local bookmark: %s'))

    @pyqtSlot()
    def pull_bookmark(self):
        self._sync('pull', self.selectedIncomingBookmarks(),
                   _('Pulled remote bookmark: %s'))

    @pyqtSlot()
    def remove_incoming(self):
        self._sync('push', self.selectedIncomingBookmarks(),
                   _('Removed remote bookmark: %s'))

    def _sync(self, cmdname, selected, finishmsg):
        if not selected:
            return
        self._finishmsg = finishmsg % ', '.join(selected)
        cmdline = hglib.buildcmdargs(cmdname, self._syncurl, bookmark=selected)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onBoomarkHandlingFinished)
        self._updateActions()

    @pyqtSlot()
    def remove_outgoing(self):
        selected = self.selectedOutgoingBookmarks()
        if not selected:
            return

        self._finishmsg = _('Removed local bookmark: %s') % ', '.join(selected)

        cmdline = hglib.buildcmdargs('bookmark', *selected, delete=True)
        self._cmdsession = sess = self._repoagent.runCommand(cmdline, self)
        sess.commandFinished.connect(self._onBoomarkHandlingFinished)
        self._updateActions()

    @pyqtSlot(int)
    def _onBoomarkHandlingFinished(self, ret):
        if ret == 0 or ret == 1:
            self.set_status(self._finishmsg, True)
        else:
            self.set_status(self._cmdsession.errorString(), False)

        self.refresh()

    def _updateBookmarkList(self, worklist, bookmarks):
        selected = [x.text() for x in worklist.selectedItems()]
        worklist.clear()
        bookmarks = [hglib.tounicode(x.strip()) for x in bookmarks]
        worklist.addItems(bookmarks)
        for select in selected:
            items = worklist.findItems(select, Qt.MatchExactly)
            for item in items:
                item.setSelected(True)

    @pyqtSlot(QPoint)
    def _onOutgoingMenuRequested(self, pos):
        self._popupMenuFor(self._outactions, self.outgoingList, pos)

    @pyqtSlot(QPoint)
    def _onIncomingMenuRequested(self, pos):
        self._popupMenuFor(self._inactions, self.incomingList, pos)

    def _popupMenuFor(self, actions, worklist, pos):
        menu = QMenu(self)
        menu.addActions(actions)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(worklist.viewport().mapToGlobal(pos))

    @pyqtSlot()
    def _updateActions(self):
        state = all(sess.isFinished() for sess
                    in [self._cmdsession, self._insess, self._outsess])
        for a in self._outactions:
            a.setEnabled(state and bool(self.selectedOutgoingBookmarks()))
        for a in self._inactions:
            a.setEnabled(state and bool(self.selectedIncomingBookmarks()))
