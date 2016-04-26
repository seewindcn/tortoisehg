# pipeui.py - append parsable label to output, prompt and progress
#
# Copyright 2014 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

"""append parsable label to output, prompt and progress

This extension is intended to be used with the command server, so the packed
message provides no reliable length field.

Message structure::

    without label:
    |msg...|

    with label:
    |'\1'|label...|'\n'|msg...|

    progress:
    |'\1'|'ui.progress'|'\n'|topic|'\0'|pos|'\0'|item|'\0'|unit|'\0'|total|

    prompt:
    |'\1'|'ui.prompt'|'\n'|msg|'\0'|default|

Labels:

ui.getpass (with ui.prompt)
    denotes message for password prompt
ui.progress
    contains packed progress data (not for display)
ui.promptchoice (with ui.prompt)
    denotes message and choices for prompt
"""

import time

from mercurial import util

from tortoisehg.util import hgversion
from tortoisehg.util.i18n import agettext as _

testedwith = hgversion.testedwith

class _labeledstr(str):
    r"""
    >>> a = _labeledstr('foo', 'ui.warning')
    >>> a.packed()
    '\x01ui.warning\nfoo'
    >>> _labeledstr(a, 'ui.error').packed()
    '\x01ui.warning ui.error\nfoo'
    >>> _labeledstr('foo', '').packed()
    'foo'
    >>> _labeledstr('\1foo', '').packed()
    '\x01\n\x01foo'
    >>> _labeledstr(a, '') is a  # fast path
    True
    """

    def __new__(cls, s, l):
        if isinstance(s, cls):
            if not l:
                return s
            if s._label:
                l = s._label + ' ' + l
        t = str.__new__(cls, s)
        t._label = l
        return t

    def packed(self):
        if not self._label and not self.startswith('\1'):
            return str(self)
        return '\1%s\n%s' % (self._label, self)

def _packmsgs(msgs, label):
    r"""
    >>> _packmsgs(['foo'], '')
    ['foo']
    >>> _packmsgs(['foo ', 'bar'], '')
    ['foo bar']
    >>> _packmsgs(['foo ', 'bar'], 'ui.status')
    ['\x01ui.status\nfoo bar']
    >>> _packmsgs(['foo ', _labeledstr('bar', 'log.branch')], '')
    ['foo ', '\x01log.branch\nbar']
    """
    if not any(isinstance(e, _labeledstr) for e in msgs):
        # pack into single message to avoid overhead of label header and
        # channel protocol; also it's convenient for command-server client
        # to receive the whole message at once.
        if len(msgs) > 1:
            msgs = [''.join(msgs)]
        if not label:
            # fast path
            return msgs
    return [_labeledstr(e, label).packed() for e in msgs]

def splitmsgs(data):
    r"""Split data to list of packed messages assuming that original messages
    contain no '\1' character

    >>> splitmsgs('')
    []
    >>> splitmsgs('\x01ui.warning\nfoo\x01\nbar')
    ['\x01ui.warning\nfoo', '\x01\nbar']
    >>> splitmsgs('foo\x01ui.warning\nbar')
    ['foo', '\x01ui.warning\nbar']
    """
    msgs = data.split('\1')
    if msgs[0]:
        return msgs[:1] + ['\1' + e for e in msgs[1:]]
    else:
        return ['\1' + e for e in msgs[1:]]

def unpackmsg(data):
    r"""Try to unpack data to original message and label

    >>> unpackmsg('foo')
    ('foo', '')
    >>> unpackmsg('\x01ui.warning\nfoo')
    ('foo', 'ui.warning')
    >>> unpackmsg('\x01ui.warning')  # immature end
    ('', 'ui.warning')
    """
    if not data.startswith('\1'):
        return data, ''
    try:
        label, msg = data[1:].split('\n', 1)
        return msg, label
    except ValueError:
        return '', data[1:]

