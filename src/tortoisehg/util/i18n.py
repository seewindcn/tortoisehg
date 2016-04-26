# i18n.py - TortoiseHg internationalization code
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import gettext, os, locale
from tortoisehg.util import paths

_localeenvs = ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG')
def _defaultlanguage():
    if os.name != 'nt' or any(e in os.environ for e in _localeenvs):
        return  # honor posix-style env var

    # On Windows, UI language can be determined by GetUserDefaultUILanguage(),
    # but gettext doesn't take it into account.
    # Note that locale.getdefaultlocale() uses GetLocaleInfo(), which may be
    # different from UI language.
    #
    # For details, please read "User Interface Language Management":
    # http://msdn.microsoft.com/en-us/library/dd374098(v=VS.85).aspx
    try:
        from ctypes import windll  # requires Python>=2.5
        langid = windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale[langid]
    except (ImportError, AttributeError, KeyError):
        pass

def setlanguage(lang=None):
    """Change translation catalog to the specified language"""
    global t, language
    if not lang:
        lang = _defaultlanguage()
    opts = {}
    if lang:
        opts['languages'] = (lang,)
    t = gettext.translation('tortoisehg', paths.get_locale_path(),
                            fallback=True, **opts)
    language = lang or locale.getdefaultlocale(_localeenvs)[0]
setlanguage()

def availablelanguages():
    """List up language code of which message catalog is available"""
    basedir = paths.get_locale_path()
    def mopath(lang):
        return os.path.join(basedir, lang, 'LC_MESSAGES', 'tortoisehg.mo')
    if os.path.exists(basedir): # locale/ is an install option
        langs = [e for e in os.listdir(basedir) if os.path.exists(mopath(e))]
    else:
        langs = []
    langs.append('en')  # means null translation
    return sorted(langs)

def _(message, context=''):
    if context:
        sep = '\004'
        tmsg = t.ugettext(context + sep + message)
        if sep not in tmsg:
            return tmsg
    return t.ugettext(message)

def ngettext(singular, plural, n):
    return t.ungettext(singular, plural, n)

def agettext(message, context=''):
    """Translate message and convert to local encoding
    such as 'ascii' before being returned.

    Only use this if you need to output translated messages
    to command-line interface (ie: Windows Command Prompt).
    """
    try:
        from tortoisehg.util import hglib
        u = _(message, context)
        return hglib.fromunicode(u)
    except (LookupError, UnicodeEncodeError):
        return message

class keepgettext(object):
    def _(self, message, context=''):
        return {'id': message, 'str': _(message, context)}
