# webconf.py - Widget to show/edit hgweb config
#
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from tortoisehg.util import hglib, wconfig
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib
from tortoisehg.hgqt.webconf_ui import Ui_WebconfForm

_FILE_FILTER = ';;'.join([_('Config files (*.conf *.config *.ini)'),
                          _('All files (*)')])

class WebconfForm(QWidget):
    """Widget to show/edit webconf"""
    def __init__(self, parent=None, webconf=None):
        super(WebconfForm, self).__init__(parent, acceptDrops=True)
        self._qui = Ui_WebconfForm()
        self._qui.setupUi(self)
        self._initicons()
        self._qui.path_edit.currentIndexChanged.connect(self._updateview)
        self._qui.path_edit.currentIndexChanged.connect(self._updateform)
        self._qui.add_button.clicked.connect(self._addpathmap)

        self.setwebconf(webconf or wconfig.config())
        self._updateform()

    def _initicons(self):
        def setstdicon(w, name):
            w.setIcon(self.style().standardIcon(name))

        setstdicon(self._qui.open_button, QStyle.SP_DialogOpenButton)
        setstdicon(self._qui.save_button, QStyle.SP_DialogSaveButton)
        self._qui.add_button.setIcon(qtlib.geticon('hg-add'))
        self._qui.edit_button.setIcon(qtlib.geticon('edit-file'))
        self._qui.remove_button.setIcon(qtlib.geticon('hg-remove'))

    def dragEnterEvent(self, event):
        if self._getlocalpath_from_dropevent(event):
            event.setDropAction(Qt.LinkAction)
            event.accept()

    def dropEvent(self, event):
        localpath = self._getlocalpath_from_dropevent(event)
        if localpath:
            event.setDropAction(Qt.LinkAction)
            event.accept()
            self._addpathmap(localpath=localpath)

    @staticmethod
    def _getlocalpath_from_dropevent(event):
        m = event.mimeData()
        if m.hasFormat('text/uri-list') and len(m.urls()) == 1:
            return unicode(m.urls()[0].toLocalFile())

    def setwebconf(self, webconf):
        """set current webconf object"""
        path = hglib.tounicode(getattr(webconf, 'path', None) or '')
        i = self._qui.path_edit.findText(path)
        if i < 0:
            i = 0
            self._qui.path_edit.insertItem(i, path, webconf)
        self._qui.path_edit.setCurrentIndex(i)

    @property
    def webconf(self):
        """current webconf object"""
        def curconf(w):
            i = w.currentIndex()
            _path, conf = unicode(w.itemText(i)), w.itemData(i).toPyObject()
            return conf

        return curconf(self._qui.path_edit)

    @property
    def _webconfmodel(self):
        """current model object of webconf"""
        return self._qui.repos_view.model()

    @pyqtSlot()
    def _updateview(self):
        m = WebconfModel(config=self.webconf, parent=self)
        self._qui.repos_view.setModel(m)
        self._qui.repos_view.selectionModel().currentChanged.connect(
            self._updateform)

    def _updateform(self):
        """Update availability of each widget"""
        self._qui.repos_view.setEnabled(hasattr(self.webconf, 'write'))
        self._qui.add_button.setEnabled(hasattr(self.webconf, 'write'))
        self._qui.edit_button.setEnabled(
            hasattr(self.webconf, 'write')
            and self._qui.repos_view.currentIndex().isValid())
        self._qui.remove_button.setEnabled(
            hasattr(self.webconf, 'write')
            and self._qui.repos_view.currentIndex().isValid())

    @pyqtSlot()
    def on_open_button_clicked(self):
        path = QFileDialog.getOpenFileName(
            self, _('Open hgweb config'),
            getattr(self.webconf, 'path', None) or '', _FILE_FILTER)
        if path:
            self.openwebconf(path)

    def openwebconf(self, path):
        """load the specified webconf file"""
        path = hglib.fromunicode(path)
        c = wconfig.readfile(path)
        c.path = os.path.abspath(path)
        self.setwebconf(c)

    @pyqtSlot()
    def on_save_button_clicked(self):
        path = QFileDialog.getSaveFileName(
            self, _('Save hgweb config'),
            getattr(self.webconf, 'path', None) or '', _FILE_FILTER)
        if path:
            self.savewebconf(path)

    def savewebconf(self, path):
        """save current webconf to the specified file"""
        path = hglib.fromunicode(path)
        wconfig.writefile(self.webconf, path)
        self.openwebconf(path)  # reopen in case file path changed

    @pyqtSlot()
    def _addpathmap(self, path=None, localpath=None):
        path, localpath = _PathDialog.getaddpathmap(
            self, path=path, localpath=localpath,
            invalidpaths=self._webconfmodel.paths)
        if path:
            self._webconfmodel.addpathmap(path, localpath)

    @pyqtSlot()
    def on_edit_button_clicked(self):
        self.on_repos_view_doubleClicked(self._qui.repos_view.currentIndex())

    @pyqtSlot(QModelIndex)
    def on_repos_view_doubleClicked(self, index):
        assert index.isValid()
        origpath, origlocalpath = self._webconfmodel.getpathmapat(index.row())
        path, localpath = _PathDialog.geteditpathmap(
            self, path=origpath, localpath=origlocalpath,
            invalidpaths=set(self._webconfmodel.paths) - set([origpath]))
        if not path:
            return
        if path != origpath:
            # we cannot change config key without reordering
            self._webconfmodel.removepathmap(origpath)
            self._webconfmodel.addpathmap(path, localpath)
        else:
            self._webconfmodel.setpathmap(path, localpath)

    @pyqtSlot()
    def on_remove_button_clicked(self):
        index = self._qui.repos_view.currentIndex()
        assert index.isValid()
        path, _localpath = self._webconfmodel.getpathmapat(index.row())
        self._webconfmodel.removepathmap(path)

