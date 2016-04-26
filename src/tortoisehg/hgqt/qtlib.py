# qtlib.py - Qt utility code
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import sys
import atexit
import posixpath
import shutil
import shlex
import stat
import subprocess
import tempfile
import re
import sip
import weakref

from mercurial import extensions, error, util

from tortoisehg.util import hglib, paths, editor, terminal
from tortoisehg.util.i18n import _
from hgext.color import _styles

from PyQt4.QtCore import *
from PyQt4.QtGui import *

try:
    import win32con
    openflags = win32con.CREATE_NO_WINDOW
except ImportError:
    openflags = 0

# largest allowed size for widget, defined in <src/gui/kernel/qwidget.h>
QWIDGETSIZE_MAX = (1 << 24) - 1

if PYQT_VERSION < 0x40704:
    # QObject.sender() goes wrong if connection made in Qt layer.  consider
    # using QSignalMapper for zero-argument slots instead.
    def senderSafeSlot(*types, **opts):
        def deco(func):
            return func
        return deco
else:
    senderSafeSlot = pyqtSlot

tmproot = None
def gettempdir():
    global tmproot
    def cleanup():
        def writeable(arg, dirname, names):
            for name in names:
                fullname = os.path.join(dirname, name)
                os.chmod(fullname, os.stat(fullname).st_mode | stat.S_IWUSR)
        try:
            os.path.walk(tmproot, writeable, None)
            shutil.rmtree(tmproot)
        except:
            pass
    if not tmproot:
        tmproot = tempfile.mkdtemp(prefix='thg.')
        atexit.register(cleanup)
    return tmproot

def openhelpcontents(url):
    'Open online help, use local CHM file if available'
    if not url.startswith('http'):
        fullurl = 'http://tortoisehg.readthedocs.org/en/latest/' + url
        # Use local CHM file if it can be found
        if os.name == 'nt' and paths.bin_path:
            chm = os.path.join(paths.bin_path, 'doc', 'TortoiseHg.chm')
            if os.path.exists(chm):
                fullurl = (r'mk:@MSITStore:%s::/' % chm) + url
                openlocalurl(fullurl)
                return
        QDesktopServices.openUrl(QUrl(fullurl))

def openlocalurl(path):
    '''open the given path with the default application

    takes str, unicode or QString as argument
    returns True if open was successfull
    '''

    if isinstance(path, str):
        path = hglib.tounicode(path)
    else:
        path = unicode(path)
    if os.name == 'nt' and path.startswith('\\\\'):
        # network share, special handling because of qt bug 13359
        # see http://bugreports.qt.nokia.com/browse/QTBUG-13359
        qurl = QUrl()
        qurl.setUrl(QDir.toNativeSeparators(path))
    else:
        qurl = QUrl.fromLocalFile(path)
    return QDesktopServices.openUrl(qurl)

def openfiles(repo, files, parent=None):
    for filename in files:
        openlocalurl(repo.wjoin(filename))

def editfiles(repo, files, lineno=None, search=None, parent=None):
    if len(files) == 1:
        # if editing a single file, open in cwd context of that file
        filename = files[0].strip()
        if not filename:
            return
        files = [filename]
        path = repo.wjoin(filename)
        cwd = os.path.dirname(path)
        files = [os.path.basename(path)]
    else:
        # else edit in cwd context of repo root
        cwd = repo.root

    toolpath, args, argsln, argssearch = editor.detecteditor(repo, files)
    if os.path.basename(toolpath) in ('vi', 'vim', 'hgeditor'):
        res = QMessageBox.critical(parent,
                    _('No visual editor configured'),
                    _('Please configure a visual editor.'))
        from tortoisehg.hgqt.settings import SettingsDialog
        dlg = SettingsDialog(False, focus='tortoisehg.editor')
        dlg.exec_()
        return

    files = [util.shellquote(util.localpath(f)) for f in files]
    assert len(files) == 1 or lineno == None

    cmdline = None
    if search:
        assert lineno is not None
        if argssearch:
            cmdline = ' '.join([toolpath, argssearch])
            cmdline = cmdline.replace('$LINENUM', str(lineno))
            cmdline = cmdline.replace('$SEARCH', search)
        elif argsln:
            cmdline = ' '.join([toolpath, argsln])
            cmdline = cmdline.replace('$LINENUM', str(lineno))
        elif args:
            cmdline = ' '.join([toolpath, args])
    elif lineno:
        if argsln:
            cmdline = ' '.join([toolpath, argsln])
            cmdline = cmdline.replace('$LINENUM', str(lineno))
        elif args:
            cmdline = ' '.join([toolpath, args])
    else:
        if args:
            cmdline = ' '.join([toolpath, args])

    if cmdline is None:
        # editor was not specified by editor-tools configuration, fall
        # back to older tortoisehg.editor OpenAtLine parsing
        cmdline = ' '.join([toolpath] + files) # default
        try:
            regexp = re.compile('\[([^\]]*)\]')
            expanded = []
            pos = 0
            for m in regexp.finditer(toolpath):
                expanded.append(toolpath[pos:m.start()-1])
                phrase = toolpath[m.start()+1:m.end()-1]
                pos = m.end()+1
                if '$LINENUM' in phrase:
                    if lineno is None:
                        # throw away phrase
                        continue
                    phrase = phrase.replace('$LINENUM', str(lineno))
                elif '$SEARCH' in phrase:
                    if search is None:
                        # throw away phrase
                        continue
                    phrase = phrase.replace('$SEARCH', search)
                if '$FILE' in phrase:
                    phrase = phrase.replace('$FILE', files[0])
                    files = []
                expanded.append(phrase)
            expanded.append(toolpath[pos:])
            cmdline = ' '.join(expanded + files)
        except ValueError, e:
            # '[' or ']' not found
            pass
        except TypeError, e:
            # variable expansion failed
            pass

    shell = not (len(cwd) >= 2 and cwd[0:2] == r'\\')
    try:
        if '$FILES' in cmdline:
            cmdline = cmdline.replace('$FILES', ' '.join(files))
            cmdline = util.quotecommand(cmdline)
            subprocess.Popen(cmdline, shell=shell, creationflags=openflags,
                             stderr=None, stdout=None, stdin=None, cwd=cwd)
        elif '$FILE' in cmdline:
            for file in files:
                cmd = cmdline.replace('$FILE', file)
                cmd = util.quotecommand(cmd)
                subprocess.Popen(cmd, shell=shell, creationflags=openflags,
                                 stderr=None, stdout=None, stdin=None, cwd=cwd)
        else:
            # assume filenames were expanded already
            cmdline = util.quotecommand(cmdline)
            subprocess.Popen(cmdline, shell=shell, creationflags=openflags,
                             stderr=None, stdout=None, stdin=None, cwd=cwd)
    except (OSError, EnvironmentError), e:
        QMessageBox.warning(parent,
                _('Editor launch failure'),
                u'%s : %s' % (hglib.tounicode(cmdline),
                              hglib.tounicode(str(e))))

