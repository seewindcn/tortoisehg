# revpanel.py - TortoiseHg rev panel widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.


from mercurial import error

from tortoisehg.util import hglib, obsoleteutil
from tortoisehg.util.i18n import _
from tortoisehg.hgqt import csinfo, qtlib

from PyQt4.QtCore import *

def label_func(widget, item, ctx):
    if item == 'cset':
        if type(ctx.rev()) is str:
            return _('Patch:')
        return _('Changeset:')
    elif item == 'parents':
        return _('Parent:')
    elif item == 'children':
        return _('Child:')
    elif item == 'precursors':
        return _('Precursors:')
    elif item == 'successors':
        return _('Successors:')
    raise csinfo.UnknownItem(item)

def revid_markup(revid, **kargs):
    opts = dict(family='monospace', size='9pt')
    opts.update(kargs)
    return qtlib.markup(revid, **opts)

def data_func(widget, item, ctx):
    def summary_line(desc):
        return hglib.longsummary(desc.replace('\0', ''))
    def revline_data(ctx, hl=False, branch=None):
        if isinstance(ctx, basestring):
            return ctx
        desc = ctx.description()
        return (str(ctx.rev()), str(ctx), summary_line(desc), hl, branch)
    def format_ctxlist(ctxlist):
        if not ctxlist:
            return None
        return [revline_data(ctx)[:3] for ctx in ctxlist]
    if item == 'cset':
        return revline_data(ctx)
    elif item == 'branch':
        value = hglib.tounicode(ctx.branch())
        return value != 'default' and value or None
    elif item == 'parents':
        # TODO: need to put 'diff to other' checkbox
        #pindex = self.diff_other_parent() and 1 or 0
        pindex = 0 # always show diff with first parent
        pctxs = ctx.parents()
        parents = []
        for pctx in pctxs:
            highlight = len(pctxs) == 2 and pctx == pctxs[pindex]
            branch = None
            if hasattr(pctx, 'branch') and pctx.branch() != ctx.branch():
                branch = pctx.branch()
            parents.append(revline_data(pctx, highlight, branch))
        return parents
    elif item == 'children':
        children = []
        for cctx in ctx.children():
            branch = None
            if hasattr(cctx, 'branch') and cctx.branch() != ctx.branch():
                branch = cctx.branch()
            children.append(revline_data(cctx, branch=branch))
        return children
    elif item in ('graft', 'transplant', 'mqoriginalparent',
                  'p4', 'svn', 'converted',):
        ts = widget.get_data(item, usepreset=True)
        if not ts:
            return None
        try:
            tctx = ctx._repo[ts]
            return revline_data(tctx)
        except (error.LookupError, error.RepoLookupError, error.RepoError):
            return ts
    elif item == 'ishead':
        if ctx.rev() is None:
            ctx = ctx.p1()
        childbranches = [cctx.branch() for cctx in ctx.children()]
        return ctx.branch() not in childbranches
    elif item == 'isclose':
        if ctx.rev() is None:
            ctx = ctx.p1()
        return ctx.extra().get('close') is not None
    elif item == 'precursors':
        ctxlist = obsoleteutil.first_known_precursors(ctx)
        return format_ctxlist(ctxlist)
    elif item == 'successors':
        ctxlist = obsoleteutil.first_known_successors(ctx)
        return format_ctxlist(ctxlist)

    raise csinfo.UnknownItem(item)

def create_markup_func(ui):
    def link_markup(revnum, revid, linkpattern=None):
        mrevid = revid_markup('%s (%s)' % (revnum, revid))
        if linkpattern is None:
            return mrevid
        link = linkpattern.replace('{node|short}', revid).replace('{rev}', revnum)
        return '<a href="%s">%s</a>' % (link, mrevid)
    def revline_markup(revnum, revid, summary, highlight=None,
                       branch=None, linkpattern='cset:{node|short}'):
        def branch_markup(branch):
            opts = dict(fg='black', bg='#aaffaa')
            return qtlib.markup(' %s ' % branch, **opts)
        summary = qtlib.markup(summary)
        if branch:
            branch = branch_markup(branch)
        if revid:
            rev = link_markup(revnum, revid, linkpattern=linkpattern)
            if branch:
                return '%s %s %s' % (rev, branch, summary)
            return '%s %s' % (rev, summary)
        else:
            revnum = qtlib.markup(revnum)
            if branch:
                return '%s - %s %s' % (revnum, branch, summary)
            return '%s - %s' % (revnum, summary)
    def markup_func(widget, item, value):
        if item in ('cset', 'graft', 'transplant', 'mqoriginalparent',
                    'p4', 'svn', 'converted'):
            if item == 'cset':
                linkpattern = ui.config('tortoisehg', 'changeset.link', None)
            else:
                linkpattern = 'cset:{node|short}'
            if isinstance(value, basestring):
                return revid_markup(value)
            return revline_markup(linkpattern=linkpattern, *value)
        elif item in ('parents', 'children', 'precursors', 'successors'):
            csets = []
            for cset in value:
                if isinstance(cset, basestring):
                    csets.append(revid_markup(cset))
                else:
                    csets.append(revline_markup(*cset))
            return csets
        raise csinfo.UnknownItem(item)
    return markup_func

def RevPanelWidget(repo):
    '''creates a rev panel widget and returns it'''
    custom = csinfo.custom(data=data_func, label=label_func,
                           markup=create_markup_func(repo.ui))
    style = csinfo.panelstyle(contents=('cset', 'branch', 'obsolete', 'close', 'user',
                   'dateage', 'parents', 'children', 'tags', 'graft', 'transplant',
                   'mqoriginalparent',
                   'precursors', 'successors',
                   'p4', 'svn', 'converted'), selectable=True,
                   expandable=True)
    return csinfo.create(repo, style=style, custom=custom)


def nomarkup(widget, item, value):
    def revline_markup(revnum, revid, summary, highlight=None, branch=None):
        summary = qtlib.markup(summary)
        if revid:
            rev = revid_markup('%s (%s)' % (revnum, revid))
            return '%s %s' % (rev, summary)
        else:
            revnum = qtlib.markup(revnum)
            return '%s - %s' % (revnum, summary)
    csets = []
    if item == 'ishead':
        if value is False:
            text = _('Not a head revision!')
            return qtlib.markup(text, fg='red', weight='bold')
        raise csinfo.UnknownItem(item)
    elif item == 'isclose':
        if value is True:
            text = _('Head is closed!')
            return qtlib.markup(text, fg='red', weight='bold')
        raise csinfo.UnknownItem(item)
    for cset in value:
        if isinstance(cset, basestring):
            csets.append(revid_markup(cset))
        else:
            csets.append(revline_markup(*cset))
    return csets

def ParentWidget(repo):
    'creates a parent rev widget and returns it'
    custom = csinfo.custom(data=data_func, label=label_func, markup=nomarkup)
    style = csinfo.panelstyle(contents=('parents', 'ishead', 'isclose'),
                             selectable=True)
    return csinfo.create(repo, style=style, custom=custom)
