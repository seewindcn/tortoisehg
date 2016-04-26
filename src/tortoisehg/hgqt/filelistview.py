# Copyright (c) 2009-2010 LOGILAB S.A. (Paris, FRANCE).
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

from tortoisehg.util import hglib
from tortoisehg.hgqt import qtlib

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class HgFileListView(QTreeView):
    """Display files and statuses between two revisions or patch"""

    fileSelected = pyqtSignal(str, str)
    clearDisplay = pyqtSignal()

    def __init__(self, parent):
        QTreeView.__init__(self, parent)
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setRootIsDecorated(False)
        self.setTextElideMode(Qt.ElideLeft)

        # give consistent height and enable optimization
        self.setIconSize(qtlib.smallIconSize())
        self.setUniformRowHeights(True)

    def setModel(self, model):
        QTreeView.setModel(self, model)
        model.layoutChanged.connect(self._onLayoutChanged)
        model.revLoaded.connect(self._onRevLoaded)
        self.selectionModel().currentRowChanged.connect(self._emitFileChanged)

    def currentFile(self):
        index = self.currentIndex()
        return hglib.fromunicode(self.model().filePath(index))

    def setCurrentFile(self, path):
        model = self.model()
        model.fetchMore(QModelIndex())  # make sure path is populated
        self.setCurrentIndex(model.indexFromPath(hglib.tounicode(path)))

    def getSelectedFiles(self):
        model = self.model()
        return [hglib.fromunicode(model.filePath(index))
                for index in self.selectedRows()]

    def _initCurrentIndex(self):
        m = self.model()
        if m.rowCount() > 0:
            self.setCurrentIndex(m.index(0, 0))
        else:
            self.clearDisplay.emit()

    @pyqtSlot()
    def _onLayoutChanged(self):
        index = self.currentIndex()
        if index.isValid():
            self.scrollTo(index)
            return
        self._initCurrentIndex()

    @pyqtSlot()
    def _onRevLoaded(self):
        index = self.currentIndex()
        if index.isValid():
            # redisplay previous row
            self._emitFileChanged()
        else:
            self._initCurrentIndex()

    @pyqtSlot()
    def _emitFileChanged(self):
        index = self.currentIndex()
        m = self.model()
        if index.isValid():
            # TODO: delete status from fileSelected because it isn't primitive
            # pseudo directory node has no status
            st = m.fileStatus(index) or ''
            self.fileSelected.emit(m.filePath(index), st)
        else:
            self.clearDisplay.emit()

    def selectedRows(self):
        return self.selectionModel().selectedRows()