def openshell(root, reponame, ui=None):
    if not os.path.exists(root):
        WarningMsgBox(
            _('Failed to open path in terminal'),
            _('"%s" is not a valid directory') % hglib.tounicode(root))
        return
    shell, args = terminal.detectterminal(ui)
    if shell:
        if args:
            shell = shell + ' ' + util.expandpath(args)
        # check invalid expression in tortoisehg.shell.  we shouldn't apply
        # string formatting to untrusted value, but too late to change syntax.
        try:
            shell % {'root': '', 'reponame': ''}
        except (KeyError, TypeError, ValueError):
            # KeyError: "%(invalid)s", TypeError: "%(root)d", ValueError: "%"
            ErrorMsgBox(_('Failed to open path in terminal'),
                        _('Invalid configuration: %s')
                        % hglib.tounicode(shell))
            return
        shellcmd = shell % {'root': root, 'reponame': reponame}

        cwd = os.getcwd()
        try:
            # Unix: QProcess.startDetached(program) cannot parse single-quoted
            # parameters built using util.shellquote().
            # Windows: subprocess.Popen(program, shell=True) cannot spawn
            # cmd.exe in new window, probably because the initial cmd.exe is
            # invoked with SW_HIDE.
            os.chdir(root)
            if os.name == 'nt':
                # can't parse shellcmd in POSIX way
                started = QProcess.startDetached(hglib.tounicode(shellcmd))
            else:
                fullargs = map(hglib.tounicode, shlex.split(shellcmd))
                started = QProcess.startDetached(fullargs[0], fullargs[1:])
        finally:
            os.chdir(cwd)
        if not started:
            ErrorMsgBox(_('Failed to open path in terminal'),
                        _('Unable to start the following command:'), shellcmd)
    else:
        InfoMsgBox(_('No shell configured'),
                   _('A terminal shell must be configured'))


def isDarkTheme(palette=None):
    """True if white-on-black color scheme is preferable"""
    if not palette:
        palette = QApplication.palette()
    return palette.color(QPalette.Base).black() >= 0x80

# _styles maps from ui labels to effects
# _effects maps an effect to font style properties.  We define a limited
# set of _effects, since we convert color effect names to font style
# effect programatically.

_effects = {
    'bold': 'font-weight: bold',
    'italic': 'font-style: italic',
    'underline': 'text-decoration: underline',
}

_thgstyles = {
   # Styles defined by TortoiseHg
   'log.branch': 'black #aaffaa_background',
   'log.patch': 'black #aaddff_background',
   'log.unapplied_patch': 'black #dddddd_background',
   'log.tag': 'black #ffffaa_background',
   'log.bookmark': 'blue #ffffaa_background',
   'log.curbookmark': 'black #ffdd77_background',
   'log.modified': 'black #ffddaa_background',
   'log.added': 'black #aaffaa_background',
   'log.removed': 'black #ffcccc_background',
   'log.warning': 'black #ffcccc_background',
   'status.deleted': 'red bold',
   'ui.error': 'red bold #ffcccc_background',
   'ui.warning': 'black bold #ffffaa_background',
   'control': 'black bold #dddddd_background',
}

thgstylesheet = '* { white-space: pre; font-family: monospace;' \
                ' font-size: 9pt; }'
tbstylesheet = 'QToolBar { border: 0px }'

def configstyles(ui):
    # extensions may provide more labels and default effects
    for name, ext in extensions.extensions():
        _styles.update(getattr(ext, 'colortable', {}))

    # tortoisehg defines a few labels and default effects
    _styles.update(_thgstyles)

    # allow the user to override
    for status, cfgeffects in ui.configitems('color'):
        if '.' not in status:
            continue
        cfgeffects = ui.configlist('color', status)
        _styles[status] = ' '.join(cfgeffects)

    for status, cfgeffects in ui.configitems('thg-color'):
        if '.' not in status:
            continue
        cfgeffects = ui.configlist('thg-color', status)
        _styles[status] = ' '.join(cfgeffects)

