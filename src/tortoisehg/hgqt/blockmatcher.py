# Copyright (c) 2003-2010 LOGILAB S.A. (Paris, FRANCE).
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

"""
Qt4 widgets to display diffs as blocks
"""
from PyQt4.QtGui import *
from PyQt4.QtCore import *

class BlockList(QWidget):
    """
    A simple widget to be 'linked' to the scrollbar of a diff text
    view.

    It represents diff blocks with coloured rectangles, showing
    currently viewed area by a semi-transparant rectangle sliding
    above them.
    """

    rangeChanged = pyqtSignal(int,int)
    valueChanged = pyqtSignal(int)
    pageStepChanged = pyqtSignal(int)

    def __init__(self, *args):
        QWidget.__init__(self, *args)
        self._blocks = set()
        self._minimum = 0
        self._maximum = 100
        self.blockTypes = {'+': QColor(0xA0, 0xFF, 0xB0, ),#0xa5),
                           '-': QColor(0xFF, 0xA0, 0xA0, ),#0xa5),
                           'x': QColor(0xA0, 0xA0, 0xFF, ),#0xa5),
                           's': QColor(0xFF, 0xA5, 0x00, ),#0xa5),
                           }
        self._sbar = None
        self._value = 0
        self._pagestep = 10
        self._vrectcolor = QColor(0x00, 0x00, 0x55, 0x25)
        self._vrectbordercolor = self._vrectcolor.darker()
        self.sizePolicy().setControlType(QSizePolicy.Slider)
        self.setMinimumWidth(20)

    def clear(self):
        self._blocks = set()

    def addBlock(self, typ, alo, ahi):
        self._blocks.add((typ, alo, ahi))

    def setMaximum(self, maximum):
        self._maximum = maximum
        self.update()
        self.rangeChanged.emit(self._minimum, self._maximum)

    def setMinimum(self, minimum):
        self._minimum = minimum
        self.update()
        self.rangeChanged.emit(self._minimum, self._maximum)

    def setRange(self, minimum, maximum):
        if minimum == maximum:
            return
        self._minimum = minimum
        self._maximum = maximum
        self.update()
        self.rangeChanged.emit(self._minimum, self._maximum)

    def setValue(self, val):
        if val != self._value:
            self._value = val
            self.update()
            self.valueChanged.emit(val)

    def setPageStep(self, pagestep):
        if pagestep != self._pagestep:
            self._pagestep = pagestep
            self.update()
            self.pageStepChanged.emit(pagestep)

    def linkScrollBar(self, sbar):
        """
        Make the block list displayer be linked to the scrollbar
        """
        self._sbar = sbar
        self.setUpdatesEnabled(False)
        self.setMaximum(sbar.maximum())
        self.setMinimum(sbar.minimum())
        self.setPageStep(sbar.pageStep())
        self.setValue(sbar.value())
        self.setUpdatesEnabled(True)

        sbar.valueChanged.connect(self.setValue)
        sbar.rangeChanged.connect(self.setRange)

        self.valueChanged.connect(sbar.setValue)
        self.rangeChanged.connect(lambda x, y: sbar.setRange(x,y))
        self.pageStepChanged.connect(lambda x: sbar.setPageStep(x))

    def syncPageStep(self):
        self.setPageStep(self._sbar.pageStep())

    def paintEvent(self, event):
        w = self.width() - 1
        h = self.height()
        p = QPainter(self)
        sy = float(h) / (self._maximum - self._minimum + self._pagestep)
        for typ, alo, ahi in self._blocks:
            color = self.blockTypes[typ]
            p.setPen(color)  # make sure the height is at least 1px
            p.setBrush(color)
            p.drawRect(1, alo * sy, w - 1, (ahi - alo) * sy)

        p.setPen(self._vrectbordercolor)
        p.setBrush(self._vrectcolor)
        p.drawRect(0, self._value * sy, w, self._pagestep * sy)

    def scrollToPos(self, y):
        # Scroll to the position which specified by Y coodinate.
        if not isinstance(self._sbar, QScrollBar):
            return
        ratio = float(y) / self.height()
        minimum, maximum, step = self._minimum, self._maximum, self._pagestep
        value = minimum + (maximum + step - minimum) * ratio - (step * 0.5)
        value = min(maximum, max(minimum, value))  # round to valid range.
        self.setValue(value)

    def mousePressEvent(self, event):
        super(BlockList, self).mousePressEvent(event)
        self.scrollToPos(event.y())

    def mouseMoveEvent(self, event):
        super(BlockList, self).mouseMoveEvent(event)
        self.scrollToPos(event.y())

