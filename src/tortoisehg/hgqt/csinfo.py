# csinfo.py - An embeddable widget for changeset summary
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re
import binascii

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import qtlib

PANEL_DEFAULT = ('rev', 'summary', 'user', 'dateage', 'branch', 'close',
                 'tags', 'graft', 'transplant', 'obsolete',
                 'p4', 'svn', 'converted',)

def create(repo, target=None, style=None, custom=None, **kargs):
    return Factory(repo, custom, style, target, **kargs)()

def factory(*args, **kargs):
    return Factory(*args, **kargs)

def panelstyle(**kargs):
    kargs['type'] = 'panel'
    if 'contents' not in kargs:
        kargs['contents'] = PANEL_DEFAULT
    return kargs

def labelstyle(**kargs):
    kargs['type'] = 'label'
    return kargs

def custom(**kargs):
    return kargs

class Factory(object):

    def __init__(self, repo, custom=None, style=None, target=None,
                 withupdate=False):
        if repo is None:
            raise _('must be specified repository')
        self.repo = repo
        self.target = target
        if custom is None:
            custom = {}
        self.custom = custom
        if style is None:
            style = panelstyle()
        self.csstyle = style
        self.info = SummaryInfo()

        self.withupdate = withupdate

    def __call__(self, target=None, style=None, custom=None, repo=None):
        # try to create a context object
        if target is None:
            target = self.target
        if repo is None:
            repo = self.repo

        if style is None:
            style = self.csstyle
        else:
            # need to override styles
            newstyle = self.csstyle.copy()
            newstyle.update(style)
            style = newstyle

        if custom is None:
            custom = self.custom
        else:
            # need to override customs
            newcustom = self.custom.copy()
            newcustom.update(custom)
            custom = newcustom

        if 'type' not in style:
            raise _("must be specified 'type' in style")
        type = style['type']
        assert type in ('panel', 'label')

        # create widget
        args = (target, style, custom, repo, self.info)
        if type == 'panel':
            widget = SummaryPanel(*args)
        else:
            widget = SummaryLabel(*args)
        if self.withupdate:
            widget.update()
        return widget

class UnknownItem(Exception):
    pass


