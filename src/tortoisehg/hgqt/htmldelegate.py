# htmldelegate.py - HTML QStyledItemDelegate
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class HTMLDelegate(QStyledItemDelegate):

    def paint(self, painter, option, index):
        # draw selection
        option = QStyleOptionViewItemV4(option)
        self.parent().style().drawControl(QStyle.CE_ItemViewItem, option, painter)

        # draw text
        doc = self._builddoc(option, index)
        painter.save()
        painter.setClipRect(option.rect)
        painter.translate(QPointF(
            option.rect.left(),
            option.rect.top() + (option.rect.height() - doc.size().height()) / 2))
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette = option.palette
        if option.state & QStyle.State_Selected:
            if option.state & QStyle.State_Active:
                ctx.palette.setCurrentColorGroup(QPalette.Active)
            else:
                ctx.palette.setCurrentColorGroup(QPalette.Inactive)
            ctx.palette.setBrush(QPalette.Text, ctx.palette.highlightedText())
        elif not option.state & QStyle.State_Enabled:
            ctx.palette.setCurrentColorGroup(QPalette.Disabled)

        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        doc = self._builddoc(option, index)
        return QSize(doc.idealWidth() + 5, doc.size().height())

    def _builddoc(self, option, index):
        doc = QTextDocument(defaultFont=option.font)
        doc.setHtml(index.data().toString())
        return doc
