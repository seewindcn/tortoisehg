# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/sborho/repos/thg/tortoisehg/hgqt/serve.ui'
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

class Ui_ServeDialog(object):
    def setupUi(self, ServeDialog):
        ServeDialog.setObjectName(_fromUtf8("ServeDialog"))
        ServeDialog.resize(500, 400)
        self.dialog_layout = QtGui.QVBoxLayout(ServeDialog)
        self.dialog_layout.setObjectName(_fromUtf8("dialog_layout"))
        self.top_layout = QtGui.QHBoxLayout()
        self.top_layout.setObjectName(_fromUtf8("top_layout"))
        self.opts_layout = QtGui.QFormLayout()
        self.opts_layout.setFieldGrowthPolicy(QtGui.QFormLayout.ExpandingFieldsGrow)
        self.opts_layout.setObjectName(_fromUtf8("opts_layout"))
        self.port_label = QtGui.QLabel(ServeDialog)
        self.port_label.setObjectName(_fromUtf8("port_label"))
        self.opts_layout.setWidget(0, QtGui.QFormLayout.LabelRole, self.port_label)
        self.port_edit = QtGui.QSpinBox(ServeDialog)
        self.port_edit.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.port_edit.setMinimum(1)
        self.port_edit.setMaximum(65535)
        self.port_edit.setProperty("value", 8000)
        self.port_edit.setObjectName(_fromUtf8("port_edit"))
        self.opts_layout.setWidget(0, QtGui.QFormLayout.FieldRole, self.port_edit)
        self.status_label = QtGui.QLabel(ServeDialog)
        self.status_label.setObjectName(_fromUtf8("status_label"))
        self.opts_layout.setWidget(1, QtGui.QFormLayout.LabelRole, self.status_label)
        self.status_edit = QtGui.QLabel(ServeDialog)
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.status_edit.sizePolicy().hasHeightForWidth())
        self.status_edit.setSizePolicy(sizePolicy)
        self.status_edit.setText(_fromUtf8(""))
        self.status_edit.setTextFormat(QtCore.Qt.RichText)
        self.status_edit.setOpenExternalLinks(True)
        self.status_edit.setObjectName(_fromUtf8("status_edit"))
        self.opts_layout.setWidget(1, QtGui.QFormLayout.FieldRole, self.status_edit)
        self.top_layout.addLayout(self.opts_layout)
        self.actions_layout = QtGui.QVBoxLayout()
        self.actions_layout.setObjectName(_fromUtf8("actions_layout"))
        self.start_button = QtGui.QPushButton(ServeDialog)
        self.start_button.setDefault(True)
        self.start_button.setObjectName(_fromUtf8("start_button"))
        self.actions_layout.addWidget(self.start_button)
        self.stop_button = QtGui.QPushButton(ServeDialog)
        self.stop_button.setAutoDefault(False)
        self.stop_button.setObjectName(_fromUtf8("stop_button"))
        self.actions_layout.addWidget(self.stop_button)
        spacerItem = QtGui.QSpacerItem(0, 5, QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding)
        self.actions_layout.addItem(spacerItem)
        self.settings_button = QtGui.QPushButton(ServeDialog)
        self.settings_button.setAutoDefault(False)
        self.settings_button.setObjectName(_fromUtf8("settings_button"))
        self.actions_layout.addWidget(self.settings_button)
        self.top_layout.addLayout(self.actions_layout)
        self.top_layout.setStretch(0, 1)
        self.dialog_layout.addLayout(self.top_layout)
        self.details_tabs = QtGui.QTabWidget(ServeDialog)
        self.details_tabs.setObjectName(_fromUtf8("details_tabs"))
        self.dialog_layout.addWidget(self.details_tabs)
        self.dialog_layout.setStretch(1, 1)
        self.port_label.setBuddy(self.port_edit)

        self.retranslateUi(ServeDialog)
        self.details_tabs.setCurrentIndex(-1)
        QtCore.QMetaObject.connectSlotsByName(ServeDialog)
        ServeDialog.setTabOrder(self.port_edit, self.start_button)
        ServeDialog.setTabOrder(self.start_button, self.stop_button)
        ServeDialog.setTabOrder(self.stop_button, self.settings_button)
        ServeDialog.setTabOrder(self.settings_button, self.details_tabs)

    def retranslateUi(self, ServeDialog):
        ServeDialog.setWindowTitle(_('Web Server'))
        self.port_label.setText(_('Port:'))
        self.status_label.setText(_('Status:'))
        self.start_button.setText(_('Start'))
        self.stop_button.setText(_('Stop'))
        self.settings_button.setText(_('Settings'))