class SummaryInfo(object):

    LABELS = {'rev': _('Revision:'), 'revnum': _('Revision:'),
              'revid': _('Revision:'), 'summary': _('Summary:'),
              'user': _('User:'), 'date': _('Date:'),'age': _('Age:'),
              'dateage': _('Date:'), 'branch': _('Branch:'),
              'close': _('Close:'),
              'tags': _('Tags:'), 'rawbranch': _('Branch:'),
              'graft': _('Graft:'),
              'transplant': _('Transplant:'),
              'obsolete': _('Obsolete state:'),
              'p4': _('Perforce:'), 'svn': _('Subversion:'),
              'converted': _('Converted From:'), 'shortuser': _('User:'),
              'mqoriginalparent': _('Original Parent:')
    }

    def __init__(self):
        pass

    def get_data(self, item, widget, ctx, custom, **kargs):
        args = (widget, ctx, custom)
        def default_func(widget, item, ctx):
            return None
        def preset_func(widget, item, ctx):
            if item == 'rev':
                revnum = self.get_data('revnum', *args)
                revid = self.get_data('revid', *args)
                if revid:
                    return (revnum, revid)
                return None
            elif item == 'revnum':
                return ctx.rev()
            elif item == 'revid':
                return str(ctx)
            elif item == 'desc':
                return hglib.tounicode(ctx.description().replace('\0', ''))
            elif item == 'summary':
                summary = hglib.longsummary(
                    ctx.description().replace('\0', ''))
                if len(summary) == 0:
                    return None
                return summary
            elif item == 'user':
                user = hglib.user(ctx)
                if user:
                    return hglib.tounicode(user)
                return None
            elif item == 'shortuser':
                return hglib.tounicode(hglib.username(hglib.user(ctx)))
            elif item == 'dateage':
                date = self.get_data('date', *args)
                age = self.get_data('age', *args)
                if date and age:
                    return (date, age)
                return None
            elif item == 'date':
                date = ctx.date()
                if date:
                    return hglib.displaytime(date)
                return None
            elif item == 'age':
                date = ctx.date()
                if date:
                    return hglib.age(date).decode('utf-8')
                return None
            elif item == 'rawbranch':
                return ctx.branch() or None
            elif item == 'branch':
                value = self.get_data('rawbranch', *args)
                if value:
                    repo = ctx._repo
                    try:
                        if ctx.node() != repo.branchtip(ctx.branch()):
                            return None
                    except error.RepoLookupError:
                        # ctx.branch() can be invalid for null or workingctx
                        return None
                    if value in repo.deadbranches:
                        return None
                    return value
                return None
            elif item == 'close':
                return ctx.extra().get('close')
            elif item == 'tags':
                return ctx.thgtags() or None
            elif item == 'graft':
                extra = ctx.extra()
                try:
                    return extra['source']
                except KeyError:
                    pass
                return None
            elif item == 'transplant':
                extra = ctx.extra()
                try:
                    ts = extra['transplant_source']
                    if ts:
                        return binascii.hexlify(ts)
                except KeyError:
                    pass
                return None
            elif item == 'obsolete':
                obsoletestate = []
                if ctx.obsolete():
                    obsoletestate.append('obsolete')
                if ctx.extinct():
                    obsoletestate.append('extinct')
                obsoletestate += ctx.troubles()
                if obsoletestate:
                    return obsoletestate
                return None
            elif item == 'p4':
                extra = ctx.extra()
                p4cl = extra.get('p4', None)
                return p4cl and ('changelist %s' % p4cl)
            elif item == 'svn':
                extra = ctx.extra()
                cvt = extra.get('convert_revision', '')
                if cvt.startswith('svn:'):
                    result = cvt.split('/', 1)[-1]
                    if cvt != result:
                        return result
                    return cvt.split('@')[-1]
                else:
                    return None
            elif item == 'converted':
                extra = ctx.extra()
                cvt = extra.get('convert_revision', '')
                if cvt and not cvt.startswith('svn:'):
                    return cvt
                else:
                    return None
            elif item == 'ishead':
                childbranches = [cctx.branch() for cctx in ctx.children()]
                return ctx.branch() not in childbranches
            elif item == 'mqoriginalparent':
                target = ctx.thgmqoriginalparent()
                if not target:
                    return None
                p1 = ctx.p1()
                if p1 is not None and p1.hex() == target:
                    return None
                if target not in ctx._repo:
                    return None
                return target
            raise UnknownItem(item)
        if 'data' in custom and not kargs.get('usepreset', False):
            try:
                return custom['data'](widget, item, ctx)
            except UnknownItem:
                pass
        try:
            return preset_func(widget, item, ctx)
        except UnknownItem:
            pass
        return default_func(widget, item, ctx)

    def get_label(self, item, widget, ctx, custom, **kargs):
        def default_func(widget, item):
            return ''
        def preset_func(widget, item):
            try:
                return self.LABELS[item]
            except KeyError:
                raise UnknownItem(item)
        if 'label' in custom and not kargs.get('usepreset', False):
            try:
                return custom['label'](widget, item, ctx)
            except UnknownItem:
                pass
        try:
            return preset_func(widget, item)
        except UnknownItem:
            pass
        return default_func(widget, item)

    def get_markup(self, item, widget, ctx, custom, **kargs):
        args = (widget, ctx, custom)
        mono = dict(family='monospace', size='9pt', space='pre')
        def default_func(widget, item, value):
            return ''
        def preset_func(widget, item, value):
            if item == 'rev':
                revnum, revid = value
                revid = qtlib.markup(revid, **mono)
                if revnum is not None and revid is not None:
                    return '%s (%s)' % (revnum, revid)
                return '%s' % revid
            elif item in ('revid', 'graft', 'transplant', 'mqoriginalparent'):
                return qtlib.markup(value, **mono)
            elif item in ('revnum', 'p4', 'close', 'converted'):
                return str(value)
            elif item == 'svn':
                # svn is always in utf-8 because ctx.extra() isn't converted
                return unicode(value, 'utf-8', 'replace')
            elif item in ('rawbranch', 'branch'):
                opts = dict(fg='black', bg='#aaffaa')
                return qtlib.markup(' %s ' % value, **opts)
            elif item == 'tags':
                opts = dict(fg='black', bg='#ffffaa')
                tags = [qtlib.markup(' %s ' % tag, **opts) for tag in value]
                return ' '.join(tags)
            elif item in ('desc', 'summary', 'user', 'shortuser',
                          'date', 'age'):
                return qtlib.markup(value)
            elif item == 'dateage':
                return qtlib.markup('%s (%s)' % value)
            elif item == 'obsolete':
                opts = dict(fg='black', bg='#ff8566')
                obsoletestates = [qtlib.markup(' %s ' % state, **opts)
                                  for state in value]
                return ' '.join(obsoletestates)
            raise UnknownItem(item)
        value = self.get_data(item, *args)
        if value is None:
            return None
        if 'markup' in custom and not kargs.get('usepreset', False):
            try:
                return custom['markup'](widget, item, value)
            except UnknownItem:
                pass
        try:
            return preset_func(widget, item, value)
        except UnknownItem:
            pass
        return default_func(widget, item, value)

    def get_widget(self, item, widget, ctx, custom, **kargs):
        args = (widget, ctx, custom)
        def default_func(widget, item, markups):
            if isinstance(markups, basestring):
                markups = (markups,)
            labels = []
            for text in markups:
                label = QLabel()
                label.setText(text)
                labels.append(label)
            return labels
        markups = self.get_markup(item, *args)
        if not markups:
            return None
        if 'widget' in custom and not kargs.get('usepreset', False):
            try:
                return custom['widget'](widget, item, markups)
            except UnknownItem:
                pass
        return default_func(widget, item, markups)

