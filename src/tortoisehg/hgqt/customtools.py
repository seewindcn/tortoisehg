# customtools.py - Settings panel and configuration dialog for TortoiseHg custom tools
#
# This module implements 3 main classes:
#
# 1. A ToolsFrame which is meant to be shown on the settings dialog
# 2. A ToolList widget, part of the ToolsFrame, showing a list of
#    configured custom tools
# 3. A CustomToolConfigDialog, that can be used to add a new or
#    edit an existing custom tool
#
# The ToolsFrame and specially the ToolList must implement some methods
# which are common to all settings widgets.
#
# Copyright 2012 Angel Ezquerra <angel.ezquerra@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re

from tortoisehg.hgqt import qtlib
from tortoisehg.util import hglib
from tortoisehg.util.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

DEFAULTICONNAME = 'tools-spanner-hammer'


class ToolsFrame(QFrame):
    def __init__(self, ini, parent=None, **opts):
        QFrame.__init__(self, parent, **opts)
        self.widgets = []
        self.ini = ini
        self.tortoisehgtools, guidef = hglib.tortoisehgtools(self.ini)
        self.setValue(self.tortoisehgtools)

        # The frame has a header and 3 columns:
        # - The header shows a combo with the list of locations
        # - The columns show:
        #     - The current location tool list and its associated buttons
        #     - The add to list button
        #     - The "available tools" list and its associated buttons
        topvbox = QVBoxLayout()
        self.setLayout(topvbox)

        topvbox.addWidget(QLabel(_('Select a GUI location to edit:')))

        self.locationcombo = QComboBox(self,
            toolTip=_('Select the toolbar or menu to change'))

        def selectlocation(index):
            location = self.locationcombo.itemData(index).toString()
            for widget in self.widgets:
                if widget.location == location:
                    widget.removeInvalid(self.value())
                    widget.show()
                else:
                    widget.hide()
        self.locationcombo.currentIndexChanged.connect(selectlocation)
        topvbox.addWidget(self.locationcombo)

        hbox = QHBoxLayout()
        topvbox.addLayout(hbox)
        vbox = QVBoxLayout()

        self.globaltoollist = ToolListBox(self.ini, minimumwidth=100,
                                          parent=self)
        self.globaltoollist.doubleClicked.connect(self.editToolItem)

        vbox.addWidget(QLabel(_('Tools shown on selected location')))
        for location, locationdesc in hglib.tortoisehgtoollocations:
            self.locationcombo.addItem(locationdesc.decode('utf-8'), location)
            toollist = ToolListBox(self.ini, location=location,
                minimumwidth=100, parent=self)
            toollist.doubleClicked.connect(self.editToolFromName)
            vbox.addWidget(toollist)
            toollist.hide()
            self.widgets.append(toollist)

        deletefromlistbutton = QPushButton(_('Delete from list'), self)
        deletefromlistbutton.clicked.connect(
            lambda: self.forwardToCurrentToolList('deleteTool', remove=False))
        vbox.addWidget(deletefromlistbutton)
        hbox.addLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel('')) # to align all lists
        addtolistbutton = QPushButton('<< ' + _('Add to list') + ' <<', self)
        addtolistbutton.clicked.connect(self.addToList)
        addseparatorbutton = QPushButton('<< ' + _('Add separator'), self)
        addseparatorbutton.clicked.connect(
            lambda: self.forwardToCurrentToolList('addSeparator'))

        vbox.addWidget(addtolistbutton)
        vbox.addWidget(addseparatorbutton)
        vbox.addStretch()
        hbox.addLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(_('List of all tools')))
        vbox.addWidget(self.globaltoollist)
        newbutton = QPushButton(_('New Tool ...'), self)
        newbutton.clicked.connect(self.newTool)
        editbutton = QPushButton(_('Edit Tool ...'), self)
        editbutton.clicked.connect(lambda: self.editTool(row=None))
        deletebutton = QPushButton(_('Delete Tool'), self)
        deletebutton.clicked.connect(self.deleteCurrentTool)

        vbox.addWidget(newbutton)
        vbox.addWidget(editbutton)
        vbox.addWidget(deletebutton)
        hbox.addLayout(vbox)

        # Ensure that the first location list is shown
        selectlocation(0)

    def getCurrentToolList(self):
        index = self.locationcombo.currentIndex()
        location = self.locationcombo.itemData(index).toString()
        for widget in self.widgets:
            if widget.location == location:
                return widget
        return None

    def addToList(self):
        gtl = self.globaltoollist
        row = gtl.currentIndex().row()
        if row < 0:
            row = 0
        item = gtl.item(row)
        if item is None:
            return
        toolname = item.text()
        self.forwardToCurrentToolList('addOrInsertItem', toolname, icon=item.icon())

    def forwardToCurrentToolList(self, funcname, *args, **opts):
        w = self.getCurrentToolList()
        if w is not None:
            getattr(w, funcname)(*args, **opts)
        return None

    def newTool(self):
        td = CustomToolConfigDialog(self)
        res = td.exec_()
        if res:
            toolname, toolconfig = td.value()
            self.globaltoollist.addOrInsertItem(
                toolname, icon=toolconfig.get('icon', None))
            self.tortoisehgtools[toolname] = toolconfig

    def editTool(self, row=None):
        gtl = self.globaltoollist
        if row is None:
            row = gtl.currentIndex().row()
        if row < 0:
            return self.newTool()
        else:
            item = gtl.item(row)
            toolname = item.text()
            td = CustomToolConfigDialog(
                self, toolname=toolname,
                toolconfig=self.tortoisehgtools[str(toolname)])
            res = td.exec_()
            if res:
                toolname, toolconfig = td.value()
                icon = toolconfig.get('icon', '')
                if not icon:
                    icon = DEFAULTICONNAME
                item = QListWidgetItem(qtlib.geticon(icon), toolname)
                gtl.takeItem(row)
                gtl.insertItem(row, item)
                gtl.setCurrentRow(row)
                self.tortoisehgtools[toolname] = toolconfig

    def editToolItem(self, item):
        self.editTool(item.row())

    def editToolFromName(self, name):
        # [TODO] connect to toollist doubleClick (not global)
        gtl = self.globaltoollist
        if name == gtl.SEPARATOR:
            return
        guidef = gtl.values()
        for row, toolname in enumerate(guidef):
            if toolname == name:
                self.editTool(row)
                return

    def deleteCurrentTool(self):
        row = self.globaltoollist.currentIndex().row()
        if row >= 0:
            item = self.globaltoollist.item(row)
            itemtext = str(item.text())
            self.globaltoollist.deleteTool(row=row)

            self.deleteTool(itemtext)
            self.forwardToCurrentToolList('removeInvalid', self.value())

    def deleteTool(self, name):
        try:
            del self.tortoisehgtools[name]
        except KeyError:
            pass

    def applyChanges(self, ini):
        # widget.value() returns the _NEW_ values
        # widget.curvalue returns the _ORIGINAL_ values (yes, this is a bit
        # misleading! "cur" means "current" as in currently valid)
        def updateIniValue(section, key, newvalue):
            section = hglib.fromunicode(section)
            key = hglib.fromunicode(key)
            try:
                del ini[section][key]
            except KeyError:
                pass
            if newvalue is not None:
                ini.set(section, key, newvalue)

        emitChanged = False
        if not self.isDirty():
            return emitChanged

        emitChanged = True
        # 1. Save the new tool configurations
        #
        # In order to keep the tool order we must delete all existing
        # custom tool configurations, and then set all the configuration
        # settings anew:
        section = 'tortoisehg-tools'
        fieldnames = ('command', 'workingdir', 'label', 'tooltip',
                      'icon', 'location', 'enable', 'showoutput',)
        for name in self.curvalue:
            for field in fieldnames:
                try:
                    keyname = '%s.%s' % (name, field)
                    del ini[section][keyname]
                except KeyError:
                    pass

        tools = self.value()
        for uname in tools:
            name = hglib.fromunicode(uname)
            if name[0] in '|-':
                continue
            for field in sorted(tools[name]):
                keyname = '%s.%s' % (name, field)
                value = tools[name][field]
                # value may be bool if originating from hglib.tortoisehgtools()
                if value != '':
                    ini.set(section, keyname, str(value))

        # 2. Save the new guidefs
        for n, toollistwidget in enumerate(self.widgets):
            toollocation = self.locationcombo.itemData(n).toString()
            if not toollistwidget.isDirty():
                continue
            emitChanged = True
            toollist = toollistwidget.value()

            updateIniValue('tortoisehg', toollocation, ' '.join(toollist))

        return emitChanged

    ## common APIs for all edit widgets
    def setValue(self, curvalue):
        self.curvalue = dict(curvalue)

    def value(self):
        return self.tortoisehgtools

    def isDirty(self):
        for toollistwidget in self.widgets:
            if toollistwidget.isDirty():
                return True
        if self.globaltoollist.isDirty():
            return True
        return self.tortoisehgtools != self.curvalue

    def refresh(self):
        self.tortoisehgtools, guidef = hglib.tortoisehgtools(self.ini)
        self.setValue(self.tortoisehgtools)
        self.globaltoollist.refresh()
        for w in self.widgets:
            w.refresh()


