# Copyright (c) 2003-2010 LOGILAB S.A. (Paris, FRANCE).
# http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Qt4 dialogs to display hg revisions of a file
"""

import difflib

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib, repomodel, blockmatcher, lexers
from tortoisehg.hgqt import filectxactions, fileview, repoview, revpanel
from tortoisehg.hgqt.qscilib import Scintilla

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciScintilla

sides = ('left', 'right')
otherside = {'left': 'right', 'right': 'left'}

_MARKERPLUSLINE = 31
_MARKERMINUSLINE = 30
_MARKERPLUSUNDERLINE = 29
_MARKERMINUSUNDERLINE = 28

_colormap = {
             '+': QColor(0xA0, 0xFF, 0xB0),
             '-': QColor(0xFF, 0xA0, 0xA0),
             'x': QColor(0xA0, 0xA0, 0xFF)
             }

def _setupFileMenu(menu, fileactions):
    for name in ['visualDiff', 'visualDiffToLocal', None,
                 'visualDiffFile', 'visualDiffFileToLocal', None,
                 'editFile', 'saveFile', 'editLocalFile', 'revertFile']:
        if name:
            menu.addAction(fileactions.action(name))
        else:
            menu.addSeparator()

def _fileDataListForSelection(model, selmodel):
    # since FileRevModel is a model for single file, this creates single
    # FileData between two revisions instead of a list for each selection
    indexes = sorted(selmodel.selectedRows())
    if not indexes:
        return []
    if len(indexes) == 1:
        fd = model.fileData(indexes[0])
    else:
        fd = model.fileData(indexes[0], indexes[-1])
    return [fd]


class _FileDiffScintilla(Scintilla):
    def paintEvent(self, event):
        super(_FileDiffScintilla, self).paintEvent(event)
        viewport = self.viewport()

        start = self.firstVisibleLine()
        scale = self.textHeight(0)  # Currently all lines are the same height
        n = min(viewport.height() / scale + 1, self.lines() - start)
        lines = []
        for i in xrange(0, n):
            m = self.markersAtLine(start + i)
            if m & (1 << _MARKERPLUSLINE):
                lines.append((i, _colormap['+'], ))
            if m & (1 << _MARKERPLUSUNDERLINE):
                lines.append((i + 1, _colormap['+'], ))
            if m & (1 << _MARKERMINUSLINE):
                lines.append((i, _colormap['-'], ))
            if m & (1 << _MARKERMINUSUNDERLINE):
                lines.append((i + 1, _colormap['-'], ))

        p = QPainter(viewport)
        p.setRenderHint(QPainter.Antialiasing)
        for (line, color) in lines:
            p.setPen(QPen(color, 3.0))
            y = line * scale
            p.drawLine(0, y, viewport.width(), y)

# Minimal wrapper to make RepoAgent always returns unfiltered repo.  Because
# filelog_grapher can't take account of hidden changesets, all child widgets
# of file dialog need to take unfiltered repo instance.
#
# TODO: this should be removed if filelog_grapher (and FileRevModel) are
# superseded by revset-based implementation.
class _UnfilteredRepoAgentProxy(object):
    def __init__(self, repoagent):
        self._repoagent = repoagent

    def rawRepo(self):
        repo = self._repoagent.rawRepo()
        return repo.unfiltered()

    def runCommand(self, cmdline, uihandler=None, overlay=True):
        cmdline = ['--hidden'] + cmdline
        return self._repoagent.runCommand(cmdline, uihandler, overlay)

    def runCommandSequence(self, cmdlines, uihandler=None, overlay=True):
        cmdlines = [['--hidden'] + l for l in cmdlines]
        return self._repoagent.runCommandSequence(cmdlines, uihandler, overlay)

    def __getattr__(self, name):
        return getattr(self._repoagent, name)

class _AbstractFileDialog(QMainWindow):

    def __init__(self, repoagent, filename):
        QMainWindow.__init__(self)
        self._repoagent = _UnfilteredRepoAgentProxy(repoagent)

        self.setupUi()
        self._show_rev = None

        assert not isinstance(filename, (unicode, QString))
        self.filename = filename

        self.setWindowTitle(_('Hg file log viewer [%s] - %s')
                            % (repoagent.displayName(),
                               hglib.tounicode(filename)))
        self.setWindowIcon(qtlib.geticon('hg-log'))
        self.setIconSize(qtlib.toolBarIconSize())

        self.createActions()
        self.setupToolbars()

        self.setupViews()
        self.setupModels()

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def reload(self):
        'Reload toolbar action handler'
        self.repo.thginvalidate()
        self.setupModels()

    def onRevisionActivated(self, rev):
        """
        Callback called when a revision is double-clicked in the revisions table
        """
        # TODO: implement by using signal-slot if possible
        from tortoisehg.hgqt import run
        run.qtrun.showRepoInWorkbench(hglib.tounicode(self.repo.root), rev)

class FileLogDialog(_AbstractFileDialog):
    """
    A dialog showing a revision graph for a file.
    """
    def __init__(self, repoagent, filename):
        super(FileLogDialog, self).__init__(repoagent, filename)
        self._readSettings()
        self.revdetails = None

    def closeEvent(self, event):
        self._writeSettings()
        super(FileLogDialog, self).closeEvent(event)

    def _readSettings(self):
        s = QSettings()
        s.beginGroup('filelog')
        try:
            self.textView.loadSettings(s, 'fileview')
            self.restoreGeometry(s.value('geom').toByteArray())
            self.splitter.restoreState(s.value('splitter').toByteArray())
            self.revpanel.set_expanded(s.value('revpanel.expanded').toBool())
        finally:
            s.endGroup()

    def _writeSettings(self):
        s = QSettings()
        s.beginGroup('filelog')
        try:
            self.textView.saveSettings(s, 'fileview')
            s.setValue('revpanel.expanded', self.revpanel.is_expanded())
            s.setValue('geom', self.saveGeometry())
            s.setValue('splitter', self.splitter.saveState())
        finally:
            s.endGroup()

        self.repoview.saveSettings()

    def setupUi(self):
        self.editToolbar = QToolBar(self)
        self.editToolbar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea(Qt.TopToolBarArea), self.editToolbar)
        self.actionClose = QAction(self)
        self.actionClose.setShortcuts(QKeySequence.Close)
        self.actionReload = QAction(self)
        self.actionReload.setShortcuts(QKeySequence.Refresh)
        self.editToolbar.addAction(self.actionReload)
        self.addAction(self.actionClose)

        self.splitter = QSplitter(Qt.Vertical)
        self.setCentralWidget(self.splitter)
        cs = ('fileLogDialog', _('File History Log Columns'))
        self.repoview = repoview.HgRepoView(self._repoagent, cs[0], cs,
                                            self.splitter)

        self.contentframe = QFrame(self.splitter)

        vbox = QVBoxLayout()
        vbox.setSpacing(0)
        vbox.setMargin(0)
        self.contentframe.setLayout(vbox)

        self.revpanel = revpanel.RevPanelWidget(self.repo)
        self.revpanel.linkActivated.connect(self.onLinkActivated)
        vbox.addWidget(self.revpanel, 0)

        self.textView = fileview.HgFileView(self._repoagent, self)
        self.textView.revisionSelected.connect(self.goto)
        vbox.addWidget(self.textView, 1)

    def setupViews(self):
        self.textView.showMessage.connect(self.statusBar().showMessage)

    def setupToolbars(self):
        self.editToolbar.addSeparator()
        self.editToolbar.addAction(self.actionBack)
        self.editToolbar.addAction(self.actionForward)

    def setupModels(self):
        self.filerevmodel = repomodel.FileRevModel(
            self._repoagent, self.filename, parent=self)
        self.repoview.setModel(self.filerevmodel)
        self.repoview.revisionSelected.connect(self.onRevisionSelected)
        self.repoview.revisionActivated.connect(self.onRevisionActivated)
        self.repoview.menuRequested.connect(self.viewMenuRequest)
        selmodel = self.repoview.selectionModel()
        selmodel.selectionChanged.connect(self._onRevisionSelectionChanged)
        self.filerevmodel.showMessage.connect(self.statusBar().showMessage)
        QTimer.singleShot(0, self._updateRepoViewForModel)

    def createActions(self):
        self.actionClose.triggered.connect(self.close)
        self.actionReload.triggered.connect(self.reload)
        self.actionReload.setIcon(qtlib.geticon('view-refresh'))

        self.actionBack = QAction(_('Back'), self, enabled=False,
                                  shortcut=QKeySequence.Back,
                                  icon=qtlib.geticon('go-previous'))
        self.actionForward = QAction(_('Forward'), self, enabled=False,
                                     shortcut=QKeySequence.Forward,
                                     icon=qtlib.geticon('go-next'))
        self.repoview.revisionSelected.connect(self._updateHistoryActions)
        self.actionBack.triggered.connect(self.repoview.back)
        self.actionForward.triggered.connect(self.repoview.forward)

        self._fileactions = filectxactions.FilectxActions(self._repoagent, self)
        self.addActions(self._fileactions.actions())

    def _updateFileActions(self):
        selmodel = self.repoview.selectionModel()
        selfds = _fileDataListForSelection(self.filerevmodel, selmodel)
        self._fileactions.setFileDataList(selfds)
        if len(selmodel.selectedRows()) > 1:
            texts = {'visualDiff': _('Diff Selected &Changesets'),
                     'visualDiffFile': _('&Diff Selected File Revisions')}
        else:
            texts = {'visualDiff': _('Diff &Changeset to Parent'),
                     'visualDiffFile': _('&Diff to Parent')}
        for n, t in texts.iteritems():
            self._fileactions.action(n).setText(t)

    @pyqtSlot()
    def _updateHistoryActions(self):
        self.actionBack.setEnabled(self.repoview.canGoBack())
        self.actionForward.setEnabled(self.repoview.canGoForward())

    @pyqtSlot()
    def _updateRepoViewForModel(self):
        self.repoview.resizeColumns()
        if self._show_rev is not None:
            index = self.filerevmodel.indexLinkedFromRev(self._show_rev)
            self._show_rev = None
        elif self.repoview.currentIndex().isValid():
            return  # already set by goto()
        else:
            index = self.filerevmodel.index(0,0)
        self.repoview.setCurrentIndex(index)

    @pyqtSlot(QPoint, object)
    def viewMenuRequest(self, point, selection):
        'User requested a context menu in repo view widget'
        if not selection or len(selection) > 2:
            return
        menu = QMenu(self)
        if len(selection) == 2:
            for name in ['visualDiff', 'visualDiffFile']:
                menu.addAction(self._fileactions.action(name))
        else:
            _setupFileMenu(menu, self._fileactions)
            menu.addSeparator()
            a = menu.addAction(_('Show Revision &Details'))
            a.setIcon(qtlib.geticon('hg-log'))
            a.triggered.connect(self.onShowRevisionDetails)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(point)

    def onShowRevisionDetails(self):
        rev = self.repoview.selectedRevisions()[0]
        if not self.revdetails:
            from tortoisehg.hgqt.revdetails import RevDetailsDialog
            self.revdetails = RevDetailsDialog(self._repoagent, rev=rev)
        else:
            self.revdetails.setRev(rev)
        self.revdetails.show()
        self.revdetails.raise_()

    @pyqtSlot(str)
    def onLinkActivated(self, link):
        link = unicode(link)
        if ':' in link:
            scheme, param = link.split(':', 1)
            if scheme == 'cset':
                rev = self.repo[hglib.fromunicode(param)].rev()
                return self.goto(rev)
        QDesktopServices.openUrl(QUrl(link))

    def onRevisionSelected(self, rev):
        pos = self.textView.verticalScrollBar().value()
        fd = self.filerevmodel.fileData(self.repoview.currentIndex())
        self.textView.display(fd)
        self.textView.verticalScrollBar().setValue(pos)
        self.revpanel.set_revision(rev)
        self.revpanel.update(repo = self.repo)

    @pyqtSlot()
    def _onRevisionSelectionChanged(self):
        self._checkValidSelection()
        self._updateFileActions()

    # It does not make sense to select more than two revisions at a time.
    # Rather than enforcing a max selection size we simply let the user
    # know when it has selected too many revisions by using the status bar
    def _checkValidSelection(self):
        selection = self.repoview.selectedRevisions()
        if len(selection) > 2:
            msg = _('Too many rows selected for menu')
        else:
            msg = ''
        self.textView.showMessage.emit(msg)

    def goto(self, rev):
        index = self.filerevmodel.indexLinkedFromRev(rev)
        if index.isValid():
            self.repoview.setCurrentIndex(index)
        else:
            self._show_rev = rev

    def showLine(self, line):
        self.textView.showLine(line - 1)  # fileview should do -1 instead?

    def setFileViewMode(self, mode):
        self.textView.setMode(mode)

    def setSearchPattern(self, text):
        self.textView.searchbar.setPattern(text)

    def setSearchCaseInsensitive(self, ignorecase):
        self.textView.searchbar.setCaseInsensitive(ignorecase)


class FileDiffDialog(_AbstractFileDialog):
    """
    Qt4 dialog to display diffs between different mercurial revisions of a file.
    """
    def __init__(self, repoagent, filename):
        super(FileDiffDialog, self).__init__(repoagent, filename)
        self._readSettings()

    def closeEvent(self, event):
        self._writeSettings()
        super(FileDiffDialog, self).closeEvent(event)

    def _readSettings(self):
        s = QSettings()
        s.beginGroup('filediff')
        try:
            self.restoreGeometry(s.value('geom').toByteArray())
            self.splitter.restoreState(s.value('splitter').toByteArray())
        finally:
            s.endGroup()

    def _writeSettings(self):
        s = QSettings()
        s.beginGroup('filediff')
        try:
            s.setValue('geom', self.saveGeometry())
            s.setValue('splitter', self.splitter.saveState())
        finally:
            s.endGroup()

        for w in self._repoViews:
            w.saveSettings()

    def setupUi(self):
        self.editToolbar = QToolBar(self)
        self.editToolbar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea(Qt.TopToolBarArea), self.editToolbar)
        self.actionClose = QAction(self)
        self.actionClose.setShortcuts(QKeySequence.Close)
        self.actionReload = QAction(self)
        self.actionReload.setShortcuts(QKeySequence.Refresh)
        self.editToolbar.addAction(self.actionReload)
        self.addAction(self.actionClose)

        def layouttowidget(layout):
            w = QWidget()
            w.setLayout(layout)
            return w

        self.splitter = QSplitter(Qt.Vertical)
        self.setCentralWidget(self.splitter)
        self.horizontalLayout = QHBoxLayout()
        self._repoViews = []
        cs = ('fileDiffDialogLeft', _('File Differences Log Columns'))
        for cfgname in [cs[0], 'fileDiffDialogRight']:
            w = repoview.HgRepoView(self._repoagent, cfgname, cs, self)
            w.setSelectionMode(QAbstractItemView.SingleSelection)
            self.horizontalLayout.addWidget(w)
            self._repoViews.append(w)
        self.frame = QFrame()
        self.splitter.addWidget(layouttowidget(self.horizontalLayout))
        self.splitter.addWidget(self.frame)

    def setupViews(self):
        # viewers are Scintilla editors
        self.viewers = {}
        # block are diff-block displayers
        self.block = {}
        self.diffblock = blockmatcher.BlockMatch(self.frame)
        lay = QHBoxLayout(self.frame)
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)

        try:
            contents = open(self.repo.wjoin(self.filename), "rb").read(1024)
            lexer = lexers.getlexer(self.repo.ui, self.filename, contents, self)
        except Exception:
            lexer = None

        for side, idx  in (('left', 0), ('right', 3)):
            sci = _FileDiffScintilla(self.frame)
            sci.installEventFilter(self)
            sci.verticalScrollBar().setFocusPolicy(Qt.StrongFocus)
            sci.setFocusProxy(sci.verticalScrollBar())
            sci.verticalScrollBar().installEventFilter(self)

            sci.setFrameShape(QFrame.NoFrame)
            sci.setMarginLineNumbers(1, True)
            sci.SendScintilla(sci.SCI_SETSELEOLFILLED, True)

            sci.setLexer(lexer)
            if lexer is None:
                sci.setFont(qtlib.getfont('fontdiff').font())

            sci.setReadOnly(True)
            sci.setUtf8(True)
            lay.addWidget(sci)

            # hide margin 0 (markers)
            sci.SendScintilla(sci.SCI_SETMARGINTYPEN, 0, 0)
            sci.SendScintilla(sci.SCI_SETMARGINWIDTHN, 0, 0)
            # setup margin 1 for line numbers only
            sci.SendScintilla(sci.SCI_SETMARGINTYPEN, 1, 1)
            sci.SendScintilla(sci.SCI_SETMARGINWIDTHN, 1, 20)
            sci.SendScintilla(sci.SCI_SETMARGINMASKN, 1, 0)

            # define markers for colorize zones of diff
            self.markerplus = sci.markerDefine(QsciScintilla.Background)
            sci.setMarkerBackgroundColor(_colormap['+'], self.markerplus)
            self.markerminus = sci.markerDefine(QsciScintilla.Background)
            sci.setMarkerBackgroundColor(_colormap['-'], self.markerminus)
            self.markertriangle = sci.markerDefine(QsciScintilla.Background)
            sci.setMarkerBackgroundColor(_colormap['x'], self.markertriangle)

            self.markerplusline = sci.markerDefine(QsciScintilla.Invisible,
                                                   _MARKERPLUSLINE)
            self.markerminusline = sci.markerDefine(QsciScintilla.Invisible,
                                                    _MARKERMINUSLINE)
            self.markerplusunderline = sci.markerDefine(QsciScintilla.Invisible,
                                                        _MARKERPLUSUNDERLINE)
            self.markerminusunderline = sci.markerDefine(QsciScintilla.Invisible,
                                                         _MARKERMINUSUNDERLINE)

            self.viewers[side] = sci
            blk = blockmatcher.BlockList(self.frame)
            blk.linkScrollBar(sci.verticalScrollBar())
            self.diffblock.linkScrollBar(sci.verticalScrollBar(), side)
            lay.insertWidget(idx, blk)
            self.block[side] = blk
        lay.insertWidget(2, self.diffblock)

        for table in self._repoViews:
            table.setTabKeyNavigation(False)
            table.installEventFilter(self)
            table.columnsVisibilityChanged.connect(self._syncColumnsVisibility)
            table.revisionSelected.connect(self.onRevisionSelected)
            table.revisionActivated.connect(self.onRevisionActivated)

        l, r = (self.viewers[k].verticalScrollBar() for k in sides)
        l.valueChanged.connect(self.sbar_changed_left)
        r.valueChanged.connect(self.sbar_changed_right)

        l, r = (self.viewers[k].horizontalScrollBar() for k in sides)
        l.valueChanged.connect(r.setValue)
        r.valueChanged.connect(l.setValue)

        self.setTabOrder(table, self.viewers['left'])
        self.setTabOrder(self.viewers['left'], self.viewers['right'])

        # timer used to merge requests of syncPageStep on ResizeEvent
        self._delayedSyncPageStep = QTimer(self, interval=0, singleShot=True)
        self._delayedSyncPageStep.timeout.connect(self.diffblock.syncPageStep)

        # timer used to fill viewers with diff block markers during GUI idle time
        self.timer = QTimer()
        self.timer.setSingleShot(False)
        self.timer.timeout.connect(self.idle_fill_files)

    def setupModels(self):
        self.filedata = {'left': None, 'right': None}
        self._invbarchanged = False
        self.filerevmodel = repomodel.FileRevModel(
            self._repoagent, self.filename, parent=self)
        for w in self._repoViews:
            w.setModel(self.filerevmodel)
            w.menuRequested.connect(self.viewMenuRequest)
            selmodel = w.selectionModel()
            selmodel.selectionChanged.connect(self._onRevisionSelectionChanged)
        QTimer.singleShot(0, self._updateRepoViewForModel)

    def createActions(self):
        self.actionClose.triggered.connect(self.close)
        self.actionReload.triggered.connect(self.reload)
        self.actionReload.setIcon(qtlib.geticon('view-refresh'))

        self.actionNextDiff = QAction(qtlib.geticon('go-down'),
                                      _('Next diff'), self)
        self.actionNextDiff.setShortcut('Alt+Down')
        self.actionNextDiff.triggered.connect(self.nextDiff)

        self.actionPrevDiff = QAction(qtlib.geticon('go-up'),
                                      _('Previous diff'), self)
        self.actionPrevDiff.setShortcut('Alt+Up')
        self.actionPrevDiff.triggered.connect(self.prevDiff)

        self.actionNextDiff.setEnabled(False)
        self.actionPrevDiff.setEnabled(False)

        self._fileactions = filectxactions.FilectxActions(self._repoagent, self)
        self.addActions(self._fileactions.actions())

    def _updateFileActionsForSelection(self, selmodel):
        selfds = _fileDataListForSelection(self.filerevmodel, selmodel)
        self._fileactions.setFileDataList(selfds)

    def setupToolbars(self):
        self.editToolbar.addSeparator()
        self.editToolbar.addAction(self.actionNextDiff)
        self.editToolbar.addAction(self.actionPrevDiff)

    @pyqtSlot()
    def _updateRepoViewForModel(self):
        for w in self._repoViews:
            w.resizeColumns()
        if self._show_rev is not None:
            self.goto(self._show_rev)
            self._show_rev = None
        elif self._repoViews[0].currentIndex().isValid():
            return  # already set by goto()
        elif len(self.filerevmodel.graph):
            self.goto(self.filerevmodel.graph[0].rev)

    def eventFilter(self, watched, event):
        if watched in self.viewers.values():
            # copy page steps to diffblock _after_ viewers are resized; resize
            # events will be posted in arbitrary order.
            if event.type() == QEvent.Resize:
                self._delayedSyncPageStep.start()
            return False
        elif watched in self._repoViews:
            if event.type() == QEvent.FocusIn:
                self._updateFileActionsForSelection(watched.selectionModel())
            return False
        else:
            return super(FileDiffDialog, self).eventFilter(watched, event)

    def onRevisionSelected(self, rev):
        if rev is None or rev not in self.filerevmodel.graph.nodesdict:
            return
        if self.sender() is self._repoViews[1]:
            side = 'right'
        else:
            side = 'left'
        path = self.filerevmodel.graph.nodesdict[rev].extra[0]
        fc = self.repo.changectx(rev).filectx(path)
        data = hglib.tounicode(fc.data())
        self.filedata[side] = data.splitlines()
        self.update_diff(keeppos=otherside[side])

    @qtlib.senderSafeSlot()
    def _onRevisionSelectionChanged(self):
        assert isinstance(self.sender(), QItemSelectionModel)
        self._updateFileActionsForSelection(self.sender())

    def goto(self, rev):
        index = self.filerevmodel.indexLinkedFromRev(rev)
        if index.isValid():
            if index.row() == 0:
                index = self.filerevmodel.index(1, 0)
            self._repoViews[0].setCurrentIndex(index)
            index = self.filerevmodel.index(0, 0)
            self._repoViews[1].setCurrentIndex(index)
        else:
            self._show_rev = rev

    def setDiffNavActions(self, pos=0):
        hasdiff = (self.diffblock.nDiffs() > 0)
        self.actionNextDiff.setEnabled(hasdiff and pos != 1)
        self.actionPrevDiff.setEnabled(hasdiff and pos != -1)

    def nextDiff(self):
        self.setDiffNavActions(self.diffblock.nextDiff())

    def prevDiff(self):
        self.setDiffNavActions(self.diffblock.prevDiff())

    def update_page_steps(self, keeppos=None):
        for side in sides:
            self.block[side].syncPageStep()
        self.diffblock.syncPageStep()
        if keeppos:
            side, pos = keeppos
            self.viewers[side].verticalScrollBar().setValue(pos)

    def idle_fill_files(self):
        # we make a burst of diff-lines computed at once, but we
        # disable GUI updates for efficiency reasons, then only
        # refresh GUI at the end of the burst
        for side in sides:
            self.viewers[side].setUpdatesEnabled(False)
            self.block[side].setUpdatesEnabled(False)
        self.diffblock.setUpdatesEnabled(False)

        for n in range(30): # burst pool
            if self._diff is None or not self._diff.get_opcodes():
                self._diff = None
                self.timer.stop()
                self.setDiffNavActions(-1)
                break

            tag, alo, ahi, blo, bhi = self._diff.get_opcodes().pop(0)

            w = self.viewers['left']
            cposl = w.SendScintilla(w.SCI_GETENDSTYLED)
            w = self.viewers['right']
            cposr = w.SendScintilla(w.SCI_GETENDSTYLED)
            if tag == 'replace':
                self.block['left'].addBlock('x', alo, ahi)
                self.block['right'].addBlock('x', blo, bhi)
                self.diffblock.addBlock('x', alo, ahi, blo, bhi)

                w = self.viewers['left']
                for i in range(alo, ahi):
                    w.markerAdd(i, self.markertriangle)

                w = self.viewers['right']
                for i in range(blo, bhi):
                    w.markerAdd(i, self.markertriangle)

            elif tag == 'delete':
                self.block['left'].addBlock('-', alo, ahi)
                self.diffblock.addBlock('-', alo, ahi, blo, bhi)

                w = self.viewers['left']
                for i in range(alo, ahi):
                    w.markerAdd(i, self.markerminus)

                w = self.viewers['right']
                if blo < w.lines():
                    w.markerAdd(blo, self.markerminusline)
                else:
                    w.markerAdd(blo - 1, self.markerminusunderline)

            elif tag == 'insert':
                self.block['right'].addBlock('+', blo, bhi)
                self.diffblock.addBlock('+', alo, ahi, blo, bhi)

                w = self.viewers['left']
                if alo < w.lines():
                    w.markerAdd(alo, self.markerplusline)
                else:
                    w.markerAdd(alo - 1, self.markerplusunderline)

                w = self.viewers['right']
                for i in range(blo, bhi):
                    w.markerAdd(i, self.markerplus)

            elif tag == 'equal':
                pass

            else:
                raise ValueError, 'unknown tag %r' % (tag,)

        # ok, let's enable GUI refresh for code viewers and diff-block displayers
        for side in sides:
            self.viewers[side].setUpdatesEnabled(True)
            self.block[side].setUpdatesEnabled(True)
        self.diffblock.setUpdatesEnabled(True)

    def update_diff(self, keeppos=None):
        """
        Recompute the diff, display files and starts the timer
        responsible for filling diff markers
        """
        if keeppos:
            pos = self.viewers[keeppos].verticalScrollBar().value()
            keeppos = (keeppos, pos)

        for side in sides:
            self.viewers[side].clear()
            self.block[side].clear()
        self.diffblock.clear()

        if None not in self.filedata.values():
            if self.timer.isActive():
                self.timer.stop()
            for side in sides:
                self.viewers[side].setMarginWidth(1, "00%s" % len(self.filedata[side]))

            self._diff = difflib.SequenceMatcher(None, self.filedata['left'],
                                                 self.filedata['right'])
            blocks = self._diff.get_opcodes()[:]

            self._diffmatch = {'left': [x[1:3] for x in blocks],
                               'right': [x[3:5] for x in blocks]}
            for side in sides:
                self.viewers[side].setText(u'\n'.join(self.filedata[side]))
            self.update_page_steps(keeppos)
            self.timer.start()

    @qtlib.senderSafeSlot()
    def _syncColumnsVisibility(self):
        src = self.sender()
        dest = dict(zip(self._repoViews, reversed(self._repoViews)))[src]
        dest.setVisibleColumns(src.visibleColumns())

    @pyqtSlot(int)
    def sbar_changed_left(self, value):
        self.sbar_changed(value, 'left')

    @pyqtSlot(int)
    def sbar_changed_right(self, value):
        self.sbar_changed(value, 'right')

    def sbar_changed(self, value, side):
        """
        Callback called when a scrollbar of a file viewer
        is changed, so we can update the position of the other file
        viewer.
        """
        if self._invbarchanged or not hasattr(self, '_diffmatch'):
            # prevent loops in changes (left -> right -> left ...)
            return
        self._invbarchanged = True
        oside = otherside[side]

        for i, (lo, hi) in enumerate(self._diffmatch[side]):
            if lo <= value < hi:
                break
        dv = value - lo

        blo, bhi = self._diffmatch[oside][i]
        vbar = self.viewers[oside].verticalScrollBar()
        if (dv) < (bhi - blo):
            bvalue = blo + dv
        else:
            bvalue = bhi
        vbar.setValue(bvalue)
        self._invbarchanged = False

    @pyqtSlot(QPoint, object)
    def viewMenuRequest(self, point, selection):
        'User requested a context menu in repo view widget'
        if not selection:
            return
        menu = QMenu(self)
        _setupFileMenu(menu, self._fileactions)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(point)