class SummaryBase(object):

    def __init__(self, target, custom, repo, info):
        if target is None:
            self.target = None
        else:
            self.target = str(target)
        self.custom = custom
        self.repo = repo
        self.info = info
        self.ctx = repo.changectx(self.target)

    def get_data(self, item, **kargs):
        return self.info.get_data(item, self, self.ctx, self.custom, **kargs)

    def get_label(self, item, **kargs):
        return self.info.get_label(item, self, self.ctx, self.custom, **kargs)

    def get_markup(self, item, **kargs):
        return self.info.get_markup(item, self, self.ctx, self.custom, **kargs)

    def get_widget(self, item, **kargs):
        return self.info.get_widget(item, self, self.ctx, self.custom, **kargs)

    def set_revision(self, rev):
        self.target = rev

    def update(self, target=None, custom=None, repo=None):
        self.ctx = None
        if target is None:
            target = self.target
        if target is not None:
            target = str(target)
            self.target = target
        if custom is not None:
            self.custom = custom
        if repo is None:
            repo = self.repo
        if repo is not None:
            self.repo = repo
        if self.ctx is None:
            self.ctx = repo.changectx(target)

PANEL_TMPL = '<tr><td style="padding-right:6px">%s</td><td>%s</td></tr>'

class SummaryPanel(SummaryBase, QWidget):

    linkActivated = pyqtSignal(str)

    def __init__(self, target, style, custom, repo, info):
        SummaryBase.__init__(self, target, custom, repo, info)
        QWidget.__init__(self)

        self.csstyle = style

        hbox = QHBoxLayout()
        hbox.setMargin(0)
        hbox.setSpacing(0)
        self.setLayout(hbox)
        self.revlabel = None
        self.expand_btn = qtlib.PMButton()

    def update(self, target=None, style=None, custom=None, repo=None):
        SummaryBase.update(self, target, custom, repo)

        if style is not None:
            self.csstyle = style

        if self.revlabel is None:
            self.revlabel = QLabel()
            self.revlabel.linkActivated.connect(self.linkActivated)
            self.layout().addWidget(self.revlabel, 0, Qt.AlignTop)

        if 'expandable' in self.csstyle and self.csstyle['expandable']:
            if self.expand_btn.parentWidget() is None:
                self.expand_btn.clicked.connect(lambda: self.update())
                margin = QHBoxLayout()
                margin.setMargin(3)
                margin.addWidget(self.expand_btn, 0, Qt.AlignTop)
                self.layout().insertLayout(0, margin)
            self.expand_btn.setVisible(True)
        elif self.expand_btn.parentWidget() is not None:
            self.expand_btn.setHidden(True)

        interact = Qt.LinksAccessibleByMouse

        if 'selectable' in self.csstyle and self.csstyle['selectable']:
            interact |= Qt.TextBrowserInteraction

        self.revlabel.setTextInteractionFlags(interact)

        # build info
        contents = self.csstyle.get('contents', ())
        if 'expandable' in self.csstyle and self.csstyle['expandable'] \
                                        and self.expand_btn.is_collapsed():
            contents = contents[0:1]

        if 'margin' in self.csstyle:
            margin = self.csstyle['margin']
            assert isinstance(margin, (int, long))
            buf = '<table style="margin: %spx">' % margin
        else:
            buf = '<table>'

        for item in contents:
            markups = self.get_markup(item)
            if not markups:
                continue
            label = qtlib.markup(self.get_label(item), weight='bold')
            if isinstance(markups, basestring):
                markups = [markups,]
            buf += PANEL_TMPL % (label, markups.pop(0))
            for markup in markups:
                buf += PANEL_TMPL % ('&nbsp;', markup)
        buf += '</table>'
        self.revlabel.setText(buf)

        return True

    def set_expanded(self, state):
        self.expand_btn.set_expanded(state)
        self.update()

    def is_expanded(self):
        return self.expand_btn.is_expanded()

    def minimumSizeHint(self):
        s = QWidget.minimumSizeHint(self)
        return QSize(0, s.height())