# See http://doc.trolltech.com/4.2/richtext-html-subset.html
# and http://www.w3.org/TR/SVG/types.html#ColorKeywords

def geteffect(labels):
    'map labels like "log.date" to Qt font styles'
    labels = str(labels) # Could be QString
    effects = []
    # Multiple labels may be requested
    for l in labels.split():
        if not l:
            continue
        # Each label may request multiple effects
        es = _styles.get(l, '')
        for e in es.split():
            if e in _effects:
                effects.append(_effects[e])
            elif e.endswith('_background'):
                e = e[:-11]
                if e.startswith('#') or e in QColor.colorNames():
                    effects.append('background-color: ' + e)
            elif e.startswith('#') or e in QColor.colorNames():
                # Accept any valid QColor
                effects.append('color: ' + e)
    return ';'.join(effects)

def gettextcoloreffect(labels):
    """Map labels like "log.date" to foreground color if available"""
    for l in str(labels).split():
        if not l:
            continue
        for e in _styles.get(l, '').split():
            if e.startswith('#') or e in QColor.colorNames():
                return QColor(e)
    return QColor()

def getbgcoloreffect(labels):
    """Map labels like "log.date" to background color if available

    Returns QColor object. You may need to check validity by isValid().
    """
    for l in str(labels).split():
        if not l:
            continue
        for e in _styles.get(l, '').split():
            if e.endswith('_background'):
                return QColor(e[:-11])
    return QColor()

NAME_MAP = {
    'fg': 'color', 'bg': 'background-color', 'family': 'font-family',
    'size': 'font-size', 'weight': 'font-weight', 'space': 'white-space',
    'style': 'font-style', 'decoration': 'text-decoration',
}

def markup(msg, **styles):
    style = {'white-space': 'pre'}
    for name, value in styles.items():
        if not value:
            continue
        if name in NAME_MAP:
            name = NAME_MAP[name]
        style[name] = value
    style = ';'.join(['%s: %s' % t for t in style.items()])
    msg = hglib.tounicode(msg)
    msg = Qt.escape(msg)
    msg = msg.replace('\n', '<br />')
    return u'<span style="%s">%s</span>' % (style, msg)

def descriptionhtmlizer(ui):
    """Return a function to mark up ctx.description() as an HTML

    >>> from mercurial import ui
    >>> u = ui.ui()
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo <bar> \\n& <baz>')
    u'foo &lt;bar&gt; \\n&amp; &lt;baz&gt;'

    changeset hash link:
    >>> htmlize('foo af50a62e9c20 bar')
    u'foo <a href="cset:af50a62e9c20">af50a62e9c20</a> bar'
    >>> htmlize('af50a62e9c2040dcdaf61ba6a6400bb45ab56410') # doctest: +ELLIPSIS
    u'<a href="cset:af...10">af...10</a>'

    http/https links:
    >>> s = htmlize('foo http://example.com:8000/foo?bar=baz&bax#blah')
    >>> (s[:63], s[63:]) # doctest: +NORMALIZE_WHITESPACE
    (u'foo <a href="http://example.com:8000/foo?bar=baz&amp;bax#blah">',
     u'http://example.com:8000/foo?bar=baz&amp;bax#blah</a>')
    >>> htmlize('https://example/')
    u'<a href="https://example/">https://example/</a>'

    issue links:
    >>> u.setconfig('tortoisehg', 'issue.regex', r'#(\\d+)\\b')
    >>> u.setconfig('tortoisehg', 'issue.link', 'http://example/issue/{1}/')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo <a href="http://example/issue/123/">#123</a>'

    missing issue.link setting:
    >>> u.setconfig('tortoisehg', 'issue.link', '')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'

    too many replacements in issue.link:
    >>> u.setconfig('tortoisehg', 'issue.link', 'http://example/issue/{1}/{2}')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'

    invalid regexp in issue.regex:
    >>> u.setconfig('tortoisehg', 'issue.regex', '(')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'
    >>> htmlize('http://example/')
    u'<a href="http://example/">http://example/</a>'
    """
    csmatch = r'(\b[0-9a-f]{12}(?:[0-9a-f]{28})?\b)'
    httpmatch = r'(\b(http|https)://([-A-Za-z0-9+&@#/%?=~_()|!:,.;]*' \
                r'[-A-Za-z0-9+&@#/%=~_()|]))'
    regexp = r'%s|%s' % (csmatch, httpmatch)
    bodyre = re.compile(regexp)

    issuematch = ui.config('tortoisehg', 'issue.regex')
    issuerepl = ui.config('tortoisehg', 'issue.link')
    if issuematch and issuerepl:
        regexp += '|(%s)' % issuematch
        try:
            bodyre = re.compile(regexp)
        except re.error:
            pass

    def htmlize(desc):
        """Mark up ctx.description() [localstr] as an HTML [unicode]"""
        desc = unicode(Qt.escape(hglib.tounicode(desc)))

        buf = ''
        pos = 0
        for m in bodyre.finditer(desc):
            a, b = m.span()
            if a >= pos:
                buf += desc[pos:a]
                pos = b
            groups = m.groups()
            if groups[0]:
                cslink = groups[0]
                buf += '<a href="cset:%s">%s</a>' % (cslink, cslink)
            if groups[1]:
                urllink = groups[1]
                buf += '<a href="%s">%s</a>' % (urllink, urllink)
            if len(groups) > 4 and groups[4]:
                issue = groups[4]
                issueparams = groups[4:]
                try:
                    link = re.sub(r'\{(\d+)\}',
                                  lambda m: issueparams[int(m.group(1))],
                                  issuerepl)
                    buf += '<a href="%s">%s</a>' % (link, issue)
                except IndexError:
                    buf += issue

        if pos < len(desc):
            buf += desc[pos:]

        return buf

    return htmlize

