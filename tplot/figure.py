from functools import lru_cache, cached_property, partial, wraps
from colorama import init
import numpy as np
from shutil import get_terminal_size
from typing import Optional

from .scales import *
from .utils import *


class Figure:
    """
    Figure used to draw graphs.

    Args:
        xlabel: Label for x axis
        ylabel: Label for y axis
        title: Title for figure
        width: Width of figure. Defaults to the terminal window width, or falls back to 80.
        height: Height of the figure. Defaults to the terminal window height, or falls back to 24.
        legendloc: Location of the legend. Accepted values: "topleft", "topright", "bottomleft", "bottomright".
        xticklabel_length: Length of the tick labels on the x axis. Determines how many x ticks are shown.
    """

    def __init__(self,
                 xlabel: Optional[str] = None,
                 ylabel: Optional[str] = None,
                 title: Optional[str] = None,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 legendloc: str = "topright",
                 xticklabel_length: int = 7):
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.title = title
        self.legendloc = legendloc
        self.xticklabel_length = xticklabel_length
        term_width, term_height = get_terminal_size(fallback=(80, 24))
        term_height -= 1  # room for prompt
        self.width = width if width else term_width
        self.height = height if height else term_height

        # gather stuff to plot before actually drawing it
        self._plots = []
        self._labels = []

    @property
    def x(self):
        return tuple([x for plot in self._plots for x in plot.keywords["x"]])

    @property
    def y(self):
        return tuple([y for plot in self._plots for y in plot.keywords["y"]])

    @cached_property
    def _yscale(self):
        if is_numerical(self.y):
            scale = LinearScale()
        else:
            scale = NominalScale()
        target_min = self._xax_height - bool(self.xlabel) + 1
        target_max = self.height-1 - bool(self.title)
        scale.fit(self.y, target_min, target_max)
        if is_numerical(self.y):
            # refit scale to tick values, since those lay just outside the input data range
            scale.fit(self._ytick_values, target_min, target_max)
        return scale

    @cached_property
    def _xscale(self):
        if is_numerical(self.x):
            scale = LinearScale()
        else:
            scale = NominalScale()
        target_min = self._yax_width
        target_max = self.width - 1
        scale.fit(self.x, target_min, target_max)
        if is_numerical(self.x):
            # refit scale to tick values, since those lay just outside the input data range
            scale.fit(self._xtick_values, target_min, target_max)
        return scale

    @property
    def _xax_height(self):
        return 2 + bool(self.xlabel)

    def _fmt(self, value):
        return f"{value:.2g}"

    @cached_property
    def _yax_width(self):
        """
        Since y-axis tick labels are drawn horizontally, the width of the y axis
        depends on the length of the labels, which themselves depend on the data.
        """
        labels = (self._fmt(value) for value in self._ytick_values)
        width = max([len(label) for label in labels])
        width += 1  # for axis ticks
        width += bool(self.ylabel) * 2  # for y label
        return width

    def _center_draw(self, string, array, fillchar=" "):
        array[:] = list(string.center(len(array), fillchar))

    def _ljust_draw(self, string, array, fillchar=" "):
        array[:] = list(string.ljust(len(array), fillchar))

    def _rjust_draw(self, string, array, fillchar=" "):
        array[:] = list(string.rjust(len(array), fillchar))

    @cached_property
    def _ytick_values(self):
        if is_numerical(self.y):
            return best_ticks(min(self.y), max(self.y), most=self.height // 2)
        else:  # nominal
            return set(self.y)  # note this may not fit depending on the height of the figure

    @cached_property
    def _xtick_values(self):
        if is_numerical(self.x):
            return best_ticks(min(self.x), max(self.x), most=self.width // self.xticklabel_length)
        else:  # nominal
            return set(self.x)  # note this may not fit dependong on the width of the figure

    def _draw_y_axis(self):
        start = round(self._yscale.transform(self._ytick_values[0]))
        end = round(self._yscale.transform(self._ytick_values[-1]))
        self._canvas[-end-1:-start, self._yax_width-1] = "|"
        for value, pos in zip(self._ytick_values, self._yscale.transform(self._ytick_values)):
            pos = round(pos) - 1
            label = self._fmt(value)
            self._canvas[end-pos, self._yax_width-1] = "+"
            self._rjust_draw(label, self._canvas[end-pos, bool(self.ylabel)*2:self._yax_width-1])

        if self.ylabel:
            ylabel = self.ylabel[:end-start]  # make sure it fits
            self._center_draw(ylabel, self._canvas[start:end, 0])

    def _draw_x_axis(self):
        start = round(self._xscale.transform(self._xtick_values[0]))
        end = round(self._xscale.transform(self._xtick_values[-1]))
        self._canvas[-self._xax_height, start:end] = "-"
        before = self.xticklabel_length // 2
        after = self.xticklabel_length - before
        for value, pos in zip(self._xtick_values, self._xscale.transform(self._xtick_values)):
            pos = round(pos)
            label = self._fmt(value)
            self._canvas[-self._xax_height, pos] = "+"
            if pos == start:  # left-adjust first ticklabel
                self._ljust_draw(label[:after], self._canvas[-self._xax_height+1, pos:pos+after])
            elif pos == end:  # right-adjust last ticklabel
                self._rjust_draw(label[:before+1], self._canvas[-self._xax_height+1, pos-before:pos+1])
            else:  # center other ticklabels
                self._center_draw(label[:self.xticklabel_length],
                                  self._canvas[-self._xax_height+1, pos-before:pos+after])

        if self.xlabel:
            xlabel = self.xlabel[:end-start]  # make sure it fits
            self._center_draw(xlabel, self._canvas[-1, start:end])

    def _draw_legend(self):
        labelstrings = [f"{marker} {label}" for marker, label in self._labels]
        width = max([len(labelstring) for labelstring in labelstrings]) + 2
        width = max(width, len("Legend") + 2)
        height = len(labelstrings) + 2

        if self.legendloc.startswith("top"):
            top = -int(self._yscale.transform(max(self.y))) - 1
        elif self.legendloc.startswith("bottom"):
            top = -int(self._yscale.transform(min(self.y))) - height
        if self.legendloc.endswith("right"):
            left = int(self._xscale.transform(max(self.x))) - width + 1
        elif self.legendloc.endswith("left"):
            left = int(self._xscale.transform(min(self.x)))

        self._canvas[top, left:left+width] = list("+" + "Legend".center(width-2, "-") + "+")
        for i, labelstring in enumerate(labelstrings):
            self._canvas[top+i+1, left:left+width] = list("|" + labelstring.ljust(width-2) + "|")
        self._canvas[top+len(labelstrings)+1, left:left+width] = list("+" + "-"*(width-2) + "+")

    def draw(self):
        self._canvas = np.empty((self.height, self.width), dtype="U1")
        self._canvas[:] = " "

        if self.title:
            title = self.title[:self.width]  # make sure it fits
            self._center_draw(title, self._canvas[0, :])

        self._draw_x_axis()
        self._draw_y_axis()

        for plot in self._plots:
            plot()
        if self._labels:
            self._draw_legend()

    def _prep(self, x, y, marker, label):
        assert(len(x) == len(y))
        marker = marker[0]
        if label:
            self._labels.append((marker, label))
        return x, y, marker, label

    def scatter(self, x, y, marker="o", label=None):
        x, y, marker, label = self._prep(x, y, marker, label)

        def draw_scatter(x, y, marker):
            for xi, yi in zip(self._xscale.transform(x), self._yscale.transform(y)):
                self._canvas[-round(yi)-1, round(xi)] = marker
        self._plots.append(partial(draw_scatter, x=x, y=y, marker=marker))

    def line(self, x, y, marker="*", label=None):
        x, y, marker, label = self._prep(x, y, marker, label)

        def draw_line(x, y, marker):
            xs = self._xscale.transform(x)
            ys = self._yscale.transform(y)
            for (x0, x1), (y0, y1) in zip(zip(xs[: -1], xs[1:]), zip(ys[: -1], ys[1:])):
                for x, y in plot_line_segment(round(x0), round(y0), round(x1), round(y1)):
                    self._canvas[-y-1, x] = marker
        self._plots.append(partial(draw_line, x=x, y=y, marker=marker))

    def bar(self, x, y, marker="#", label=None):
        x, y, marker, label = self._prep(x, y, marker, label)

        def draw_bar(x, y, marker):
            bottom = self._yscale.transform(min(y))
            for xi, yi in zip(self._xscale.transform(x), self._yscale.transform(y)):
                self._canvas[-round(yi)-1:-int(bottom), round(xi)] = marker
        self._plots.append(partial(draw_bar, x=x, y=y, marker=marker))

    def hbar(self, x, y, marker="#", label=None):
        x, y, marker, label = self._prep(x, y, marker, label)

        def draw_hbar(x, y, marker):
            start = self._xscale.transform(min(x))
            for xi, yi in zip(self._xscale.transform(x), self._yscale.transform(y)):
                self._canvas[-round(yi)-1, int(start):round(xi)] = marker
        self._plots.append(partial(draw_hbar, x=x, y=y, marker=marker))

    def __repr__(self):
        self.draw()
        return "\n".join(["".join(row) for row in self._canvas.tolist()])

    def show(self):
        print(self)