"""Brand colours, ordinal palettes, and matplotlib theme for MwM reporting."""

import matplotlib as mpl


# ========================================================================
# COLOURS
# ========================================================================

class Colors:
    red           = '#da291c'
    medium_red    = '#ed7b73'
    light_red     = '#f9d3d0'
    purple        = '#ae90c3'
    medium_purple = '#cebcdb'
    light_purple  = '#efe9f3'
    yellow        = '#fecf28'
    medium_yellow = '#ffeca9'
    light_yellow  = '#fff5d4'
    blue          = '#00B2A9'
    medium_blue   = '#66CCC6'
    light_blue    = '#CCEEEC'
    green         = '#45b283'
    medium_green  = '#8dd3b5'
    light_green   = '#d9f0e6'
    grey_1000     = '#1F1F1F'
    grey_900      = '#2B2B2B'
    grey_700      = '#666666'
    grey_500      = '#9E9E9E'
    grey_300      = '#D9D9D9'
    grey_200      = '#EEEEEE'
    grey_100      = '#F5F5F5'


# ========================================================================
# ORDINAL PALETTES
# ========================================================================

ordinal_3 = [Colors.red, Colors.grey_300, Colors.green]
ordinal_4 = [Colors.red, Colors.medium_red, Colors.medium_green, Colors.green]
ordinal_5 = [Colors.red, Colors.medium_red, Colors.grey_300, Colors.medium_green, Colors.green]
ordinal_6 = [Colors.red, Colors.medium_red, Colors.light_red, Colors.light_green, Colors.medium_green, Colors.green]
ordinal_7 = [Colors.red, Colors.medium_red, Colors.light_red, Colors.grey_300, Colors.light_green, Colors.medium_green, Colors.green]


def get_ordinal_colors(n):
    """Return the ordinal colour palette for *n* categories (3–7)."""
    palettes = {3: ordinal_3, 4: ordinal_4, 5: ordinal_5, 6: ordinal_6, 7: ordinal_7}
    return palettes.get(n)


# ========================================================================
# MATPLOTLIB THEME
# ========================================================================

def sc_theme():
    """Apply the Save the Children matplotlib rcParams theme."""
    mpl.rcParams['font.family'] = 'sans-serif'
    mpl.rcParams['font.sans-serif'] = ['Segoe UI', 'Arial']
    mpl.rcParams.update({
        "figure.facecolor":   Colors.grey_100,
        "axes.facecolor":     Colors.grey_200,
        "axes.edgecolor":     Colors.grey_500,
        "axes.labelcolor":    Colors.grey_1000,
        "xtick.color":        Colors.grey_1000,
        "ytick.color":        Colors.grey_1000,
        "text.color":         Colors.grey_1000,
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        'ytick.major.size':   0,
        'xtick.major.size':   0,
        'xtick.minor.size':   0,
        'ytick.minor.size':   0,
        'axes.grid':          True,
        'grid.color':         Colors.grey_100,
        'grid.alpha':         1.0,
        'grid.linestyle':     '-',
        'grid.linewidth':     1.5,
        'savefig.bbox':       'tight',
        'savefig.dpi':        300,
        'savefig.pad_inches': 0.3,
        'axes.titlepad':      12,
    })
