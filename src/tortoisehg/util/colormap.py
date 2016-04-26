# colormap.py - color scheme for annotation
#
# Copyright (C) 2005 Dan Loda <danloda@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import sys, math

def _days(ctx, now):
    return (now - ctx.date()[0]) / (24 * 60 * 60)

def _rescale(val, step):
    return float(step) * int(val / step)

def _rescaleceil(val, step):
    return float(step) * math.ceil(float(val) / step)

class AnnotateColorSaturation(object):
    def __init__(self, maxhues=None, maxsaturations=None):
        self._maxhues = maxhues
        self._maxsaturations = maxsaturations

    def hue(self, angle):
        return tuple([self.v(angle, r) for r in (0, 120, 240)])

    @staticmethod
    def ang(angle, rotation):
        angle += rotation
        angle = angle % 360
        if angle > 180:
            angle = 180 - (angle - 180)
        return abs(angle)

    def v(self, angle, rotation):
        ang = self.ang(angle, rotation)
        if ang < 60:
            return 1
        elif ang > 120:
            return 0
        else:
            return 1 - ((ang - 60) / 60)

    def saturate_v(self, saturation, hv):
        return int(255 - (saturation/3*(1-hv)))

    def committer_angle(self, committer):
        angle = float(abs(hash(committer))) / sys.maxint * 360.0
        if self._maxhues is None:
            return angle
        return _rescale(angle, 360.0 / self._maxhues)

    def get_color(self, ctx, now):
        days = max(_days(ctx, now), 0.0)
        saturation = 255/((days/50) + 1)
        if self._maxsaturations:
            saturation = _rescaleceil(saturation, 255. / self._maxsaturations)
        hue = self.hue(self.committer_angle(ctx.user()))
        color = tuple([self.saturate_v(saturation, h) for h in hue])
        return "#%x%x%x" % color

def makeannotatepalette(fctxs, now, maxcolors, maxhues=None,
                        maxsaturations=None, mindate=None):
    """Assign limited number of colors for annotation

    :fctxs: list of filecontexts by lines
    :now: latest time which will have most significat color
    :maxcolors: max number of colors
    :maxhues: max number of committer angles (hues)
    :maxsaturations: max number of saturations by age
    :mindate: reassign palette until it includes fctx of mindate
              (requires maxsaturations)

    This returns dict of {color: fctxs, ...}.
    """
    if mindate is not None and maxsaturations is None:
        raise ValueError('mindate must be specified with maxsaturations')

    sortedfctxs = list(sorted(set(fctxs), key=lambda fctx: -fctx.date()[0]))
    return _makeannotatepalette(sortedfctxs, now, maxcolors, maxhues,
                                maxsaturations, mindate)[0]

def _makeannotatepalette(sortedfctxs, now, maxcolors, maxhues,
                         maxsaturations, mindate):
    cm = AnnotateColorSaturation(maxhues=maxhues,
                                 maxsaturations=maxsaturations)
    palette = {}

    def reassignifneeded(fctx):
        # fctx is the latest fctx which is NOT included in the palette
        if mindate is None or fctx.date()[0] < mindate or maxsaturations <= 1:
            return palette, cm
        return _makeannotatepalette(sortedfctxs, now, maxcolors, maxhues,
                                    maxsaturations - 1, mindate)

    # assign from the latest for maximum discrimination
    for fctx in sortedfctxs:
        color = cm.get_color(fctx, now)
        if color not in palette:
            if len(palette) >= maxcolors:
                return reassignifneeded(fctx)
            palette[color] = []
        palette[color].append(fctx)

    return palette, cm  # return cm for debbugging
