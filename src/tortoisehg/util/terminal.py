import os, sys
from mercurial import util, ui

def defaultshell():
    if sys.platform == 'darwin':
        shell = None # Terminal.App does not support open-to-folder
    elif os.name == 'nt':
        shell = 'cmd.exe /K title %(reponame)s'
    else:
        shell = 'xterm -T "%(reponame)s"'
    return shell

_defaultshell = defaultshell()

def _getplatformexecutablekey():
    if sys.platform == 'darwin':
        key = 'executable-osx'
    elif os.name == 'nt':
        key = 'executable-win'
    else:
        key = 'executable-unix'
    return key

_platformexecutablekey = _getplatformexecutablekey()

def _toolstr(ui, tool, part, default=""):
    return ui.config("terminal-tools", tool + "." + part, default)

toolcache = {}
def _findtool(ui, tool):
    global toolcache
    if tool in toolcache:
        return toolcache[tool]
    for kn in ("regkey", "regkeyalt"):
        k = _toolstr(ui, tool, kn)
        if not k:
            continue
        p = util.lookupreg(k, _toolstr(ui, tool, "regname"))
        if p:
            p = util.findexe(p + _toolstr(ui, tool, "regappend"))
            if p:
                toolcache[tool] = p
                return p
    global _platformexecutablekey
    exe = _toolstr(ui, tool, _platformexecutablekey)
    if not exe:
        exe = _toolstr(ui, tool, 'executable', tool)
    path = util.findexe(util.expandpath(exe))
    if path:
        toolcache[tool] = path
        return path
    elif tool != exe:
        path = util.findexe(tool)
        toolcache[tool] = path
        return path
    toolcache[tool] = None
    return None

def _findterminal(ui):
    '''returns tuple of terminal name and terminal path.

    tools matched by pattern are returned as (name, toolpath)
    tools detected by search are returned as (name, toolpath)
    tortoisehg.shell is returned as  (None, tortoisehg.shell)

    So first return value is an [terminal-tool] name or None and
    second return value is a toolpath or user configured command line
    '''

    # first check for tool specified in terminal-tools
    tools = {}
    for k, v in ui.configitems("terminal-tools"):
        t = k.split('.')[0]
        if t not in tools:
            try:
                priority = int(_toolstr(ui, t, "priority", "0"))
            except ValueError, e:
                priority = -100
            tools[t] = priority
    names = tools.keys()
    tools = sorted([(-p, t) for t, p in tools.items()])
    terminal = ui.config('tortoisehg', 'shell')
    if terminal:
        if terminal not in names:
            # if tortoisehg.terminal does not match an terminal-tools entry, take
            # the value directly
            return (None, terminal)
        # else select this terminal as highest priority (may still use another if
        # it is not found on this machine)
        tools.insert(0, (None, terminal))
    for p, t in tools:
        toolpath = _findtool(ui, t)
        if toolpath:
            return (t, util.shellquote(toolpath))

    # fallback to the default shell
    global _defaultshell
    return (None, _defaultshell)

def detectterminal(ui_):
    'returns tuple of terminal tool path and arguments'
    if ui_ is None:
        ui_ = ui.ui()
    name, pathorconfig = _findterminal(ui_)
    if name is None:
        return (pathorconfig, None)
    else:
        args = _toolstr(ui_, name, "args")
        return (pathorconfig, args)

def findterminals(ui):
    seen = set()
    for key, value in ui.configitems('terminal-tools'):
        t = key.split('.')[0]
        seen.add(t)
    return [t for t in seen if _findtool(ui, t)]