class HooksFrame(QFrame):
    def __init__(self, ini, parent=None, **opts):
        super(HooksFrame, self).__init__(parent, **opts)
        self.ini = ini
        # The frame is created empty, and will be populated on 'refresh',
        # which usually happens when the frames is activated
        self.setValue({})

        topbox = QHBoxLayout()
        self.setLayout(topbox)
        self.hooktable = QTableWidget(0, 3, parent)
        self.hooktable.setHorizontalHeaderLabels((_('Type'), _('Name'), _('Command')))
        self.hooktable.sortByColumn(0, Qt.AscendingOrder)
        self.hooktable.setSelectionBehavior(self.hooktable.SelectRows)
        self.hooktable.setSelectionMode(self.hooktable.SingleSelection)
        self.hooktable.cellDoubleClicked.connect(self.editHook)
        topbox.addWidget(self.hooktable)
        buttonbox = QVBoxLayout()
        self.btnnew = QPushButton(_('New hook'))
        buttonbox.addWidget(self.btnnew)
        self.btnnew.clicked.connect(self.newHook)
        self.btnedit = QPushButton(_('Edit hook'))
        buttonbox.addWidget(self.btnedit)
        self.btnedit.clicked.connect(self.editCurrentHook)
        self.btndelete = QPushButton(_('Delete hook'))
        self.btndelete.clicked.connect(self.deleteCurrentHook)
        buttonbox.addWidget(self.btndelete)
        buttonbox.addStretch()
        topbox.addLayout(buttonbox)

    def newHook(self):
        td = HookConfigDialog(self)
        res = td.exec_()
        if res:
            hooktype, command, hookname = td.value()
            # Does the new hook already exist?
            hooks = self.value()
            if hooktype in hooks:
                existingcommand = hooks[hooktype].get(hookname, None)
                if existingcommand is not None:
                    if existingcommand == command:
                        # The command already exists "as is"!
                        return
                    if not qtlib.QuestionMsgBox(
                            _('Replace existing hook?'),
                            _('There is an existing %s.%s hook.\n\n'
                            'Do you want to replace it?')
                            % (hooktype, hookname),
                            parent=self):
                        return
                    # Delete existing matching hooks in reverse order
                    # (otherwise the row numbers will be wrong after the first
                    # deletion)
                    for r in reversed(self.findHooks(
                            hooktype=hooktype, hookname=hookname)):
                        self.deleteHook(r)
            self.hooktable.setSortingEnabled(False)
            row = self.hooktable.rowCount()
            self.hooktable.insertRow(row)
            for c, text in enumerate((hooktype, hookname, command)):
                self.hooktable.setItem(row, c, QTableWidgetItem(text))
            # Make the hook column not editable (a dialog is used to edit it)
            itemhook = self.hooktable.item(row, 0)
            itemhook.setFlags(itemhook.flags() & ~Qt.ItemIsEditable)
            self.hooktable.setSortingEnabled(True)
            self.hooktable.resizeColumnsToContents()
            self.updatebuttons()

    def editHook(self, r, c=0):
        if r < 0:
            r = 0
        numrows = self.hooktable.rowCount()
        if not numrows or r >= numrows:
            return False
        if c > 0:
            # Only show the edit dialog when clicking
            # on the "Hook Type" (i.e. the 1st) column
            return False
        hooktype = self.hooktable.item(r, 0).text()
        hookname = self.hooktable.item(r, 1).text()
        command = self.hooktable.item(r, 2).text()
        td = HookConfigDialog(self, hooktype=hooktype,
                              command=command, hookname=hookname)
        res = td.exec_()
        if res:
            hooktype, command, hookname = td.value()
            # Update the table
            # Note that we must disable the ordering while the table
            # is updated to avoid updating the wrong cell!
            self.hooktable.setSortingEnabled(False)
            self.hooktable.item(r, 0).setText(hooktype)
            self.hooktable.item(r, 1).setText(hookname)
            self.hooktable.item(r, 2).setText(command)
            self.hooktable.setSortingEnabled(True)
            self.hooktable.clearSelection()
            self.hooktable.setState(self.hooktable.NoState)
            self.hooktable.resizeColumnsToContents()
        return bool(res)

    def editCurrentHook(self):
        self.editHook(self.hooktable.currentRow())

    def deleteHook(self, row=None):
        if row is None:
            row = self.hooktable.currentRow()
            if row < 0:
                row = self.hooktable.rowCount() - 1
        self.hooktable.removeRow(row)
        self.hooktable.resizeColumnsToContents()
        self.updatebuttons()

    def deleteCurrentHook(self):
        self.deleteHook()

    def findHooks(self, hooktype=None, hookname=None, command=None):
        matchingrows = []
        for r in range(self.hooktable.rowCount()):
            currhooktype = hglib.fromunicode(self.hooktable.item(r, 0).text())
            currhookname = hglib.fromunicode(self.hooktable.item(r, 1).text())
            currcommand = hglib.fromunicode(self.hooktable.item(r, 2).text())
            matchinghooktype = hooktype is None or hooktype == currhooktype
            matchinghookname = hookname is None or hookname == currhookname
            matchingcommand = command is None or command == currcommand
            if matchinghooktype and matchinghookname and matchingcommand:
                matchingrows.append(r)
        return matchingrows

    def updatebuttons(self):
        tablehasitems = self.hooktable.rowCount() > 0
        self.btnedit.setEnabled(tablehasitems)
        self.btndelete.setEnabled(tablehasitems)

    def applyChanges(self, ini):
        # widget.value() returns the _NEW_ values
        # widget.curvalue returns the _ORIGINAL_ values (yes, this is a bit
        # misleading! "cur" means "current" as in currently valid)
        emitChanged = False
        if not self.isDirty():
            return emitChanged
        emitChanged = True

        # 1. Delete the previous hook configurations
        section = 'hooks'
        hooks = self.curvalue
        for hooktype in hooks:
            for keyname in hooks[hooktype]:
                if keyname:
                    keyname = '%s.%s' % (hooktype, keyname)
                else:
                    keyname = hooktype
                try:
                    del ini[section][keyname]
                except KeyError:
                    pass
        # 2. Save the new configurations
        hooks = self.value()
        for hooktype in hooks:
            for field in sorted(hooks[hooktype]):
                if field:
                    keyname = '%s.%s' % (hooktype, field)
                else:
                    keyname = hooktype
                value = hooks[hooktype][field]
                if value:
                    ini.set(section, keyname, value)
        return emitChanged

    ## common APIs for all edit widgets
    def setValue(self, curvalue):
        self.curvalue = dict(curvalue)

    def value(self):
        hooks = {}
        for r in range(self.hooktable.rowCount()):
            hooktype = hglib.fromunicode(self.hooktable.item(r, 0).text())
            hookname = hglib.fromunicode(self.hooktable.item(r, 1).text())
            command = hglib.fromunicode(self.hooktable.item(r, 2).text())
            if hooktype not in hooks:
                hooks[hooktype] = {}
            hooks[hooktype][hookname] = command
        return hooks

    def isDirty(self):
        return self.value() != self.curvalue

    def gethooks(self):
        hooks = {}
        for key, value in self.ini.items('hooks'):
            keyparts = key.split('.', 1)
            hooktype = keyparts[0]
            if len(keyparts) == 1:
                name = ''
            else:
                name = keyparts[1]
            if hooktype not in hooks:
                hooks[hooktype] = {}
            hooks[hooktype][name] = value
        return hooks

    def refresh(self):
        hooks = self.gethooks()
        self.setValue(hooks)
        self.hooktable.setSortingEnabled(False)
        self.hooktable.setRowCount(0)
        for hooktype in sorted(hooks):
            for name in sorted(hooks[hooktype]):
                itemhook = QTableWidgetItem(hglib.tounicode(hooktype))
                # Make the hook column not editable
                # (a dialog is used to edit it)
                itemhook.setFlags(itemhook.flags() & ~Qt.ItemIsEditable)
                itemname = QTableWidgetItem(hglib.tounicode(name))
                itemtool = QTableWidgetItem(
                    hglib.tounicode(hooks[hooktype][name]))
                self.hooktable.insertRow(self.hooktable.rowCount())
                self.hooktable.setItem(self.hooktable.rowCount() - 1, 0, itemhook)
                self.hooktable.setItem(self.hooktable.rowCount() - 1, 1, itemname)
                self.hooktable.setItem(self.hooktable.rowCount() - 1, 2, itemtool)
        self.hooktable.setSortingEnabled(True)
        self.hooktable.resizeColumnsToContents()
        self.updatebuttons()


