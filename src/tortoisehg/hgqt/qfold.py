# qfold.py - QFold dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from hgext import mq

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qscilib, qtlib, messageentry

class QFoldDialog(QDialog):

    def __init__(self, repoagent, patches, parent):
        super(QFoldDialog, self).__init__(parent)
        self._repoagent = repoagent
        self.setWindowTitle(_('Patch fold - %s') % repoagent.displayName())
        self.setWindowIcon(qtlib.geticon('hg-qfold'))

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint
                            | Qt.WindowMaximizeButtonHint)

        self.setLayout(QVBoxLayout())

        mlbl = QLabel(_('New patch message:'))
        self.layout().addWidget(mlbl)
        self.msgte = messageentry.MessageEntry(self)
        self.msgte.installEventFilter(qscilib.KeyPressInterceptor(self))
        self.layout().addWidget(self.msgte)

        self.keepchk = QCheckBox(_('Keep patch files'))
        self.keepchk.setChecked(True)
        self.layout().addWidget(self.keepchk)

        q = self.repo.mq
        q.parseseries()
        patches = [p for p in q.series if p in patches]

        class PatchListWidget(QListWidget):
            def __init__(self, parent):
                QListWidget.__init__(self, parent)
                self.setCurrentRow(0)
            def focusInEvent(self, event):
                i = self.item(self.currentRow())
                if i:
                    self.parent().parent().showSummary(i)
                QListWidget.focusInEvent(self, event)
            def dropEvent(self, event):
                QListWidget.dropEvent(self, event)
                spp = self.parent().parent()
                spp.msgte.setText(spp.composeMsg(self.getPatchList()))
            def getPatchList(self):
                return [hglib.fromunicode(self.item(i).text()) \
                        for i in xrange(0, self.count())]

        ugb = QGroupBox(_('Patches to fold'))
        ugb.setLayout(QVBoxLayout())
        ugb.layout().setContentsMargins(*(0,)*4)
        self.ulw = PatchListWidget(self)
        self.ulw.setDragDropMode(QListView.InternalMove)
        ugb.layout().addWidget(self.ulw)
        self.ulw.currentItemChanged.connect(lambda:
                self.showSummary(self.ulw.item(self.ulw.currentRow())))
        self.layout().addWidget(ugb)

        for p in patches:
            item = QListWidgetItem(hglib.tounicode(p))
            item.setFlags(Qt.ItemIsSelectable |
                          Qt.ItemIsEnabled |
                          Qt.ItemIsDragEnabled)
            self.ulw.addItem(item)

        slbl = QLabel(_('Summary:'))
        self.layout().addWidget(slbl)
        self.summ = QTextEdit()
        self.summ.setFont(qtlib.getfont('fontcomment').font())
        self.summ.setMaximumHeight(80)
        self.summ.setReadOnly(True)
        self.summ.setFocusPolicy(Qt.NoFocus)
        self.layout().addWidget(self.summ)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        QShortcut('Ctrl+Return', self, self.accept)
        QShortcut('Ctrl+Enter', self, self.accept)

        self._repoagent.configChanged.connect(self.configChanged)

        self._readsettings()

        self.msgte.setText(self.composeMsg(patches))
        self.msgte.refresh(self.repo)

    @property
    def repo(self):
        return self._repoagent.rawRepo()

    def showSummary(self, item):
        patchname = hglib.fromunicode(item.text())
        txt = '\n'.join(mq.patchheader(self.repo.mq.join(patchname)).message)
        self.summ.setText(hglib.tounicode(txt))

    def composeMsg(self, patches):
        return u'\n* * *\n'.join(
              [hglib.tounicode(self.repo.changectx(p).description())
               for p in ['qtip'] + patches])

    @pyqtSlot()
    def configChanged(self):
        '''Repository is reporting its config files have changed'''
        self.msgte.refresh(self.repo)

    def options(self):
        return {'keep': self.keepchk.isChecked(),
                'message': unicode(self.msgte.text())}

    def patches(self):
        return map(hglib.tounicode, self.ulw.getPatchList())

    def accept(self):
        self._writesettings()
        QDialog.accept(self)

    def closeEvent(self, event):
        self._writesettings()
        super(QFoldDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('qfold/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('qfold/geom', self.saveGeometry())