_iconcache = {}

if getattr(sys, 'frozen', False) and os.name == 'nt':
    def iconpath(f, *insidef):
        return posixpath.join(':/icons', f, *insidef)
else:
    def iconpath(f, *insidef):
        return os.path.join(paths.get_icon_path(), f, *insidef)

if hasattr(QIcon, 'hasThemeIcon'):  # PyQt>=4.7
    def _findthemeicon(name):
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
else:
    def _findthemeicon(name):
        pass

def _findcustomicon(name):
    # let a user set the icon of a custom tool button
    if os.path.isabs(name):
        path = name
        if QFile.exists(path):
            return QIcon(path)
    return None

# http://standards.freedesktop.org/icon-theme-spec/icon-theme-spec-latest.html
_SCALABLE_ICON_PATHS = [(QSize(), 'scalable/actions', '.svg'),
                        (QSize(), 'scalable/apps', '.svg'),
                        (QSize(), 'scalable/status', '.svg'),
                        (QSize(16, 16), '16x16/actions', '.png'),
                        (QSize(16, 16), '16x16/apps', '.png'),
                        (QSize(16, 16), '16x16/mimetypes', '.png'),
                        (QSize(16, 16), '16x16/status', '.png'),
                        (QSize(22, 22), '22x22/actions', '.png'),
                        (QSize(32, 32), '32x32/actions', '.png'),
                        (QSize(32, 32), '32x32/status', '.png'),
                        (QSize(24, 24), '24x24/actions', '.png')]

def getallicons():
    """Get a sorted, unique list of all available icons"""
    iconset = set()
    for size, subdir, sfx in _SCALABLE_ICON_PATHS:
        path = iconpath(subdir)
        d = QDir(path)
        d.setNameFilters(['*%s' % sfx])
        for iconname in d.entryList():
            iconset.add(unicode(iconname).rsplit('.', 1)[0])
    return sorted(iconset)

def _findscalableicon(name):
    """Find icon from qrc by using freedesktop-like icon lookup"""
    o = QIcon()
    for size, subdir, sfx in _SCALABLE_ICON_PATHS:
        path = iconpath(subdir, name + sfx)
        if QFile.exists(path):
            for mode in (QIcon.Normal, QIcon.Active):
                o.addFile(path, size, mode)
    if not o.isNull():
        return o

def geticon(name):
    """
    Return a QIcon for the specified name. (the given 'name' parameter
    must *not* provide the extension).

    This searches for the icon from theme, Qt resource or icons directory,
    named as 'name.(svg|png|ico)'.
    """
    try:
        return _iconcache[name]
    except KeyError:
        _iconcache[name] = (_findthemeicon(name)
                            or _findscalableicon(name)
                            or _findcustomicon(name)
                            or QIcon())
        return _iconcache[name]


def getoverlaidicon(base, overlay):
    """Generate an overlaid icon"""
    pixmap = base.pixmap(16, 16)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.drawPixmap(0, 0, overlay.pixmap(16, 16))
    del painter
    return QIcon(pixmap)


_pixmapcache = {}

def getpixmap(name, width=16, height=16):
    key = '%s_%sx%s' % (name, width, height)
    try:
        return _pixmapcache[key]
    except KeyError:
        pixmap = geticon(name).pixmap(width, height)
    _pixmapcache[key] = pixmap
    return pixmap

def getcheckboxpixmap(state, bgcolor, widget):
    pix = QPixmap(16,16)
    painter = QPainter(pix)
    painter.fillRect(0, 0, 16, 16, bgcolor)
    option = QStyleOptionButton()
    style = QApplication.style()
    option.initFrom(widget)
    option.rect = style.subElementRect(style.SE_CheckBoxIndicator, option)
    option.rect.moveTo(1, 1)
    option.state |= state
    style.drawPrimitive(style.PE_IndicatorCheckBox, option, painter)
    return pix


# On machines with a retina display running OSX (i.e. "darwin"), most icons are
# too big because Qt4 does not support retina displays very well.
# To fix that we let users force tortoishg to use smaller icons by setting a
# THG_RETINA environment variable to True (or any value that mercurial parses
# as True.
IS_RETINA = False
if sys.platform == 'darwin':
    IS_RETINA = util.parsebool(os.environ.get('THG_RETINA', '0'))


def _fixIconSizeForRetinaDisplay(s):
    if IS_RETINA and s > 1:
        s /= 2
    return s

def smallIconSize():
    style = QApplication.style()
    s = style.pixelMetric(QStyle.PM_SmallIconSize)
    s = _fixIconSizeForRetinaDisplay(s)
    return QSize(s, s)

def toolBarIconSize():
    if sys.platform == 'darwin':
        # most Mac users will have laptop-sized screens and prefer a smaller
        # toolbar to preserve vertical space.
        style = QCommonStyle()
    else:
        style = QApplication.style()
    s = style.pixelMetric(QStyle.PM_ToolBarIconSize)
    s = _fixIconSizeForRetinaDisplay(s)
    return QSize(s, s)

def listviewRetinaIconSize():
    return QSize(16, 16)