class ToolListBox(QListWidget):
    SEPARATOR = '------'
    def __init__(self, ini, parent=None, location=None, minimumwidth=None,
                 **opts):
        QListWidget.__init__(self, parent, **opts)
        self.opts = opts
        self.curvalue = None
        self.ini = ini
        self.location = location

        if minimumwidth:
            self.setMinimumWidth(minimumwidth)

        self.refresh()

        # Enable drag and drop to reorder the tools
        self.setDragEnabled(True)
        self.setDragDropMode(self.InternalMove)
        if PYQT_VERSION >= 0x40700:
            self.setDefaultDropAction(Qt.MoveAction)

    def _guidef2toollist(self, guidef):
        toollist = []
        for name in guidef:
            if name == '|':
                name = self.SEPARATOR
                # avoid putting multiple separators together
                if [name] == toollist[-1:]:
                    continue
            toollist.append(name)
        return toollist

    def _toollist2guidef(self, toollist):
        guidef = []
        for uname in toollist:
            if uname == self.SEPARATOR:
                name = '|'
                # avoid putting multiple separators together
                if [name] == toollist[-1:]:
                    continue
            else:
                name = hglib.fromunicode(uname)
            guidef.append(name)
        return guidef

    def addOrInsertItem(self, text, icon=None):
        if text == self.SEPARATOR:
            item = text
        else:
            if not icon:
                icon = DEFAULTICONNAME
            if isinstance(icon, str):
                icon = qtlib.geticon(icon)
            item = QListWidgetItem(icon, text)
        row = self.currentIndex().row()
        if row < 0:
            self.addItem(item)
            self.setCurrentRow(self.count()-1)
        else:
            self.insertItem(row+1, item)
            self.setCurrentRow(row+1)

    def deleteTool(self, row=None, remove=False):
        if row is None:
            row = self.currentIndex().row()
        if row >= 0:
            self.takeItem(row)

    def addSeparator(self):
        self.addOrInsertItem(self.SEPARATOR, icon=None)

    def values(self):
        out = []
        for row in range(self.count()):
            out.append(self.item(row).text())
        return out

    ## common APIs for all edit widgets
    def setValue(self, curvalue):
        self.curvalue = curvalue

    def value(self):
        return self._toollist2guidef(self.values())

    def isDirty(self):
        return self.value() != self.curvalue

    def refresh(self):
        toolsdefs, guidef = hglib.tortoisehgtools(self.ini,
            selectedlocation=self.location)
        self.toollist = self._guidef2toollist(guidef)
        self.setValue(guidef)
        self.clear()
        for toolname in self.toollist:
            icon = toolsdefs.get(toolname, {}).get('icon', None)
            self.addOrInsertItem(toolname, icon=icon)

    def removeInvalid(self, validtools):
        validguidef = []
        for toolname in self.value():
            if toolname[0] not in '|-':
                if toolname not in validtools:
                    continue
            validguidef.append(toolname)
        self.clear()
        self.toollist = self._guidef2toollist(validguidef)
        for toolname in self.toollist:
            icon = validtools.get(toolname, {}).get('icon', None)
            self.addOrInsertItem(toolname, icon=icon)


