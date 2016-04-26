# gpg.py - TortoiseHg GnuPG support
#
# Copyright 2013 Elson Wei <elson.wei@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.
import os

if os.name == 'nt':
    import _winreg

    def findgpg(ui):
        path = []
        for key in (r"Software\GNU\GnuPG", r"Software\Wow6432Node\GNU\GnuPG"):
            try:
                hkey = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, key)
                pfx = _winreg.QueryValueEx(hkey, 'Install Directory')[0]
                for dirPath, dirNames, fileNames in os.walk(pfx):
                    for f in fileNames:
                        if f == 'gpg.exe':
                            path.append(os.path.join(dirPath, f))
            except WindowsError:
                pass
            except EnvironmentError:
                pass

        return path

else:
    def findgpg(ui):
        return []