def treeviewRetinaIconSize():
    return QSize(16, 16)

def barRetinaIconSize():
    return QSize(10, 10)

class ThgFont(QObject):
    changed = pyqtSignal(QFont)
    def __init__(self, name):
        QObject.__init__(self)
        self.myfont = QFont()
        self.myfont.fromString(name)
    def font(self):
        return self.myfont
    def setFont(self, f):
        self.myfont = f
        self.changed.emit(f)

_fontdefaults = {
    'fontcomment': 'monospace,10',
    'fontdiff': 'monospace,10',
    'fontlist': 'sans,9',
    'fontlog': 'monospace,10',
    'fontoutputlog': 'sans,8'
}
if sys.platform == 'darwin':
    _fontdefaults['fontoutputlog'] = 'sans,10'
_fontcache = {}

def initfontcache(ui):
    for name in _fontdefaults:
        fname = ui.config('tortoisehg', name, _fontdefaults[name])
        _fontcache[name] = ThgFont(hglib.tounicode(fname))

def getfont(name):
    assert name in _fontdefaults
    return _fontcache[name]

def CommonMsgBox(icon, title, main, text='', buttons=QMessageBox.Ok,
                 labels=[], parent=None, defaultbutton=None):
    msg = QMessageBox(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setStandardButtons(buttons)
    for button_id, label in labels:
        msg.setButtonText(button_id, label)
    if defaultbutton:
        msg.setDefaultButton(defaultbutton)
    msg.setText('<b>%s</b>' % main)
    info = ''
    for line in text.split('\n'):
        info += '<nobr>%s</nobr><br />' % line
    msg.setInformativeText(info)
    return msg.exec_()

def InfoMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Information, *args, **kargs)

def WarningMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Warning, *args, **kargs)

def ErrorMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Critical, *args, **kargs)

def QuestionMsgBox(*args, **kargs):
    btn = QMessageBox.Yes | QMessageBox.No
    res = CommonMsgBox(QMessageBox.Question, buttons=btn, *args, **kargs)
    return res == QMessageBox.Yes

class CustomPrompt(QMessageBox):
    def __init__(self, title, message, parent, choices, default=None,
                 esc=None, files=None):
        QMessageBox.__init__(self, parent)

        self.setWindowTitle(hglib.tounicode(title))
        self.setText(hglib.tounicode(message))
        if files:
            self.setDetailedText(hglib.tounicode('\n'.join(files)))
        self.hotkeys = {}
        for i, s in enumerate(choices):
            btn = self.addButton(s, QMessageBox.AcceptRole)
            try:
                char = s[s.index('&')+1].lower()
                self.hotkeys[char] = btn
            except (ValueError, IndexError):
                pass
            if default == i:
                self.setDefaultButton(btn)
            if esc == i:
                self.setEscapeButton(btn)

    def run(self):
        return self.exec_()

    def keyPressEvent(self, event):
        for k, btn in self.hotkeys.iteritems():
            if event.text() == k:
                btn.clicked.emit(False)
        super(CustomPrompt, self).keyPressEvent(event)