class CustomConfigDialog(QDialog):
    '''Custom Config Dialog base class'''

    def __init__(self, parent=None, dialogname='', **kwargs):
        QDialog.__init__(self, parent, **kwargs)
        self.dialogname = dialogname
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.hbox = QHBoxLayout()
        self.formvbox = QFormLayout()

        self.hbox.addLayout(self.formvbox)
        vbox = QVBoxLayout()
        self.okbutton = QPushButton(_('OK'))
        self.okbutton.clicked.connect(self.okClicked)
        vbox.addWidget(self.okbutton)
        self.cancelbutton = QPushButton(_('Cancel'))
        self.cancelbutton.clicked.connect(self.reject)
        vbox.addWidget(self.cancelbutton)
        vbox.addStretch()
        self.hbox.addLayout(vbox)
        self.setLayout(self.hbox)
        self.setMaximumHeight(self.sizeHint().height())
        self._readsettings()

    def value(self):
        return None

    def _genCombo(self, items, selecteditem=None):
        index = 0
        if selecteditem:
            try:
                index = list(items).index(selecteditem)
            except ValueError:
                pass
        combo = QComboBox()
        combo.addItems(items)
        if index:
            combo.setCurrentIndex(index)
        return combo

    def _addConfigItem(self, parent, label, configwidget, tooltip=None):
        if tooltip:
            configwidget.setToolTip(tooltip)
        parent.addRow(label, configwidget)
        return configwidget

    def okClicked(self):
        errormsg = self.validateForm()
        if errormsg:
            qtlib.WarningMsgBox(_('Missing information'), errormsg)
            return
        return self.accept()

    def validateForm(self):
        return '' # No error

    def _readsettings(self):
        s = QSettings()
        if self.dialogname:
            self.restoreGeometry(s.value(self.dialogname + '/geom').toByteArray())
        return s

    def _writesettings(self):
        s = QSettings()
        if self.dialogname:
            s.setValue(self.dialogname + '/geom', self.saveGeometry())

    def done(self, r):
        self._writesettings()
        super(CustomConfigDialog, self).done(r)


