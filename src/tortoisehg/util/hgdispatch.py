# hgdispatch.py - Mercurial command wrapper for TortoiseHg
#
# Copyright 2007, 2009 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import urllib2, urllib

from mercurial import error, extensions, subrepo, util
from mercurial import dispatch as dispatchmod

from tortoisehg.util import hgversion
from tortoisehg.util.i18n import agettext as _

testedwith = hgversion.testedwith

# exception handling different from _runcatch()
def _dispatch(orig, req):
    ui = req.ui
    try:
        return orig(req)
    except subrepo.SubrepoAbort, e:
        errormsg = str(e)
        label = 'ui.error'
        if e.subrepo:
            label += ' subrepo=%s' % urllib.quote(e.subrepo)
        ui.write_err(_('abort: ') + errormsg + '\n', label=label)
        if e.hint:
            ui.write_err(_('hint: ') + str(e.hint) + '\n', label=label)
    except util.Abort, e:
        ui.write_err(_('abort: ') + str(e) + '\n', label='ui.error')
        if e.hint:
            ui.write_err(_('hint: ') + str(e.hint) + '\n', label='ui.error')
    except error.RepoError, e:
        ui.write_err(str(e) + '\n', label='ui.error')
    except urllib2.HTTPError, e:
        err = _('HTTP Error: %d (%s)') % (e.code, e.msg)
        ui.write_err(err + '\n', label='ui.error')
    except urllib2.URLError, e:
        err = _('URLError: %s') % str(e.reason)
        try:
            import ssl  # Python 2.6 or backport for 2.5
            if isinstance(e.args[0], ssl.SSLError):
                parts = e.args[0].strerror.split(':')
                if len(parts) == 7:
                    file, line, level, _errno, lib, func, reason = parts
                    if func == 'SSL3_GET_SERVER_CERTIFICATE':
                        err = _('SSL: Server certificate verify failed')
                    elif _errno == '00000000':
                        err = _('SSL: unknown error %s:%s') % (file, line)
                    else:
                        err = _('SSL error: %s') % reason
        except ImportError:
            pass
        ui.write_err(err + '\n', label='ui.error')

    return -1

def uisetup(ui):
    # uisetup() is called after the initial dispatch(), so this only makes an
    # effect on command server
    extensions.wrapfunction(dispatchmod, '_dispatch', _dispatch)