class ChoicePrompt(QDialog):
    def __init__(self, title, message, parent, choices, default=None,
                 esc=None, files=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(hglib.tounicode(title))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.box = QHBoxLayout()
        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(8)

        self.message_lbl = QLabel()
        self.message_lbl.setText(message)
        self.vbox.addWidget(self.message_lbl)

        self.choice_combo = combo = QComboBox()
        self.choices = choices
        combo.addItems([hglib.tounicode(item) for item in choices])
        if default:
            try:
                combo.setCurrentIndex(choices.index(default))
            except:
                # Ignore a missing default value
                pass
        self.vbox.addWidget(combo)
        self.box.addLayout(self.vbox)
        vbox = QVBoxLayout()
        self.ok = QPushButton('&OK')
        self.ok.clicked.connect(self.accept)
        vbox.addWidget(self.ok)
        self.cancel = QPushButton('&Cancel')
        self.cancel.clicked.connect(self.reject)
        vbox.addWidget(self.cancel)
        vbox.addStretch()
        self.box.addLayout(vbox)
        self.setLayout(self.box)

    def run(self):
        if self.exec_():
            return self.choices[self.choice_combo.currentIndex()]
        return None

def allowCaseChangingInput(combo):
    """Allow case-changing input of known combobox item

    QComboBox performs case-insensitive inline completion by default. It's
    all right, but sadly it implies case-insensitive check for duplicates,
    i.e. you can no longer enter "Foo" if the combobox contains "foo".

    For details, read QComboBoxPrivate::_q_editingFinished() and matchFlags()
    of src/gui/widgets/qcombobox.cpp.
    """
    assert isinstance(combo, QComboBox) and combo.isEditable()
    combo.completer().setCaseSensitivity(Qt.CaseSensitive)

class BadCompletionBlocker(QObject):
    """Disable unexpected inline completion by enter key if selectAll()-ed

    If the selection state looks in the middle of the completion, QComboBox
    replaces the edit text by the current completion on enter key pressed.
    This is wrong in the following scenario:

    >>> combo = QComboBox(editable=True)
    >>> combo.addItem('history value')
    >>> combo.setEditText('initial value')
    >>> combo.lineEdit().selectAll()
    >>> QApplication.sendEvent(
    ...     combo, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier))
    True
    >>> str(combo.currentText())
    'history value'

    In this example, QLineControl picks the first item in the combo box
    because the completion prefix has not been set.

    BadCompletionBlocker is intended to work around this problem.

    >>> combo.installEventFilter(BadCompletionBlocker(combo))
    >>> combo.setEditText('initial value')
    >>> combo.lineEdit().selectAll()
    >>> QApplication.sendEvent(
    ...     combo, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier))
    True
    >>> str(combo.currentText())
    'initial value'

    For details, read QLineControl::processKeyEvent() and complete() of
    src/gui/widgets/qlinecontrol.cpp.
    """

    def __init__(self, parent):
        super(BadCompletionBlocker, self).__init__(parent)
        if not isinstance(parent, QComboBox):
            raise ValueError('invalid object to watch: %r' % parent)

    def eventFilter(self, watched, event):
        if watched is not self.parent():
            return super(BadCompletionBlocker, self).eventFilter(watched, event)
        if (event.type() != QEvent.KeyPress
            or event.key() not in (Qt.Key_Enter, Qt.Key_Return)
            or not watched.isEditable()):
            return False
        # deselect without completion if all text selected
        le = watched.lineEdit()
        if le.selectedText() == le.text():
            le.deselect()
        return False

class ActionPushButton(QPushButton):
    """Button which properties are defined by QAction like QToolButton"""

    def __init__(self, action, parent=None):
        super(ActionPushButton, self).__init__(parent)
        self.setAutoDefault(False)  # action won't be used as dialog default
        self._defaultAction = action
        self.addAction(action)
        self.clicked.connect(action.trigger)
        self._copyActionProps()

    def actionEvent(self, event):
        if (event.type() == QEvent.ActionChanged
            and event.action() is self._defaultAction):
            self._copyActionProps()
        super(ActionPushButton, self).actionEvent(event)

    def _copyActionProps(self):
        action = self._defaultAction
        self.setEnabled(action.isEnabled())
        self.setText(action.text())
        self.setToolTip(action.toolTip())

class PMButton(QPushButton):
    """Toggle button with plus/minus icon images"""

    def __init__(self, expanded=True, parent=None):
        QPushButton.__init__(self, parent)

        size = QSize(11, 11)
        self.setIconSize(size)
        self.setMaximumSize(size)
        self.setFlat(True)
        self.setAutoDefault(False)

        self.plus = QIcon(iconpath('expander-open.png'))
        self.minus = QIcon(iconpath('expander-close.png'))
        icon = expanded and self.minus or self.plus
        self.setIcon(icon)

        self.clicked.connect(self._toggle_icon)

    @pyqtSlot()
    def _toggle_icon(self):
        icon = self.is_expanded() and self.plus or self.minus
        self.setIcon(icon)

    def set_expanded(self, state=True):
        icon = state and self.minus or self.plus
        self.setIcon(icon)

    def set_collapsed(self, state=True):
        icon = state and self.plus or self.minus
        self.setIcon(icon)

    def is_expanded(self):
        return self.icon().serialNumber() == self.minus.serialNumber()

    def is_collapsed(self):
        return not self.is_expanded()

class ClickableLabel(QLabel):

    clicked = pyqtSignal()

    def __init__(self, label, parent=None):
        QLabel.__init__(self, parent)

        self.setText(label)

    def mouseReleaseEvent(self, event):
        self.clicked.emit()

class ExpanderLabel(QWidget):

    expanded = pyqtSignal(bool)

    def __init__(self, label, expanded=True, stretch=True, parent=None):
        QWidget.__init__(self, parent)

        box = QHBoxLayout()
        box.setSpacing(4)
        box.setContentsMargins(*(0,)*4)
        self.button = PMButton(expanded, self)
        self.button.clicked.connect(self.pm_clicked)
        box.addWidget(self.button)
        self.label = ClickableLabel(label, self)
        self.label.clicked.connect(self.button.click)
        box.addWidget(self.label)
        if not stretch:
            box.addStretch(0)

        self.setLayout(box)

    def pm_clicked(self):
        self.expanded.emit(self.button.is_expanded())

    def set_expanded(self, state=True):
        if not self.button.is_expanded() == state:
            self.button.set_expanded(state)
            self.expanded.emit(state)

    def is_expanded(self):
        return self.button.is_expanded()

class StatusLabel(QWidget):

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        # same policy as status bar of QMainWindow
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        box = QHBoxLayout()
        box.setContentsMargins(*(0,)*4)
        self.status_icon = QLabel()
        self.status_icon.setMaximumSize(16, 16)
        self.status_icon.setAlignment(Qt.AlignCenter)
        box.addWidget(self.status_icon)
        self.status_text = QLabel()
        self.status_text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        box.addWidget(self.status_text)
        box.addStretch(0)

        self.setLayout(box)

    def set_status(self, text, icon=None):
        self.set_text(text)
        self.set_icon(icon)

    def clear_status(self):
        self.clear_text()
        self.clear_icon()

    def set_text(self, text=''):
        if text is None:
            text = ''
        self.status_text.setText(text)

    def clear_text(self):
        self.set_text()

    def set_icon(self, icon=None):
        if icon is None:
            self.clear_icon()
        else:
            if isinstance(icon, bool):
                icon = geticon(icon and 'thg-success' or 'thg-error')
            elif isinstance(icon, basestring):
                icon = geticon(icon)
            elif not isinstance(icon, QIcon):
                raise TypeError, '%s: bool, str or QIcon' % type(icon)
            self.status_icon.setVisible(True)
            self.status_icon.setPixmap(icon.pixmap(16, 16))

    def clear_icon(self):
        self.status_icon.setHidden(True)

class LabeledSeparator(QWidget):

    def __init__(self, label=None, parent=None):
        QWidget.__init__(self, parent)

        box = QHBoxLayout()
        box.setContentsMargins(*(0,)*4)

        if label:
            if isinstance(label, basestring):
                label = QLabel(label)
            box.addWidget(label)

        sep = QFrame()
        sep.setFrameShadow(QFrame.Sunken)
        sep.setFrameShape(QFrame.HLine)
        box.addWidget(sep, 1, Qt.AlignVCenter)

        self.setLayout(box)

class WidgetGroups(object):
    """ Support for bulk-updating properties of Qt widgets """

    def __init__(self):
        object.__init__(self)

        self.clear(all=True)

    ### Public Methods ###

    def add(self, widget, group='default'):
        if group not in self.groups:
            self.groups[group] = []
        widgets = self.groups[group]
        if widget not in widgets:
            widgets.append(widget)

    def remove(self, widget, group='default'):
        if group not in self.groups:
            return
        widgets = self.groups[group]
        if widget in widgets:
            widgets.remove(widget)

    def clear(self, group='default', all=True):
        if all:
            self.groups = {}
        else:
            del self.groups[group]

    def set_prop(self, prop, value, group='default', cond=None):
        if group not in self.groups:
            return
        widgets = self.groups[group]
        if callable(cond):
            widgets = [w for w in widgets if cond(w)]
        for widget in widgets:
            getattr(widget, prop)(value)

    def set_visible(self, *args, **kargs):
        self.set_prop('setVisible', *args, **kargs)

    def set_enable(self, *args, **kargs):
        self.set_prop('setEnabled', *args, **kargs)

class DialogKeeper(QObject):
    """Manage non-blocking dialogs identified by creation parameters

    Example "open single dialog per type":

    >>> mainwin = QWidget()
    >>> dialogs = DialogKeeper(lambda self, cls: cls(self), parent=mainwin)
    >>> dlg1 = dialogs.open(QDialog)
    >>> dlg1.parent() is mainwin
    True
    >>> dlg2 = dialogs.open(QDialog)
    >>> dlg1 is dlg2
    True
    >>> dialogs.count()
    1

    closed dialog will be deleted:

    >>> def processDeferredDeletion():
    ...     loop = QEventLoop()
    ...     QTimer.singleShot(0, loop.quit)
    ...     loop.exec_()

    >>> dlg1.reject()
    >>> processDeferredDeletion()
    >>> dialogs.count()
    0

    and recreates as necessary:

    >>> dlg3 = dialogs.open(QDialog)
    >>> dlg1 is dlg3
    False

    creates new dialog of the same type:

    >>> dlg4 = dialogs.openNew(QDialog)
    >>> dlg3 is dlg4
    False
    >>> dialogs.count()
    2

    and the last dialog is preferred:

    >>> dialogs.open(QDialog) is dlg4
    True
    >>> dlg4.reject()
    >>> processDeferredDeletion()
    >>> dialogs.count()
    1
    >>> dialogs.open(QDialog) is dlg3
    True

    The following example is not recommended because it creates reference
    cycles and makes hard to garbage-collect::

        self._dialogs = DialogKeeper(self._createDialog)
        self._dialogs = DialogKeeper(lambda *args: Foo(self))
    """

    def __init__(self, createdlg, genkey=None, parent=None):
        super(DialogKeeper, self).__init__(parent)
        self._createdlg = createdlg
        self._genkey = genkey or DialogKeeper._defaultgenkey
        self._keytodlgs = {}  # key: [dlg, ...]

    def open(self, *args, **kwargs):
        """Create new dialog or reactivate existing dialog"""
        dlg = self._preparedlg(self._genkey(self.parent(), *args, **kwargs),
                               args, kwargs)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def openNew(self, *args, **kwargs):
        """Create new dialog even if there exists the specified one"""
        dlg = self._populatedlg(self._genkey(self.parent(), *args, **kwargs),
                                args, kwargs)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _preparedlg(self, key, args, kwargs):
        if key in self._keytodlgs:
            assert len(self._keytodlgs[key]) > 0
            return self._keytodlgs[key][-1]  # prefer latest
        else:
            return self._populatedlg(key, args, kwargs)

    def _populatedlg(self, key, args, kwargs):
        dlg = self._createdlg(self.parent(), *args, **kwargs)
        if key not in self._keytodlgs:
            self._keytodlgs[key] = []
        self._keytodlgs[key].append(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(self._cleanupdlgs)
        return dlg

    # "destroyed" is emitted soon after Python wrapper is deleted
    @pyqtSlot()
    def _cleanupdlgs(self):
        for key, dialogs in self._keytodlgs.items():
            livedialogs = [dlg for dlg in dialogs if not sip.isdeleted(dlg)]
            if livedialogs:
                self._keytodlgs[key] = livedialogs
            else:
                del self._keytodlgs[key]

    def count(self):
        return sum(len(dlgs) for dlgs in self._keytodlgs.itervalues())

    @staticmethod
    def _defaultgenkey(_parent, *args, **_kwargs):
        return args

class TaskWidget(object):
    def canswitch(self):
        """Return True if the widget allows to switch away from it"""
        return True

    def canExit(self):
        return True

    def reload(self):
        pass

class DemandWidget(QWidget):
    'Create a widget the first time it is shown'

    def __init__(self, createfuncname, createinst, parent=None):
        super(DemandWidget, self).__init__(parent)
        # We store a reference to the create function name to avoid having a
        # hard reference to the bound function, which prevents it being
        # disposed. Weak references to bound functions don't work.
        self._createfuncname = createfuncname
        self._createinst = weakref.ref(createinst)
        self._widget = None
        vbox = QVBoxLayout()
        vbox.setContentsMargins(*(0,)*4)
        self.setLayout(vbox)

    def showEvent(self, event):
        """create the widget if necessary"""
        self.get()
        super(DemandWidget, self).showEvent(event)

    def forward(self, funcname, *args, **opts):
        if self._widget:
            return getattr(self._widget, funcname)(*args, **opts)
        return None

    def get(self):
        """Returns the stored widget"""
        if self._widget is None:
            func = getattr(self._createinst(), self._createfuncname, None)
            self._widget = func()
            self.layout().addWidget(self._widget)
        return self._widget

    def canswitch(self):
        """Return True if the widget allows to switch away from it"""
        if self._widget is None:
            return True
        return self._widget.canswitch()

    def canExit(self):
        if self._widget is None:
            return True
        return self._widget.canExit()

    def __getattr__(self, name):
        return getattr(self._widget, name)

class Spacer(QWidget):
    """Spacer to separate controls in a toolbar"""

    def __init__(self, width, height, parent=None):
        QWidget.__init__(self, parent)
        self.width = width
        self.height = height

    def sizeHint(self):
        return QSize(self.width, self.height)

def _configuredusername(ui):
    # need to check the existence before calling ui.username(); otherwise it
    # may fall back to the system default.
    if (not os.environ.get('HGUSER')
        and not ui.config('ui', ['username', 'user'])
        and not os.environ.get('EMAIL')):
        return None
    try:
        if ui.configbool('ui', 'askusername'):
            ui.setconfig('ui', 'askusername', False)
        return ui.username()
    except error.Abort:
        return None

def getCurrentUsername(widget, repo, opts=None):
    if opts:
        # 1. Override has highest priority
        user = opts.get('user')
        if user:
            return user

    # 2. Read from repository
    user = _configuredusername(repo.ui)
    if user:
        return user

    # 3. Get a username from the user
    QMessageBox.information(widget, _('Please enter a username'),
                _('You must identify yourself to Mercurial'),
                QMessageBox.Ok)
    from tortoisehg.hgqt.settings import SettingsDialog
    dlg = SettingsDialog(False, focus='ui.username')
    dlg.exec_()
    repo.invalidateui()
    return _configuredusername(repo.ui)

class _EncodingSafeInputDialog(QInputDialog):
    def accept(self):
        try:
            hglib.fromunicode(self.textValue())
            return super(_EncodingSafeInputDialog, self).accept()
        except UnicodeEncodeError:
            WarningMsgBox(_('Text Translation Failure'),
                          _('Unable to translate input to local encoding.'),
                          parent=self)

def getTextInput(parent, title, label, mode=QLineEdit.Normal, text='',
                 flags=Qt.WindowFlags()):
    flags |= (Qt.CustomizeWindowHint | Qt.WindowTitleHint
              | Qt.WindowCloseButtonHint)
    dlg = _EncodingSafeInputDialog(parent, flags)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    dlg.setTextEchoMode(mode)

    r = dlg.exec_()
    dlg.setParent(None)  # so that garbage collected
    return r and dlg.textValue() or '', bool(r)

def keysequence(o):
    """Create QKeySequence from string or QKeySequence"""
    if isinstance(o, (QKeySequence, QKeySequence.StandardKey)):
        return o
    try:
        return getattr(QKeySequence, str(o))  # standard key
    except AttributeError:
        return QKeySequence(o)

def modifiedkeysequence(o, modifier):
    """Create QKeySequence of modifier key prepended"""
    origseq = QKeySequence(keysequence(o))
    return QKeySequence('%s+%s' % (modifier, origseq.toString()))

def newshortcutsforstdkey(key, *args, **kwargs):
    """Create [QShortcut,...] for all key bindings of the given StandardKey"""
    return [QShortcut(keyseq, *args, **kwargs)
            for keyseq in QKeySequence.keyBindings(key)]

class PaletteSwitcher(object):
    """
    Class that can be used to enable a predefined, alterantive background color
    for a widget

    This is normally used to change the color of widgets when they display some
    "filtered" content which is a subset of the actual widget contents.

    The alternative background color is fixed, and depends on the original
    background color (dark and light backgrounds use a different alternative
    color).

    The alterenative color cannot be changed because the idea is to set a
    consistent "filter" style for all widgets.

    An instance of this class must be added as a property of the widget whose
    background we want to change. The constructor takes the "target widget" as
    its only parameter.

    In order to enable or disable the background change, simply call the
    enablefilterpalette() method.
    """
    def __init__(self, targetwidget):
        self._targetwref = weakref.ref(targetwidget)  # avoid circular ref
        self._defaultpalette = targetwidget.palette()
        if not isDarkTheme(self._defaultpalette):
            filterbgcolor = QColor('#FFFFB7')
        else:
            filterbgcolor = QColor('darkgrey')
        self._filterpalette = QPalette()
        self._filterpalette.setColor(QPalette.Base, filterbgcolor)

    def enablefilterpalette(self, enabled=False):
        targetwidget = self._targetwref()
        if not targetwidget:
            return
        if enabled:
            pl = self._filterpalette
        else:
            pl = self._defaultpalette
        targetwidget.setPalette(pl)
