# shellconf.py - User interface for the TortoiseHg shell extension settings
#
# Copyright 2009 Steve Borho <steve@borho.org>
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from tortoisehg.hgqt import qtlib
from tortoisehg.util.i18n import _
from tortoisehg.util import menuthg

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from _winreg import (HKEY_CURRENT_USER, REG_SZ, REG_DWORD,
                     OpenKey, CreateKey, QueryValueEx, SetValueEx)

THGKEY = 'TortoiseHg'
OVLKEY = 'TortoiseOverlays'
PROMOTEDITEMS = 'PromotedItems'

# reading functions
def is_true(x): return x in ('1', 'True')
def nonzero(x): return x != 0

# writing functions
def one_str(x):
    if x: return '1'
    return '0'
def one_int(x):
    if x: return 1
    return 0

def noop(x): return x

vars = {
    # name:
    #   default, regkey, regtype, evalfunc, wrfunc, checkbuttonattribute
    'EnableOverlays':
        [True,     THGKEY, REG_SZ, is_true, one_str, 'ovenable'],
    'LocalDisksOnly':
        [False,    THGKEY, REG_SZ, is_true, one_str, 'localonly'],
    'ShowTaskbarIcon':
        [True,     THGKEY, REG_SZ, is_true, one_str, 'show_taskbaricon'],
    'HighlightTaskbarIcon':
        [True,     THGKEY, REG_SZ, is_true, one_str, 'highlight_taskbaricon'],
    'HideMenuOutsideRepo':
        [False,    THGKEY, REG_SZ, is_true, one_str, 'hidecmenu'],
    PROMOTEDITEMS:
        ['commit,workbench', THGKEY, REG_SZ, noop, noop, None],
    'ShowUnversionedOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableUnversionedHandler'],
    'ShowIgnoredOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableIgnoredHandler'],
    'ShowLockedOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableLockedHandler'],
    'ShowReadonlyOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableReadonlyHandler'],
    'ShowDeletedOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableDeletedHandler'],
    'ShowAddedOverlay':
        [True, OVLKEY, REG_DWORD, nonzero, one_int, 'enableAddedHandler']
}