class BlockMatch(BlockList):
    """
    A simpe widget to be linked to 2 file views (text areas),
    displaying 2 versions of a same file (diff).

    It will show graphically matching diff blocks between the 2 text
    areas.
    """

    rangeChanged = pyqtSignal(int, int, str)
    valueChanged = pyqtSignal(int, str)
    pageStepChanged = pyqtSignal(int, str)

    def __init__(self, *args):
        QWidget.__init__(self, *args)
        self._blocks = set()
        self._minimum = {'left': 0, 'right': 0}
        self._maximum = {'left': 100, 'right': 100}
        self.blockTypes = {'+': QColor(0xA0, 0xFF, 0xB0, ),#0xa5),
                           '-': QColor(0xFF, 0xA0, 0xA0, ),#0xa5),
                           'x': QColor(0xA0, 0xA0, 0xFF, ),#0xa5),
                           }
        self._sbar = {}
        self._value =  {'left': 0, 'right': 0}
        self._pagestep =  {'left': 10, 'right': 10}
        self._vrectcolor = QColor(0x00, 0x00, 0x55, 0x25)
        self._vrectbordercolor = self._vrectcolor.darker()
        self.sizePolicy().setControlType(QSizePolicy.Slider)
        self.setMinimumWidth(20)

    def nDiffs(self):
        return len(self._blocks)

    def showDiff(self, delta):
        ps_l = float(self._pagestep['left'])
        ps_r = float(self._pagestep['right'])
        mv_l = self._value['left']
        mv_r = self._value['right']
        Mv_l = mv_l + ps_l
        Mv_r = mv_r + ps_r

        vblocks = []
        blocks = sorted(self._blocks, key=lambda x:(x[1],x[3],x[2],x[4]))
        for i, (typ, alo, ahi, blo, bhi) in enumerate(blocks):
            if (mv_l<=alo<=Mv_l or mv_l<=ahi<=Mv_l or
                mv_r<=blo<=Mv_r or mv_r<=bhi<=Mv_r):
                break
        else:
            i = -1
        i += delta

        if i < 0:
            return -1
        if i >= len(blocks):
            return 1
        typ, alo, ahi, blo, bhi = blocks[i]
        self.setValue(alo, "left")
        self.setValue(blo, "right")
        if i == 0:
            return -1
        if i == len(blocks)-1:
            return 1
        return 0

    def nextDiff(self):
        return self.showDiff(+1)

    def prevDiff(self):
        return self.showDiff(-1)

    def addBlock(self, typ, alo, ahi, blo=None, bhi=None):
        if bhi is None:
            bhi = ahi
        if blo is None:
            blo = alo
        self._blocks.add((typ, alo, ahi, blo, bhi))

    def paintEvent(self, event):
        if self._pagestep['left'] == 0 or self._pagestep['right'] == 0:
            return

        w = self.width()
        h = self.height()
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)

        ps_l = float(self._pagestep['left'])
        ps_r = float(self._pagestep['right'])
        v_l = self._value['left']
        v_r = self._value['right']

        # we do integer divisions here cause the pagestep is the
        # integer number of fully displayed text lines
        scalel = self._sbar['left'].height()//ps_l
        scaler = self._sbar['right'].height()//ps_r

        ml = v_l
        Ml = v_l + ps_l
        mr = v_r
        Mr = v_r + ps_r

        p.setPen(Qt.NoPen)
        for typ, alo, ahi, blo, bhi in self._blocks:
            if not (ml<=alo<=Ml or ml<=ahi<=Ml or mr<=blo<=Mr or mr<=bhi<=Mr):
                continue
            p.save()
            p.setBrush(self.blockTypes[typ])

            path = QPainterPath()
            path.moveTo(0, scalel * (alo - ml))
            path.cubicTo(w/3.0, scalel * (alo - ml),
                         2*w/3.0, scaler * (blo - mr),
                         w, scaler * (blo - mr))
            path.lineTo(w, scaler * (bhi - mr) + 2)
            path.cubicTo(2*w/3.0, scaler * (bhi - mr) + 2,
                         w/3.0, scalel * (ahi - ml) + 2,
                         0, scalel * (ahi - ml) + 2)
            path.closeSubpath()
            p.drawPath(path)

            p.restore()

    def setMaximum(self, maximum, side):
        self._maximum[side] = maximum
        self.update()
        self.rangeChanged.emit(self._minimum[side], self._maximum[side], side)

    def setMinimum(self, minimum, side):
        self._minimum[side] = minimum
        self.update()
        self.rangeChanged.emit(self._minimum[side], self._maximum[side], side)

    def setRange(self, minimum, maximum, side=None):
        if side is None:
            if self.sender() == self._sbar['left']:
                side = 'left'
            else:
                side = 'right'
        self._minimum[side] = minimum
        self._maximum[side] = maximum
        self.update()
        self.rangeChanged.emit(self._minimum[side], self._maximum[side], side)

    def setValue(self, val, side=None):
        if side is None:
            if self.sender() == self._sbar['left']:
                side = 'left'
            else:
                side = 'right'
        if val != self._value[side]:
            self._value[side] = val
            self.update()
            self.valueChanged.emit(val, side)

    def setPageStep(self, pagestep, side):
        if pagestep != self._pagestep[side]:
            self._pagestep[side] = pagestep
            self.update()
            self.pageStepChanged.emit(pagestep, side)

    @pyqtSlot()
    def syncPageStep(self):
        for side in ['left', 'right']:
            self.setPageStep(self._sbar[side].pageStep(), side)

    def linkScrollBar(self, sb, side):
        """
        Make the block list displayer be linked to the scrollbar
        """
        if self._sbar is None:
            self._sbar = {}
        self._sbar[side] = sb
        self.setUpdatesEnabled(False)
        self.setMaximum(sb.maximum(), side)
        self.setMinimum(sb.minimum(), side)
        self.setPageStep(sb.pageStep(), side)
        self.setValue(sb.value(), side)
        self.setUpdatesEnabled(True)
        sb.valueChanged.connect(self.setValue)
        sb.rangeChanged.connect(self.setRange)

        self.valueChanged.connect(lambda v, s: side==s and sb.setValue(v))
        self.rangeChanged.connect(
                     lambda v1, v2, s: side==s and sb.setRange(v1, v2))
        self.pageStepChanged.connect(
                     lambda v, s: side==s and sb.setPageStep(v))


