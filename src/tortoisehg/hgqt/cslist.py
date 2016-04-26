# cslist.py - embeddable changeset/patch list component
#
# Copyright 2009 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 David Wilhelm <dave@jumbledpile.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from tortoisehg.hgqt import csinfo, qtlib
from tortoisehg.util.i18n import _
from tortoisehg.util.patchctx import patchctx

_SPACING = 6

class ChangesetList(QWidget):

    def __init__(self, repo=None, parent=None):
        super(ChangesetList, self).__init__(parent)

        self.currepo = repo
        self.curitems = None
        self.curfactory = None
        self.showitems = None
        self.limit = 20
        contents = ('%(item_l)s:', ' %(branch)s', ' %(tags)s', ' %(summary)s')
        self.lstyle = csinfo.labelstyle(contents=contents, width=350,
                                        selectable=True)
        contents = ('item', 'summary', 'user', 'dateage', 'rawbranch',
                    'tags', 'graft', 'transplant', 'p4', 'svn', 'converted')
        self.pstyle = csinfo.panelstyle(contents=contents, width=350,
                                        selectable=True)

        # main layout
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mainvbox = QVBoxLayout()
        self.mainvbox.setSpacing(_SPACING)
        self.mainvbox.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setLayout(self.mainvbox)

        ## status box
        self.statusbox = QHBoxLayout()
        self.statuslabel = QLabel(_('No items to display'))
        self.compactchk = QCheckBox(_('Use compact view'))
        self.statusbox.addWidget(self.statuslabel)
        self.statusbox.addWidget(self.compactchk)
        self.mainvbox.addLayout(self.statusbox)

        ## scroll area
        self.scrollarea = QScrollArea()
        self.scrollarea.setMinimumSize(400, 200)
        self.scrollarea.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scrollarea.setWidgetResizable(True)
        self.mainvbox.addWidget(self.scrollarea)

        ### cs layout grid, contains Factory objects, one per revision
        self.scrollbox = QWidget()
        self.csvbox = QVBoxLayout()
        self.csvbox.setSpacing(_SPACING)
        self.csvbox.setSizeConstraint(QLayout.SetMaximumSize)
        self.scrollbox.setLayout(self.csvbox)
        self.scrollarea.setWidget(self.scrollbox)

        # signal handlers
        self.compactchk.toggled.connect(self._updateView)

        # csetinfo
        def datafunc(widget, item, ctx):
            if item in ('item', 'item_l'):
                if not isinstance(ctx, patchctx):
                    return True
                revid = widget.get_data('revid')
                if not revid:
                    return widget.target
                filename = os.path.basename(widget.target)
                return filename, revid
            raise csinfo.UnknownItem(item)
        def labelfunc(widget, item, ctx):
            if item in ('item', 'item_l'):
                if not isinstance(ctx, patchctx):
                    return _('Revision:')
                return _('Patch:')
            raise csinfo.UnknownItem(item)
        def markupfunc(widget, item, value):
            if item in ('item', 'item_l'):
                if not isinstance(widget.ctx, patchctx):
                    if item == 'item':
                        return widget.get_markup('rev')
                    return widget.get_markup('revnum')
                mono = dict(face='monospace', size='9000')
                if isinstance(value, basestring):
                    return qtlib.markup(value, **mono)
                filename = qtlib.markup(value[0])
                revid = qtlib.markup(value[1], **mono)
                if item == 'item':
                    return '%s (%s)' % (filename, revid)
                return filename
            raise csinfo.UnknownItem(item)
        self.custom = csinfo.custom(data=datafunc, label=labelfunc,
                                    markup=markupfunc)

    def clear(self):
        """Clear the item list"""
        while self.csvbox.count():
            w = self.csvbox.takeAt(0).widget()
            w.setParent(None)
        self.curitems = None

    def insertcs(self, item):
        """Insert changeset info into the item list.

        item: String, revision number or patch file path to display.
        """
        style = self.compactchk.isChecked() and self.lstyle or self.pstyle
        info = self.curfactory(item, style=style)
        info.update(item)
        sizePolicy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        info.setSizePolicy(sizePolicy)
        self.csvbox.addWidget(info, Qt.AlignTop)

    def updatestatus(self):
        if not self.curitems:
            text = _('No items to display')
        else:
            num = dict(count=len(self.showitems), total=len(self.curitems))
            text = _('Displaying %(count)d of %(total)d items') % num
        self.statuslabel.setText(text)

    def update(self, items, uselimit=True):
        """Update the item list.

        Public arguments:
        items: List of revision numbers and/or patch file paths.
               You can pass a mixed list. The order will be respected.
        uselimit: If True, some of items will be shown.

        return: True if the item list was updated successfully,
                False if it wasn't updated.
        """
        # setup
        self.clear()
        self.curfactory = csinfo.factory(self.currepo, self.custom)

        # initialize variables
        self.curitems = items

        if not items or not self.currepo:
            self.updatestatus()
            return False

        if self.compactchk.isChecked():
            self.csvbox.setSpacing(0)
        else:
            self.csvbox.setSpacing(_SPACING)

        # determine the items to show
        if uselimit and self.limit < len(items):
            showitems, lastitem = items[:self.limit - 1], items[-1]
        else:
            showitems, lastitem = items, None
        self.showitems = showitems + (lastitem and [lastitem] or [])

        # show items
        for item in showitems:
            self.insertcs(item)
        if lastitem:
            self.csvbox.addWidget(QLabel("..."))
            self.insertcs(lastitem)
        self.updatestatus()
        return True

    @pyqtSlot()
    def _updateView(self):
        self.update(self.curitems)