class ShellConfigWindow(QDialog):

    def __init__(self, parent=None):
        super(ShellConfigWindow, self).__init__(parent)

        self.menu_cmds = {}
        self.dirty = False

        layout = QVBoxLayout()

        tw = QTabWidget()
        layout.addWidget(tw)

        # cmenu tab
        cmenuwidget = QWidget()
        grid = QGridLayout()
        cmenuwidget.setLayout(grid)
        tw.addTab(cmenuwidget, _("Context Menu"))

        w = QLabel(_("Top menu items:"))
        grid.addWidget(w, 0, 0)
        self.topmenulist = w = QListWidget()
        grid.addWidget(w, 1, 0, 4, 1)
        w.itemClicked.connect(self.listItemClicked)

        w = QLabel(_("Sub menu items:"))
        grid.addWidget(w, 0, 2)
        self.submenulist = w = QListWidget()
        grid.addWidget(w, 1, 2, 4, 1)
        w.itemClicked.connect(self.listItemClicked)

        style = QApplication.style()
        icon = style.standardIcon(QStyle.SP_ArrowLeft)
        self.top_button = w = QPushButton(icon, '')
        grid.addWidget(w, 2, 1)
        w.clicked.connect(self.top_clicked)
        icon = style.standardIcon(QStyle.SP_ArrowRight)
        self.sub_button = w = QPushButton(icon, '')
        grid.addWidget(w, 3, 1)
        w.clicked.connect(self.sub_clicked)

        grid.setRowStretch(1, 10)
        grid.setRowStretch(4, 10)

        def checkbox(label):
            cb = QCheckBox(label)
            cb.stateChanged.connect(self.stateChanged)
            return cb

        hidebox = QGroupBox(_('Menu Behavior'))
        grid.addWidget(hidebox, 5, 0, 5, 3)
        self.hidecmenu = checkbox(_('Hide context menu outside repositories'))
        self.hidecmenu.setToolTip(_('Do not show menu items on unversioned '
                                    'folders (use shift + click to override)'))
        hidebox.setLayout(QVBoxLayout())
        hidebox.layout().addWidget(self.hidecmenu)

        # Icons tab
        iconswidget = QWidget()
        iconslayout = QVBoxLayout()
        iconswidget.setLayout(iconslayout)
        tw.addTab(iconswidget, _("Icons"))

        # Overlays group
        gbox = QGroupBox(_("Overlays"))
        iconslayout.addWidget(gbox)
        hb = QHBoxLayout()
        gbox.setLayout(hb)
        self.ovenable = cb = checkbox(_("Enabled overlays"))
        hb.addWidget(cb)
        self.localonly = checkbox(_("Local disks only"))
        hb.addWidget(self.localonly)
        hb.addStretch()

        # Enabled Overlay Handlers group
        gbox = QGroupBox(_("Enabled Overlay Handlers"))
        iconslayout.addWidget(gbox)
        grid = QGridLayout()
        gbox.setLayout(grid)
        grid.setColumnStretch(3, 10)
        w = QLabel(_("Warning: affects all Tortoises, logoff required after "
                     "change"))
        grid.addWidget(w, 0, 0, 1, 3)
        self.enableAddedHandler = w = checkbox(_("Added"))
        grid.addWidget(w, 1, 0)
        self.enableLockedHandler = w = checkbox(_("Locked*"))
        grid.addWidget(w, 1, 1)
        self.enableIgnoredHandler = w = checkbox(_("Ignored*"))
        grid.addWidget(w, 1, 2)
        self.enableUnversionedHandler = w = checkbox(_("Unversioned"))
        grid.addWidget(w, 2, 0)
        self.enableReadonlyHandler = w = checkbox(_("Readonly*"))
        grid.addWidget(w, 2, 1)
        self.enableDeletedHandler = w = checkbox(_("Deleted*"))
        grid.addWidget(w, 2, 2)
        w = QLabel(_("*: not used by TortoiseHg"))
        grid.addWidget(w, 3, 0, 1, 3)

        # Taskbar group
        gbox = QGroupBox(_("Taskbar"))
        iconslayout.addWidget(gbox)
        hb = QHBoxLayout()
        gbox.setLayout(hb)
        self.show_taskbaricon = cb = checkbox(_("Show Icon"))
        hb.addWidget(cb)
        self.highlight_taskbaricon = cb = checkbox(_("Highlight Icon"))
        hb.addWidget(cb)
        hb.addStretch()

        iconslayout.addStretch()

        # i18n: URL of TortoiseSVN documentation
        url = _('http://tortoisesvn.net/docs/release/TortoiseSVN_en/'
                'tsvn-dug-settings.html#tsvn-dug-settings-icon-set')
        w = QLabel(_('You can change the icon set from <a href="%s">'
                     "TortoiseSVN's Settings</a>") % url)
        w.setOpenExternalLinks(True)
        iconslayout.addWidget(w)

        # dialog buttons
        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel|BB.Apply)
        self.apply_button = bb.button(BB.Apply)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Apply).clicked.connect(self.apply)
        bb.button(BB.Ok).setDefault(True)
        layout.addWidget(bb)

        self.setLayout(layout)
        self.setWindowTitle(_("Explorer Extension Settings - TortoiseHg"))
        self.setWindowIcon(qtlib.geticon('thg-repoconfig'))

        self.load_shell_configs()

    def load_shell_configs(self):
        for name, info in vars.iteritems():
            default, regkey, regtype, evalfunc, wrfunc, cbattr = info
            try:
                hkey = OpenKey(HKEY_CURRENT_USER, 'Software\\' + regkey)
                v = QueryValueEx(hkey, name)[0]
                vars[name][0] = evalfunc(v)
            except (WindowsError, EnvironmentError):
                pass
            if cbattr != None:
                checkbutton = getattr(self, cbattr)
                checkbutton.setChecked(vars[name][0])

        promoteditems = vars[PROMOTEDITEMS][0]
        self.set_menulists(promoteditems)

        self.dirty = False
        self.update_states()

    def set_menulists(self, promoteditems):
        for list in (self.topmenulist, self.submenulist):
            list.clear()
            list.setSortingEnabled(True)
        promoted = [pi.strip() for pi in promoteditems.split(',')]
        for cmd, info in menuthg.thgcmenu.items():
            label = info['label']
            item = QListWidgetItem(label['str'].decode('utf-8'))
            item._id = label['id']
            if cmd in promoted:
                self.topmenulist.addItem(item)
            else:
                self.submenulist.addItem(item)
            self.menu_cmds[item._id] = cmd

    def store_shell_configs(self):
        if not  self.dirty:
            return

        promoted = []
        list = self.topmenulist
        for row in range(list.count()):
            cmd = self.menu_cmds[list.item(row)._id]
            promoted.append(cmd)

        hkey = CreateKey(HKEY_CURRENT_USER, "Software\\" + THGKEY)
        SetValueEx(hkey, PROMOTEDITEMS, 0, REG_SZ, ','.join(promoted))

        for name, info in vars.iteritems():
            default, regkey, regtype, evalfunc, wrfunc, cbattr = info
            if cbattr == None:
                continue
            checkbutton = getattr(self, cbattr)
            v = wrfunc(checkbutton.isChecked())
            hkey = CreateKey(HKEY_CURRENT_USER, 'Software\\' + regkey)
            SetValueEx(hkey, name, 0, regtype, v)

        self.dirty = False
        self.update_states()

    def accept(self):
        self.store_shell_configs()
        QDialog.accept(self)

    def reject(self):
        QDialog.reject(self)

    def apply(self):
        self.store_shell_configs()

    def top_clicked(self):
        self.move_selected(self.submenulist, self.topmenulist)

    def sub_clicked(self):
        self.move_selected(self.topmenulist, self.submenulist)

    def move_selected(self, fromlist, tolist):
        row = fromlist.currentRow()
        if row < 0:
            return
        item = fromlist.takeItem(row)
        tolist.addItem(item)
        tolist.setCurrentItem(item)
        fromlist.setCurrentItem(None)
        self.dirty = True
        self.update_states()

    def update_states(self):
        self.top_button.setEnabled(len(self.submenulist.selectedItems()) > 0)
        self.sub_button.setEnabled(len(self.topmenulist.selectedItems()) > 0)
        self.apply_button.setEnabled(self.dirty)

    def stateChanged(self, state):
        self.dirty = True
        self.update_states()

    def listItemClicked(self, item):
        itemlist = item.listWidget()
        for list in (self.topmenulist, self.submenulist):
            if list != itemlist:
                list.setCurrentItem(None)
        self.update_states()
