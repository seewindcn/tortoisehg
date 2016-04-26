# guess.py - TortoiseHg's dialogs for detecting copies and renames
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from mercurial import hg, ui, mdiff, similar, patch

from tortoisehg.util import hglib, thread2
from tortoisehg.util.i18n import _

from tortoisehg.hgqt import qtlib, htmlui, cmdui

from PyQt4.QtCore import *
from PyQt4.QtGui import *

# Techincal debt
# Try to cut down on the jitter when findRenames is pressed.  May
# require a splitter.

class DetectRenameDialog(QDialog):
    'Detect renames after they occur'
    matchAccepted = pyqtSignal()

    def __init__(self, repoagent, parent, *pats):
        QDialog.__init__(self, parent)

        self._repoagent = repoagent
        self.pats = pats
        self.thread = None

        self.setWindowTitle(_('Detect Copies/Renames in %s')
                            % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('thg-guess'))
        self.setWindowFlags(Qt.Window)

        layout = QVBoxLayout()
        layout.setContentsMargins(*(2,)*4)
        self.setLayout(layout)

        # vsplit for top & diff
        vsplit = QSplitter(Qt.Horizontal)
        utframe = QFrame(vsplit)
        matchframe = QFrame(vsplit)

        utvbox = QVBoxLayout()
        utvbox.setContentsMargins(*(2,)*4)
        utframe.setLayout(utvbox)
        matchvbox = QVBoxLayout()
        matchvbox.setContentsMargins(*(2,)*4)
        matchframe.setLayout(matchvbox)

        hsplit = QSplitter(Qt.Vertical)
        layout.addWidget(hsplit)
        hsplit.addWidget(vsplit)
        utheader = QHBoxLayout()
        utvbox.addLayout(utheader)

        utlbl = QLabel(_('<b>Unrevisioned Files</b>'))
        utheader.addWidget(utlbl)

        self.refreshBtn = tb = QToolButton()
        tb.setToolTip(_('Refresh file list'))
        tb.setIcon(qtlib.geticon('view-refresh'))
        tb.clicked.connect(self.refresh)
        utheader.addWidget(tb)

        self.unrevlist = QListWidget()
        self.unrevlist.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.unrevlist.doubleClicked.connect(self.onUnrevDoubleClicked)
        utvbox.addWidget(self.unrevlist)

        simhbox = QHBoxLayout()
        utvbox.addLayout(simhbox)
        lbl = QLabel()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setTickInterval(10)
        slider.setPageStep(10)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.changefunc = lambda v: lbl.setText(
                            _('Min Similarity: %d%%') % v)
        slider.valueChanged.connect(slider.changefunc)
        self.simslider = slider
        lbl.setBuddy(slider)
        simhbox.addWidget(lbl)
        simhbox.addWidget(slider, 1)

        buthbox = QHBoxLayout()
        utvbox.addLayout(buthbox)
        copycheck = QCheckBox(_('Only consider deleted files'))
        copycheck.setToolTip(_('Uncheck to consider all revisioned files '
                               'for copy sources'))
        copycheck.setChecked(True)
        findrenames = QPushButton(_('Find Renames'))
        findrenames.setToolTip(_('Find copy and/or rename sources'))
        findrenames.setEnabled(False)
        findrenames.clicked.connect(self.findRenames)
        buthbox.addWidget(copycheck)
        buthbox.addStretch(1)
        buthbox.addWidget(findrenames)
        self.findbtn, self.copycheck = findrenames, copycheck

        matchlbl = QLabel(_('<b>Candidate Matches</b>'))
        matchvbox.addWidget(matchlbl)
        matchtv = QTreeView()
        matchtv.setSelectionMode(QTreeView.ExtendedSelection)
        matchtv.setItemsExpandable(False)
        matchtv.setRootIsDecorated(False)
        matchtv.setModel(MatchModel())
        matchtv.setSortingEnabled(True)
        matchtv.selectionModel().selectionChanged.connect(self.showDiff)
        buthbox = QHBoxLayout()
        matchbtn = QPushButton(_('Accept All Matches'))
        matchbtn.clicked.connect(self.acceptMatch)
        matchbtn.setEnabled(False)
        buthbox.addStretch(1)
        buthbox.addWidget(matchbtn)
        matchvbox.addWidget(matchtv)
        matchvbox.addLayout(buthbox)
        self.matchtv, self.matchbtn = matchtv, matchbtn
        def matchselect(s, d):
            count = len(matchtv.selectedIndexes())
            if count:
                self.matchbtn.setText(_('Accept Selected Matches'))
            else:
                self.matchbtn.setText(_('Accept All Matches'))
        selmodel = matchtv.selectionModel()
        selmodel.selectionChanged.connect(matchselect)

        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sp.setHorizontalStretch(1)
        matchframe.setSizePolicy(sp)

        diffframe = QFrame(hsplit)
        diffvbox = QVBoxLayout()
        diffvbox.setContentsMargins(*(2,)*4)
        diffframe.setLayout(diffvbox)

        difflabel = QLabel(_('<b>Differences from Source to Dest</b>'))
        diffvbox.addWidget(difflabel)
        difftb = QTextBrowser()
        difftb.document().setDefaultStyleSheet(qtlib.thgstylesheet)
        diffvbox.addWidget(difftb)
        self.difftb = difftb

        self.stbar = cmdui.ThgStatusBar()
        layout.addWidget(self.stbar)

        s = QSettings()
        self.restoreGeometry(s.value('guess/geom').toByteArray())
        hsplit.restoreState(s.value('guess/hsplit-state').toByteArray())
        vsplit.restoreState(s.value('guess/vsplit-state').toByteArray())
        slider.setValue(s.value('guess/simslider').toInt()[0] or 50)
        self.vsplit, self.hsplit = vsplit, hsplit
        QTimer.singleShot(0, self.refresh)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def refresh(self):
        self.repo.thginvalidate()
        self.repo.lfstatus = True
        wctx = self.repo[None]
        ws = wctx.status(listunknown=True)
        self.repo.lfstatus = False
        self.unrevlist.clear()
        dests = []
        for u in ws.unknown:
            dests.append(u)
        for a in ws.added:
            if not wctx[a].renamed():
                dests.append(a)
        for x in dests:
            item = QListWidgetItem(hglib.tounicode(x))
            item.orig = x
            self.unrevlist.addItem(item)
            self.unrevlist.setItemSelected(item, x in self.pats)
        if dests:
            self.findbtn.setEnabled(True)
        else:
            self.findbtn.setEnabled(False)
        self.difftb.clear()
        self.pats = []
        self.matchbtn.setEnabled(len(self.matchtv.model().rows))

    def findRenames(self):
        'User pressed "find renames" button'
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, _('Search already in progress'),
                                    _('Cannot start a new search'))
            return

        ulist = [it.orig for it in self.unrevlist.selectedItems()]
        if not ulist:
            # When no files are selected, look for all files
            ulist = [self.unrevlist.item(n).orig
                        for n in range(self.unrevlist.count())]

        if not ulist:
            QMessageBox.information(self, _('No files to find'),
                _('There are no files that may have been renamed'))
            return

        pct = self.simslider.value() / 100.0
        copies = not self.copycheck.isChecked()
        self.findbtn.setEnabled(False)

        self.matchtv.model().clear()
        self.thread = RenameSearchThread(self.repo, ulist, pct, copies)
        self.thread.match.connect(self.rowReceived)
        self.thread.progress.connect(self.stbar.progress)
        self.thread.showMessage.connect(self.stbar.showMessage)
        self.thread.finished.connect(self.searchfinished)
        self.thread.start()

    def searchfinished(self):
        self.stbar.clearProgress()
        for col in xrange(3):
            self.matchtv.resizeColumnToContents(col)
        self.findbtn.setEnabled(self.unrevlist.count())
        self.matchbtn.setEnabled(len(self.matchtv.model().rows))

    def rowReceived(self, args):
        self.matchtv.model().appendRow(*args)

    def acceptMatch(self):
        'User pressed "accept match" button'
        remdests = {}
        wctx = self.repo[None]
        m = self.matchtv.model()

        # If no rows are selected, ask the user if he'd like to accept all renames
        if self.matchtv.selectionModel().hasSelection():
            itemList = [self.matchtv.model().getRow(index) \
                for index in self.matchtv.selectionModel().selectedRows()]
        else:
            itemList = m.rows

        for item in itemList:
            src, dest, percent = item
            if dest in remdests:
                udest = hglib.tounicode(dest)
                QMessageBox.warning(self, _('Multiple sources chosen'),
                    _('You have multiple renames selected for '
                      'destination file:\n%s. Aborting!') % udest)
                return
            remdests[dest] = src
        for dest, src in remdests.iteritems():
            if not os.path.exists(self.repo.wjoin(src)):
                wctx.forget([src]) # !->R
            wctx.copy(src, dest)
            self.matchtv.model().remove(dest)
        self.matchAccepted.emit()
        self.refresh()

    def showDiff(self, index):
        'User selected a row in the candidate tree'
        indexes = index.indexes()
        if not indexes:
            return
        index = indexes[0]
        ctx = self.repo['.']
        hu = htmlui.htmlui()
        row = self.matchtv.model().getRow(index)
        src, dest, percent = self.matchtv.model().getRow(index)
        aa = self.repo.wread(dest)
        rr = ctx.filectx(src).data()
        date = hglib.displaytime(ctx.date())
        difftext = mdiff.unidiff(rr, date, aa, date, src, dest)
        if not difftext:
            t = _('%s and %s have identical contents\n\n') % \
                    (hglib.tounicode(src), hglib.tounicode(dest))
            hu.write(t, label='ui.error')
        else:
            for t, l in patch.difflabel(difftext.splitlines, True):
                hu.write(t, label=l)
        self.difftb.setHtml(hu.getdata()[0])

    def onUnrevDoubleClicked(self, index):
        file = hglib.fromunicode(self.unrevlist.model().data(index).toString())
        qtlib.editfiles(self.repo, [file])

    def accept(self):
        s = QSettings()
        s.setValue('guess/geom', self.saveGeometry())
        s.setValue('guess/vsplit-state', self.vsplit.saveState())
        s.setValue('guess/hsplit-state', self.hsplit.saveState())
        s.setValue('guess/simslider', self.simslider.value())
        QDialog.accept(self)

    def reject(self):
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            if self.thread.wait(2000):
                self.thread = None
        else:
            s = QSettings()
            s.setValue('guess/geom', self.saveGeometry())
            s.setValue('guess/vsplit-state', self.vsplit.saveState())
            s.setValue('guess/hsplit-state', self.hsplit.saveState())
            s.setValue('guess/simslider', self.simslider.value())
            QDialog.reject(self)