class CustomToolConfigDialog(CustomConfigDialog):
    '''Dialog for editing custom tool configurations'''

    _enablemappings = [(_('All items'), 'istrue'),
                       (_('Working directory'), 'iswd'),
                       (_('All revisions'), 'isrev'),
                       (_('All contexts'), 'isctx'),
                       (_('Fixed revisions'), 'fixed'),
                       (_('Applied patches'), 'applied'),
                       (_('Applied patches or qparent'), 'qgoto'),
                       ]
    _defaulticonstring = _('<default icon>')

    def __init__(self, parent=None, toolname=None, toolconfig={}):
        super(CustomToolConfigDialog, self).__init__(parent,
            dialogname='customtools',
            windowTitle=_('Configure Custom Tool'),
            windowIcon=qtlib.geticon(DEFAULTICONNAME))

        vbox = self.formvbox

        command = toolconfig.get('command', '')
        workingdir = toolconfig.get('workingdir', '')
        label = toolconfig.get('label', '')
        tooltip = toolconfig.get('tooltip', '')
        ico = toolconfig.get('icon', '')
        enable = toolconfig.get('enable', 'all')
        showoutput = str(toolconfig.get('showoutput', False))

        self.name = self._addConfigItem(vbox, _('Tool name'),
            QLineEdit(toolname), _('The tool name. It cannot contain spaces.'))
            # Execute a mercurial command. These _MUST_ start with "hg"
        self.command = self._addConfigItem(vbox, _('Command'),
            QLineEdit(command), _('The command that will be executed.\n'
            'To execute a Mercurial command use "hg" (rather than "hg.exe") '
            'as the executable command.\n'
            'You can use several {VARIABLES} to compose your command:\n'
            '- {ROOT}: The path to the current repository root.\n'
            '- {REV} / {REVID}: the selected revision number / '
            'hexadecimal revision id hash respectively.\n'
            '- {SELECTEDFILES}: The list of files selected by the user on the '
            'revision details file list.\n'
            '- {FILES}: The list of files touched by the selected revision.\n'
            '- {ALLFILES}: All the files tracked by Mercurial on the selected'
            ' revision.'))
        self.workingdir = self._addConfigItem(vbox, _('Working Directory'),
            QLineEdit(workingdir),
            _('The directory where the command will be executed.\n'
            'If this is not set, the root of the current repository '
            'will be used instead.\n'
            'You can use the same {VARIABLES} as on the "Command" setting.\n'))
        self.label = self._addConfigItem(vbox, _('Tool label'),
            QLineEdit(label),
            _('The tool label, which is what will be shown '
            'on the repowidget context menu.\n'
            'If no label is set, the tool name will be used as the tool label.\n'
            'If no tooltip is set, the label will be used as the tooltip as well.'))
        self.tooltip = self._addConfigItem(vbox, _('Tooltip'),
            QLineEdit(tooltip),
            _('The tooltip that will be shown on the tool button.\n'
            'This is only shown when the tool button is shown on\n'
            'the workbench toolbar.'))

        iconnames = qtlib.getallicons()
        combo = QComboBox()
        if not ico:
            ico = self._defaulticonstring
        elif ico not in iconnames:
            combo.addItem(qtlib.geticon(ico), ico)
        combo.addItem(qtlib.geticon(DEFAULTICONNAME),
                      self._defaulticonstring)
        for name in iconnames:
            combo.addItem(qtlib.geticon(name), name)
        combo.setEditable(True)
        idx = combo.findText(ico)
        # note that idx will always be >= 0 because if ico not in iconnames
        # it will have been added as the first element on the combobox!
        combo.setCurrentIndex(idx)

        self.icon = self._addConfigItem(vbox, _('Icon'),
            combo,
            _('The tool icon.\n'
            'You can use any built-in TortoiseHg icon\n'
            'by setting this value to a valid TortoiseHg icon name\n'
            '(e.g. clone, add, remove, sync, thg-logo, hg-update, etc).\n'
            'You can also set this value to the absolute path to\n'
            'any icon on your file system.'))

        combo = self._genCombo([l for l, _v in self._enablemappings],
                               self._enable2label(enable))
        self.enable = self._addConfigItem(vbox, _('On repowidget, show for'),
            combo,  _('For which kinds of revisions the tool will be enabled\n'
            'It is only taken into account when the tool is shown on the\n'
            'selected revision context menu.'))

        combo = self._genCombo(('True', 'False'), showoutput)
        self.showoutput = self._addConfigItem(vbox, _('Show Output Log'),
            combo, _('When enabled, automatically show the Output Log when the '
            'command is run.\nDefault: False.'))

    def value(self):
        toolname = str(self.name.text()).strip()
        toolconfig = {
            'label': str(self.label.text()),
            'command': str(self.command.text()),
            'workingdir': str(self.workingdir.text()),
            'tooltip': str(self.tooltip.text()),
            'icon': str(self.icon.currentText()),
            'enable': self._enablemappings[self.enable.currentIndex()][1],
            'showoutput': str(self.showoutput.currentText()),
        }
        if toolconfig['icon'] == self._defaulticonstring:
            toolconfig['icon'] = ''
        return toolname, toolconfig

    def _enable2label(self, value):
        return dict((v, l) for l, v in self._enablemappings).get(value)

    def validateForm(self):
        name, config = self.value()
        if not name:
            return _('You must set a tool name.')
        if name.find(' ') >= 0:
            return _('The tool name cannot have any spaces in it.')
        if not config['command']:
            return _('You must set a command to run.')
        return '' # No error


