# wconfig.py - Writable config object wrapper
#
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import cStringIO
import ConfigParser
from mercurial import error, util, config as config_mod

try:
    from iniparse import INIConfig
    _hasiniparse = True
except ImportError:
    _hasiniparse = False

if _hasiniparse:
    try:
        from iniparse import change_comment_syntax  # iniparse>=0.3.2
        change_comment_syntax(allow_rem=False)
    except (ImportError, TypeError):
        # TODO: yet need to care about iniparse<0.3.2 ??
        import re
        from iniparse.ini import CommentLine
        # Monkypatch this regex to prevent iniparse from considering
        # 'rem' as a comment
        CommentLine.regex = re.compile(r'^(?P<csep>[%;#])(?P<comment>.*)$')

class _wsortdict(object):
    """Wrapper for config.sortdict to record set/del operations"""
    def __init__(self, dict):
        self._dict = dict
        self._log = []  # log of set/del operations

    # no need to wrap copy() since we don't keep trac of it.

    def __contains__(self, key):
        return key in self._dict

    def __getitem__(self, key):
        return self._dict[key]

    def __setitem__(self, key, val):
        self._setdict(key, val)
        self._logset(key, val)

    def _logset(self, key, val):
        """Record set operation to log; called also by _wconfig"""
        def op(target):
            target[key] = val
        self._log.append(op)

    def _setdict(self, key, val):
        if key not in self._dict:
            self._dict[key] = val  # append
            return

        # preserve current order
        def get(k):
            if k == key:
                return val
            else:
                return self._dict[k]
        for k in list(self._dict):
            self._dict[k] = get(k)

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def update(self, src):
        if isinstance(src, _wsortdict):
            src = src._dict
        self._dict.update(src)
        self._logupdate(src)

    def _logupdate(self, src):
        """Record update operation to log; called also by _wconfig"""
        for k in src:
            self._logset(k, src[k])

    def __delitem__(self, key):
        del self._dict[key]
        self._logdel(key)

    def _logdel(self, key):
        """Record del operation to log"""
        def op(target):
            try:
                del target[key]
            except KeyError:  # in case somebody else deleted it
                pass
        self._log.append(op)

    def __getattr__(self, name):
        return getattr(self._dict, name)

    def _replaylog(self, target):
        """Replay operations against the given target; called by _wconfig"""
        for op in self._log:
            op(target)

class _wconfig(object):
    """Wrapper for config.config to replay changes to iniparse on write

    This records set/del operations and replays them on write().
    Source file is reloaded before replaying changes, so that it doesn't
    override changes for another part of file made by somebody else:

    - A "set foo = bar", B "set baz = bax" => "foo = bar, baz = bax"
    - A "set foo = bar", B "set foo = baz" => "foo = baz" (last one wins)
    - A "del foo", B "set foo = baz" => "foo = baz" (last one wins)
    - A "set foo = bar", B "del foo" => "" (last one wins)
    """

    def __init__(self, data=None):
        self._config = config_mod.config(data)
        self._readfiles = []  # list of read (path, fp, sections, remap)
        self._sections = {}

        if isinstance(data, self.__class__):  # keep log
            self._readfiles.extend(data._readfiles)
            self._sections.update(data._sections)
        elif data:  # record as changes
            self._logupdates(data)

    def copy(self):
        return self.__class__(self)

    def __contains__(self, section):
        return section in self._config

    def __getitem__(self, section):
        try:
            return self._sections[section]
        except KeyError:
            if self._config[section]:
                self._sections[section] = _wsortdict(self._config[section])
                return self._sections[section]
            else:
                return {}

    def __iter__(self):
        return iter(self._config)

    def update(self, src):
        self._config.update(src)
        self._logupdates(src)

    def _logupdates(self, src):
        for s in src:
            self[s]._logupdate(src[s])

    def set(self, section, item, value, source=''):
        self._setconfig(section, item, value, source)
        self[section]._logset(item, value)

    def _setconfig(self, section, item, value, source):
        if item not in self._config[section]:
            # need to handle 'source'
            self._config.set(section, item, value, source)
        else:
            self[section][item] = value

    def remove(self, section, item):
        del self[section][item]
        self[section]._logdel(item)

    def read(self, path, fp=None, sections=None, remap=None):
        self._config.read(path, fp, sections, remap)
        self._readfiles.append((path, fp, sections, remap))

    def write(self, dest):
        ini = self._readini()
        self._replaylogs(ini)
        dest.write(str(ini))

    def _readini(self):
        """Create iniparse object by reading every file"""
        if len(self._readfiles) > 1:
            raise NotImplementedError("wconfig does not support read() more "
                                      "than once")

        def newini(fp=None):
            try:
                # TODO: optionxformvalue isn't used by INIConfig ?
                return INIConfig(fp=fp, optionxformvalue=None)
            except ConfigParser.MissingSectionHeaderError, err:
                raise error.ParseError(err.message.splitlines()[0],
                                       '%s:%d' % (err.filename, err.lineno))
            except ConfigParser.ParsingError, err:
                if err.errors:
                    loc = '%s:%d' % (err.filename, err.errors[0][0])
                else:
                    loc = err.filename
                raise error.ParseError(err.message.splitlines()[0], loc)

        if not self._readfiles:
            return newini()

        path, fp, sections, remap = self._readfiles[0]
        if sections:
            raise NotImplementedError("wconfig does not support 'sections'")
        if remap:
            raise NotImplementedError("wconfig does not support 'remap'")

        if fp:
            fp.seek(0)
            return newini(fp)
        else:
            fp = util.posixfile(path, 'rb')
            try:
                return newini(fp)
            finally:
                fp.close()

    def _replaylogs(self, ini):
        def getsection(ini, section):
            if section in ini:
                return ini[section]
            else:
                newns = getattr(ini, '_new_namespace',
                                getattr(ini, 'new_namespace'))
                return newns(section)

        for k, v in self._sections.iteritems():
            v._replaylog(getsection(ini, k))

    def __getattr__(self, name):
        return getattr(self._config, name)

def config(data=None):
    """Create writable config if iniparse available; otherwise readonly obj

    You can test whether the returned obj is writable or not by
    `hasattr(obj, 'write')`.
    """
    if _hasiniparse:
        return _wconfig(data)
    else:
        return config_mod.config(data)

def readfile(path):
    """Read the given file to return config object"""
    c = config()
    c.read(path)
    return c

def writefile(config, path):
    """Write the given config obj to the specified file"""
    # normalize line endings
    buf = cStringIO.StringIO()
    config.write(buf)
    data = '\n'.join(buf.getvalue().splitlines()) + '\n'

    if os.name == 'nt':
        # no atomic rename to the existing file that may fail occasionally
        # for unknown reasons, possibly because of our QFileSystemWatcher or
        # a virus scanner.  also it breaks NTFS symlink (issue #2181).
        openfile = util.posixfile
    else:
        # atomic rename is reliable on Unix
        openfile = util.atomictempfile
    f = openfile(os.path.realpath(path), 'w')
    try:
        f.write(data)
        f.close()
    finally:
        del f  # unlink temp file
