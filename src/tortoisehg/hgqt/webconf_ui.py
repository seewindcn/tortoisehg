# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/sborho/repos/thg/tortoisehg/hgqt/webconf.ui'
#
# Created by: PyQt4 UI code generator 4.11.4
#
# WARNING! All changes made in this file will be lost!

from tortoisehg.util.i18n import _
from PyQt4 import QtCore, QtGui

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s

try:
    _encoding = QtGui.QApplication.UnicodeUTF8
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig, _encoding)
except AttributeError:
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig)

class Ui_WebconfForm(object):
    def setupUi(self, WebconfForm):
        WebconfForm.setObjectName(_fromUtf8("WebconfForm"))
        WebconfForm.resize(455, 300)
        self.form_layout = QtGui.QVBoxLayout(WebconfForm)
        self.form_layout.setObjectName(_fromUtf8("form_layout"))
        self.path_layout = QtGui.QHBoxLayout()
        self.path_layout.setObjectName(_fromUtf8("path_layout"))
        self.path_label = QtGui.QLabel(WebconfForm)
        self.path_label.setObjectName(_fromUtf8("path_label"))
        self.path_layout.addWidget(self.path_label)
        self.path_edit = QtGui.QComboBox(WebconfForm)
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.path_edit.sizePolicy().hasHeightForWidth())
        self.path_edit.setSizePolicy(sizePolicy)
        self.path_edit.setInsertPolicy(QtGui.QComboBox.InsertAtTop)
        self.path_edit.setObjectName(_fromUtf8("path_edit"))
        self.path_layout.addWidget(self.path_edit)
        self.open_button = QtGui.QToolButton(WebconfForm)
        self.open_button.setObjectName(_fromUtf8("open_button"))
        self.path_layout.addWidget(self.open_button)
        self.save_button = QtGui.QToolButton(WebconfForm)
        self.save_button.setObjectName(_fromUtf8("save_button"))
        self.path_layout.addWidget(self.save_button)
        self.form_layout.addLayout(self.path_layout)
        self.filerepos_sep = QtGui.QFrame(WebconfForm)
        self.filerepos_sep.setFrameShape(QtGui.QFrame.HLine)
        self.filerepos_sep.setFrameShadow(QtGui.QFrame.Sunken)
        self.filerepos_sep.setObjectName(_fromUtf8("filerepos_sep"))
        self.form_layout.addWidget(self.filerepos_sep)
        self.repos_layout = QtGui.QHBoxLayout()
        self.repos_layout.setObjectName(_fromUtf8("repos_layout"))
        self.repos_view = QtGui.QTreeView(WebconfForm)
        self.repos_view.setIndentation(0)
        self.repos_view.setRootIsDecorated(False)
        self.repos_view.setItemsExpandable(False)
        self.repos_view.setObjectName(_fromUtf8("repos_view"))
        self.repos_layout.addWidget(self.repos_view)
        self.addremove_layout = QtGui.QVBoxLayout()
        self.addremove_layout.setObjectName(_fromUtf8("addremove_layout"))
        self.add_button = QtGui.QToolButton(WebconfForm)
        self.add_button.setObjectName(_fromUtf8("add_button"))
        self.addremove_layout.addWidget(self.add_button)
        self.edit_button = QtGui.QToolButton(WebconfForm)
        self.edit_button.setObjectName(_fromUtf8("edit_button"))
        self.addremove_layout.addWidget(self.edit_button)
        self.remove_button = QtGui.QToolButton(WebconfForm)
        self.remove_button.setObjectName(_fromUtf8("remove_button"))
        self.addremove_layout.addWidget(self.remove_button)
        spacerItem = QtGui.QSpacerItem(0, 0, QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding)
        self.addremove_layout.addItem(spacerItem)
        self.repos_layout.addLayout(self.addremove_layout)
        self.form_layout.addLayout(self.repos_layout)
        self.path_label.setBuddy(self.path_edit)

        self.retranslateUi(WebconfForm)
        QtCore.QMetaObject.connectSlotsByName(WebconfForm)

    def retranslateUi(self, WebconfForm):
        WebconfForm.setWindowTitle(_('Webconf'))
        self.path_label.setText(_('Config File:'))
        self.open_button.setText(_('Open'))
        self.save_button.setText(_('Save'))
        self.add_button.setText(_('Add'))
        self.edit_button.setText(_('Edit'))
        self.remove_button.setText(_('Remove'))