class HookConfigDialog(CustomConfigDialog):
    '''Dialog for editing the a hook configuration'''

    _hooktypes = (
        'changegroup',
        'commit',
        'incoming',
        'outgoing',
        'prechangegroup',
        'precommit',
        'prelistkeys',
        'preoutgoing',
        'prepushkey',
        'pretag',
        'pretxnchangegroup',
        'pretxncommit',
        'preupdate',
        'listkeys',
        'pushkey',
        'tag',
        'update',
    )
    _rehookname = re.compile('^[^=\s]*$')

    def __init__(self, parent=None, hooktype=None, command='', hookname=''):
        super(HookConfigDialog, self).__init__(parent,
            dialogname='hookconfigdialog',
            windowTitle=_('Configure Hook'),
            windowIcon=qtlib.geticon('tools-hooks'))

        vbox = self.formvbox
        combo = self._genCombo(self._hooktypes, hooktype)
        self.hooktype = self._addConfigItem(vbox, _('Hook type'),
            combo, _('Select when your command will be run'))
        self.name = self._addConfigItem(vbox, _('Tool name'),
            QLineEdit(hookname), _('The hook name. It cannot contain spaces.'))
        self.command = self._addConfigItem(vbox, _('Command'),
            QLineEdit(command), _('The command that will be executed.\n'
                 'To execute a python function prepend the command with '
                 '"python:".\n'))

    def value(self):
        hooktype = str(self.hooktype.currentText())
        hookname = str(self.name.text()).strip()
        command = str(self.command.text()).strip()
        return hooktype, command, hookname

    def validateForm(self):
        hooktype, command, hookname = self.value()
        if hooktype not in self._hooktypes:
            return _('You must set a valid hook type.')
        if self._rehookname.match(hookname) is None:
            return _('The hook name cannot contain any spaces, '
                     'tabs or \'=\' characters.')
        if not command:
            return _('You must set a command to run.')
        return '' # No error