def createTestWidget(ui, parent=None):
    f = QFrame(parent)
    l = QHBoxLayout(f)

    sb1 = QScrollBar()
    sb2 = QScrollBar()

    w0 = BlockList()
    w0.addBlock('-', 200, 300)
    w0.addBlock('-', 450, 460)
    w0.addBlock('x', 500, 501)
    w0.linkScrollBar(sb1)

    w1 = BlockMatch()
    w1.addBlock('+', 12, 42)
    w1.addBlock('+', 55, 142)
    w1.addBlock('-', 200, 300)
    w1.addBlock('-', 330, 400, 450, 460)
    w1.addBlock('x', 420, 450, 500, 501)
    w1.linkScrollBar(sb1, 'left')
    w1.linkScrollBar(sb2, 'right')

    w2 = BlockList()
    w2.addBlock('+', 12, 42)
    w2.addBlock('+', 55, 142)
    w2.addBlock('x', 420, 450)
    w2.linkScrollBar(sb2)

    l.addWidget(sb1)
    l.addWidget(w0)
    l.addWidget(w1)
    l.addWidget(w2)
    l.addWidget(sb2)

    w0.setRange(0, 1200)
    w0.setPageStep(100)
    w1.setRange(0, 1200, 'left')
    w1.setRange(0, 1200, 'right')
    w1.setPageStep(100, 'left')
    w1.setPageStep(100, 'right')
    w2.setRange(0, 1200)
    w2.setPageStep(100)

    ui.status('sb1=%d %d %d\n' % (sb1.minimum(), sb1.maximum(), sb1.pageStep()))
    ui.status('sb2=%d %d %d\n' % (sb2.minimum(), sb2.maximum(), sb2.pageStep()))

    return f