def _packprompt(msg, default):
    r"""
    >>> _packprompt('foo', None)
    'foo\x00'
    >>> _packprompt(_labeledstr('$$ &Yes', 'ui.promptchoice'), 'y').packed()
    '\x01ui.promptchoice\n$$ &Yes\x00y'
    """
    s = '\0'.join((msg, default or ''))
    if not isinstance(msg, _labeledstr):
        return s
    return _labeledstr(s, msg._label)

def unpackprompt(msg):
    """Try to unpack prompt message to original message and default value"""
    args = msg.split('\0', 1)
    if len(args) == 1:
        return msg, ''
    else:
        return args

def _fromint(n):
    if n is None:
        return ''
    return str(n)

def _toint(s):
    if not s:
        return None
    return int(s)

def _packprogress(topic, pos, item, unit, total):
    r"""
    >>> _packprogress('updating', 1, 'foo', 'files', 5)
    'updating\x001\x00foo\x00files\x005'
    >>> _packprogress('updating', None, '', '', None)
    'updating\x00\x00\x00\x00'
    """
    return '\0'.join((topic, _fromint(pos), item, unit, _fromint(total)))

def unpackprogress(msg):
    r"""Try to unpack progress message to tuple of parameters

    >>> unpackprogress('updating\x001\x00foo\x00files\x005')
    ('updating', 1, 'foo', 'files', 5)
    >>> unpackprogress('updating\x00\x00\x00\x00')
    ('updating', None, '', '', None)
    >>> unpackprogress('updating\x001\x00foo\x00files')  # immature end
    ('updating', None, '', '', None)
    >>> unpackprogress('')  # no separator
    ('', None, '', '', None)
    >>> unpackprogress('updating\x00a\x00foo\x00files\x005')  # invalid pos
    ('updating', None, '', '', None)
    """
    try:
        topic, pos, item, unit, total = msg.split('\0')
        return topic, _toint(pos), item, unit, _toint(total)
    except ValueError:
        # fall back to termination
        topic = msg.split('\0', 1)[0]
        return topic, None, '', '', None

_progressrefresh = 0.1  # [sec]

def _extenduiclass(parcls):
    class pipeui(parcls):
        _lastprogresstopic = None
        _lastprogresstime = 0

        def write(self, *args, **opts):
            if self._buffers:
                # do not label buffered data because it can be written later
                super(pipeui, self).write(*args, **opts)
                return
            label = opts.get('label', '')
            super(pipeui, self).write(*_packmsgs(args, label), **opts)

        def write_err(self, *args, **opts):
            label = opts.get('label', '')
            super(pipeui, self).write_err(*_packmsgs(args, label), **opts)

        def prompt(self, msg, default='y'):
            fullmsg = _packprompt(msg, default)
            return super(pipeui, self).prompt(fullmsg, default)

        # write raw prompt value with choices
        def promptchoice(self, prompt, default=0):
            _msg, choices = self.extractchoices(prompt)
            resps = [r for r, _t in choices]
            prompt = self.label(prompt, 'ui.promptchoice')
            r = self.prompt(prompt, resps[default])
            try:
                return resps.index(r.lower())
            except ValueError:
                raise util.Abort(_('unrecognized response: %s') % r)

        def getpass(self, prompt=None, default=None):
            prompt = self.label(prompt or _('password: '), 'ui.getpass')
            return super(pipeui, self).getpass(prompt, default)

        def progress(self, topic, pos, item='', unit='', total=None):
            now = time.time()
            if (topic == self._lastprogresstopic and pos is not None
                and now - self._lastprogresstime < _progressrefresh):
                # skip busy increment of the same topic
                return
            if pos is None:
                # the topic is about to be closed
                self._lastprogresstopic = None
            else:
                self._lastprogresstopic = topic
            self._lastprogresstime = now
            msg = _packprogress(topic, pos, item, unit, total)
            self.write_err(msg, label='ui.progress')

        def label(self, msg, label):
            return _labeledstr(msg, label)

    return pipeui

def uisetup(ui):
    ui.__class__ = _extenduiclass(ui.__class__)