class _PathDialog(QDialog):
    """Dialog to add/edit path mapping"""
    def __init__(self, title, acceptlabel, path=None, localpath=None,
                 invalidpaths=None, parent=None):
        super(_PathDialog, self).__init__(parent)
        self.setWindowFlags((self.windowFlags() | Qt.WindowMinimizeButtonHint)
                            & ~Qt.WindowContextHelpButtonHint)
        self.resize(QFontMetrics(self.font()).width('M') * 50, self.height())
        self.setWindowTitle(title)
        self._invalidpaths = set(invalidpaths or [])
        self.setLayout(QFormLayout(fieldGrowthPolicy=QFormLayout.ExpandingFieldsGrow))
        self._initfields()
        self._initbuttons(acceptlabel)
        self._path_edit.setText(path or os.path.basename(localpath or ''))
        self._localpath_edit.setText(localpath or '')
        self._updateform()

    def _initfields(self):
        """initialize input fields"""
        def addfield(key, label, *extras):
            edit = QLineEdit(self)
            edit.textChanged.connect(self._updateform)
            if extras:
                field = QHBoxLayout()
                field.addWidget(edit)
                for e in extras:
                    field.addWidget(e)
            else:
                field = edit
            self.layout().addRow(label, field)
            setattr(self, '_%s_edit' % key, edit)

        addfield('path', _('Path:'))
        self._localpath_browse_button = QToolButton(
            icon=self.style().standardIcon(QStyle.SP_DialogOpenButton))
        addfield('localpath', _('Local Path:'), self._localpath_browse_button)
        self._localpath_browse_button.clicked.connect(self._browse_localpath)

    def _initbuttons(self, acceptlabel):
        """initialize dialog buttons"""
        self._buttons = QDialogButtonBox(self)
        self._accept_button = self._buttons.addButton(QDialogButtonBox.Ok)
        self._reject_button = self._buttons.addButton(QDialogButtonBox.Cancel)
        self._accept_button.setText(acceptlabel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self.layout().addRow(self._buttons)

    @property
    def path(self):
        """value of path field"""
        return unicode(self._path_edit.text())

    @property
    def localpath(self):
        """value of localpath field"""
        return unicode(self._localpath_edit.text())

    @pyqtSlot()
    def _browse_localpath(self):
        path = QFileDialog.getExistingDirectory(self, _('Select Repository'),
                                                self.localpath)
        if not path:
            return

        path = unicode(path)
        if os.path.exists(os.path.join(path, '.hgsub')):
            self._localpath_edit.setText(os.path.join(path, '**'))
        else:
            self._localpath_edit.setText(path)
        if not self.path:
            self._path_edit.setText(os.path.basename(path))

    @pyqtSlot()
    def _updateform(self):
        """update availability of form elements"""
        self._accept_button.setEnabled(self._isacceptable())

    def _isacceptable(self):
        return bool(self.path and self.localpath
                    and self.path not in self._invalidpaths)

    @classmethod
    def getaddpathmap(cls, parent, path=None, localpath=None, invalidpaths=None):
        d = cls(title=_('Add Path to Serve'), acceptlabel=_('Add'),
                path=path, localpath=localpath,
                invalidpaths=invalidpaths, parent=parent)
        if d.exec_():
            return d.path, d.localpath
        else:
            return None, None

    @classmethod
    def geteditpathmap(cls, parent, path=None, localpath=None, invalidpaths=None):
        d = cls(title=_('Edit Path to Serve'), acceptlabel=_('Edit'),
                path=path, localpath=localpath,
                invalidpaths=invalidpaths, parent=parent)
        if d.exec_():
            return d.path, d.localpath
        else:
            return None, None

class WebconfModel(QAbstractTableModel):
    """Wrapper for webconf object to be a Qt's model object"""
    _COLUMNS = [(_('Path'),),
                (_('Local Path'),)]

    def __init__(self, config, parent=None):
        super(WebconfModel, self).__init__(parent)
        self._config = config

    def data(self, index, role):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            v = self._config.items('paths')[index.row()][index.column()]
            return hglib.tounicode(v)
        return None

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._config['paths'])

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._COLUMNS)

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return self._COLUMNS[section][0]

    @property
    def paths(self):
        """return list of known paths"""
        return [hglib.tounicode(e) for e in self._config['paths']]

    def getpathmapat(self, row):
        """return pair of (path, localpath) at the specified index"""
        assert 0 <= row and row < self.rowCount()
        return tuple(hglib.tounicode(e) for e in self._config.items('paths')[row])

    def addpathmap(self, path, localpath):
        """add path mapping to serve"""
        assert path not in self.paths
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        try:
            self._config.set('paths', hglib.fromunicode(path),
                             hglib.fromunicode(localpath))
        finally:
            self.endInsertRows()

    def setpathmap(self, path, localpath):
        """change path mapping at the specified index"""
        self._config.set('paths', hglib.fromunicode(path),
                         hglib.fromunicode(localpath))
        row = self._indexofpath(path)
        self.dataChanged.emit(self.index(row, 0),
                              self.index(row, self.columnCount()))

    def removepathmap(self, path):
        """remove path from mapping"""
        row = self._indexofpath(path)
        self.beginRemoveRows(QModelIndex(), row, row)
        try:
            del self._config['paths'][hglib.fromunicode(path)]
        finally:
            self.endRemoveRows()

    def _indexofpath(self, path):
        path = hglib.fromunicode(path)
        assert path in self._config['paths']
        return list(self._config['paths']).index(path)
