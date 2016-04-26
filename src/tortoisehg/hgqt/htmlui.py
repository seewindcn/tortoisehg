# htmlui.py - mercurial.ui.ui class which emits HTML/Rich Text
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, cgi, time

from mercurial import ui
from tortoisehg.hgqt import qtlib
from tortoisehg.util import hglib

BEGINTAG = '\033' + str(time.time())
ENDTAG = '\032' + str(time.time())

class htmlui(ui.ui):
    def __init__(self, src=None):
        super(htmlui, self).__init__(src)
        self.setconfig('ui', 'interactive', 'off')
        self.setconfig('progress', 'disable', 'True')
        self.output, self.error = [], []

    def write(self, *args, **opts):
        label = opts.get('label', '')
        if self._buffers:
            self._buffers[-1].extend([(str(a), label) for a in args])
        else:
            self.output.extend(self.smartlabel(''.join(args), label))

    def write_err(self, *args, **opts):
        label = opts.get('label', 'ui.error')
        self.error.extend(self.smartlabel(''.join(args), label))

    def label(self, msg, label):
        '''
        Called by Mercurial to apply styling (formatting) to a piece of
        text.  Our implementation wraps tags around the data so we can
        find it later when it is passed to ui.write()
        '''
        return BEGINTAG + self.style(msg, label) + ENDTAG

    def style(self, msg, label):
        'Escape message for safe HTML, then apply specified style'
        msg = cgi.escape(msg).replace('\n', '<br />')
        style = qtlib.geteffect(label)
        return '<span style="%s">%s</span>' % (style, msg)

    def smartlabel(self, text, label):
        '''
        Escape and apply style, excluding any text between BEGINTAG and
        ENDTAG.  That text has already been escaped and styled.
        '''
        parts = []
        try:
            while True:
                b = text.index(BEGINTAG)
                e = text.index(ENDTAG)
                if e > b:
                    if b:
                        parts.append(self.style(text[:b], label))
                    parts.append(text[b + len(BEGINTAG):e])
                    text = text[e + len(ENDTAG):]
                else:
                    # invalid range, assume ENDTAG and BEGINTAG
                    # are naturually occuring.  Style, append, and
                    # consume up to the BEGINTAG and repeat.
                    parts.append(self.style(text[:b], label))
                    text = text[b:]
        except ValueError:
            pass
        if text:
            parts.append(self.style(text, label))
        return parts

    def popbuffer(self, labeled=False):
        b = self._buffers.pop()
        if labeled:
            return ''.join(self.style(a, label) for a, label in b)
        return ''.join(a for a, label in b)

    def plain(self, feature=None):
        return True

    def getdata(self):
        d, e = ''.join(self.output), ''.join(self.error)
        self.output, self.error = [], []
        return d, e

if __name__ == "__main__":
    from mercurial import hg
    u = htmlui()
    repo = hg.repository(u)
    repo.status()
    print u.getdata()[0]