def _aspercent(s):
    # i18n: percent format
    return _('%d%%') % (s * 100)

class MatchModel(QAbstractTableModel):
    def __init__(self, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self.rows = []
        self.headers = (_('Source'), _('Dest'), _('% Match'))
        self.displayformats = (hglib.tounicode, hglib.tounicode, _aspercent)

    def rowCount(self, parent):
        return len(self.rows)

    def columnCount(self, parent):
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            s = self.rows[index.row()][index.column()]
            f = self.displayformats[index.column()]
            return QVariant(f(s))
        '''
        elif role == Qt.TextColorRole:
            src, dst, pct = self.rows[index.row()]
            if pct == 1.0:
                return QColor('green')
            else:
                return QColor('black')
        elif role == Qt.ToolTipRole:
            # explain what row means?
        '''
        return QVariant()

    def headerData(self, col, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    # Custom methods

    def getRow(self, index):
        assert index.isValid()
        return self.rows[index.row()]

    def appendRow(self, *args):
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(args)
        self.endInsertRows()
        self.layoutChanged.emit()

    def clear(self):
        self.beginRemoveRows(QModelIndex(), 0, len(self.rows)-1)
        self.rows = []
        self.endRemoveRows()
        self.layoutChanged.emit()

    def remove(self, dest):
        i = 0
        while i < len(self.rows):
            if self.rows[i][1] == dest:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.rows.pop(i)
                self.endRemoveRows()
            else:
                i += 1
        self.layoutChanged.emit()

    def sort(self, col, order):
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda x: x[col],
                       reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()
        self.reset()

    def isEmpty(self):
        return not bool(self.rows)

class RenameSearchThread(QThread):
    '''Background thread for searching repository history'''
    match = pyqtSignal(object)
    progress = pyqtSignal(str, object, str, str, object)
    showMessage = pyqtSignal(str)

    def __init__(self, repo, ufiles, minpct, copies):
        super(RenameSearchThread, self).__init__()
        self.repo = hg.repository(ui.ui(), repo.root)
        self.ufiles = ufiles
        self.minpct = minpct
        self.copies = copies
        self.threadid = None

    def run(self):
        def emit(topic, pos, item='', unit='', total=None):
            topic = hglib.tounicode(topic or '')
            item = hglib.tounicode(item or '')
            unit = hglib.tounicode(unit or '')
            self.progress.emit(topic, pos, item, unit, total)
        self.repo.ui.progress = emit
        self.threadid = int(self.currentThreadId())
        try:
            self.search(self.repo)
        except KeyboardInterrupt:
            pass
        except Exception, e:
            self.showMessage.emit(hglib.tounicode(str(e)))
        finally:
            self.threadid = None

    def cancel(self):
        tid = self.threadid
        if tid is None:
            return
        try:
            thread2._async_raise(tid, KeyboardInterrupt)
        except ValueError:
            pass

    def search(self, repo):
        wctx = repo[None]
        pctx = repo['.']
        if self.copies:
            ws = wctx.status(listclean=True)
            srcs = ws.removed + ws.deleted
            srcs += ws.modified + ws.clean
        else:
            ws = wctx.status()
            srcs = ws.removed + ws.deleted
        added = [wctx[a] for a in sorted(self.ufiles)]
        removed = [pctx[a] for a in sorted(srcs) if a in pctx]
        # do not consider files of zero length
        added = [fctx for fctx in added if fctx.size() > 0]
        removed = [fctx for fctx in removed if fctx.size() > 0]
        exacts = []
        gen = similar._findexactmatches(repo, added, removed)
        for o, n in gen:
            old, new = o.path(), n.path()
            exacts.append(old)
            self.match.emit([old, new, 1.0])
        if self.minpct == 1.0:
            return
        removed = [r for r in removed if r.path() not in exacts]
        gen = similar._findsimilarmatches(repo, added, removed, self.minpct)
        for o, n, s in gen:
            old, new, sim = o.path(), n.path(), s
            self.match.emit([old, new, sim])