LABEL_PAT = re.compile(r'(?:(?<=%%)|(?<!%)%\()(\w+)(?:\)s)')

class SummaryLabel(SummaryBase, QLabel):

    def __init__(self, target, style, custom, repo, info):
        SummaryBase.__init__(self, target, custom, repo, info)
        QLabel.__init__(self)

        self.csstyle = style

    def update(self, target=None, style=None, custom=None, repo=None):
        SummaryBase.update(self, target, custom, repo)

        if style is not None:
            self.csstyle = style

        if 'selectable' in self.csstyle:
            sel = self.csstyle['selectable']
            val = sel and Qt.TextSelectableByMouse or Qt.TextBrowserInteraction
            self.setTextInteractionFlags(val)

        if 'width' in self.csstyle:
            width = self.csstyle.get('width', 0)
            self.setMinimumWidth(width)

        if 'height' in self.csstyle:
            height = self.csstyle.get('height', 0)
            self.setMinimumHeight(height)

        contents = self.csstyle.get('contents', None)

        # build info
        info = ''
        for snip in contents:
            # extract all placeholders
            items = LABEL_PAT.findall(snip)
            # fetch required data
            data = {}
            for item in items:
                markups = self.get_markup(item)
                if not markups:
                    continue
                if isinstance(markups, basestring):
                    markups = (markups,)
                data[item] = ', '.join(markups)
            if len(data) == 0:
                continue
            # insert data & append to label
            info += snip % data
        self.setText(info)

        return True
