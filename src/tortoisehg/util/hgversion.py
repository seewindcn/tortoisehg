# hgversion.py - Version information for Mercurial
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re

try:
    # post 1.1.2
    from mercurial import util
    hgversion = util.version()
except AttributeError:
    # <= 1.1.2
    from mercurial import version
    hgversion = version.get_version()

testedwith = '3.6 3.7'

def checkhgversion(v):
    """range check the Mercurial version"""
    reqvers = testedwith.split()
    v = v.split('+')[0]
    if not v or v == 'unknown' or len(v) >= 12:
        # can't make any intelligent decisions about unknown or hashes
        return
    vers = re.split(r'\.|-', v)[:2]
    if len(vers) < 2:
        return
    if '.'.join(vers) in reqvers:
        return
    return ('This version of TortoiseHg requires Mercurial version %s.n to '
            '%s.n, but found %s') % (reqvers[0], reqvers[-1], v)
