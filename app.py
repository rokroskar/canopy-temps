"""Panel app: canopy air temperatures on north- vs south-facing subalpine forest slopes.

Run locally:   panel serve app.py --show
On Renku:      see Procfile
"""

from __future__ import annotations

import holoviews as hv
import hvplot.pandas  # noqa: F401  (registers .hvplot)
import pandas as pd
import panel as pn

from canopy_temps.analysis import (
    MONTHS,
    SEASONS,
    diurnal_cycle,
    load,
    monthly_peak_contrast,
    season_frame,
    season_year,
)

pn.extension(sizing_mode="stretch_width", design="fast")
hv.extension("bokeh")

# --------------------------------------------------------------------------------------
# Theme & palette (validated: north=slot 1 blue, south=slot 2 orange; light and dark)
# --------------------------------------------------------------------------------------
DARK = pn.config.theme == "dark"
C = {
    "north": "#3987e5" if DARK else "#2a78d6",
    "south": "#d95926" if DARK else "#eb6834",
    "ink": "#f0efec" if DARK else "#0b0b0b",
    "muted": "#c3c2b7" if DARK else "#52514e",
    "grid": "#383835" if DARK else "#e4e3df",
    "snow": "#6b6b66" if DARK else "#b9b8b2",
    "filled": "#8d8c86" if DARK else "#8d8c86",
}
LABEL = {"north": "North-facing forest", "south": "South-facing forest"}

STYLE = dict(
    show_grid=True,
    gridstyle={"grid_line_color": C["grid"], "grid_line_width": 1},
    fontscale=1.05,
    toolbar="above",
)

# Read straight from the EnviDat zip on the data connector; built once per process
# (Procfile uses --warm so this happens at server start, not on the first visit).
TEMPS, SNOW = load()


# --------------------------------------------------------------------------------------
# View 1: the mean day, month by month (interactive version of the paper's figure 2)
# --------------------------------------------------------------------------------------
def _hours_fmt(h: float) -> str:
    return f"{int(h):02d}:{int(round(h % 1 * 60)):02d}"


def mean_day_view(season: str):
    df = season_frame(TEMPS, season)
    cycle = diurnal_cycle(df, season_year(season))
    long = cycle.melt(id_vars=["month", "hour"], value_vars=["north", "south"], var_name="slope", value_name="T")
    long["Slope"] = long["slope"].map(LABEL)
    long["Time"] = long["hour"].map(_hours_fmt)
    ymin, ymax = long["T"].min() - 1, long["T"].max() + 1

    panels = []
    for m, name in MONTHS.items():
        sub = long[long["month"] == m]
        overlay = hv.HLine(0).opts(color=C["muted"], line_width=1)
        for slope in ("north", "south"):
            s = sub[sub["slope"] == slope]
            overlay *= s.hvplot.line(responsive=True, 
                x="hour",
                y="T",
                label=LABEL[slope],
                color=C[slope],
                line_width=2,
                hover_cols=["Time", "Slope"],
                hover_tooltips=[("", "@Slope"), ("Time", "@Time"), ("Mean T", "@T{0.0} °C")],
            )
        panels.append(
            overlay.opts(
                title=name,
                xlabel="Time of day (h)",
                ylabel="Mean air temperature (°C)" if m == 1 else "",
                xticks=[0, 6, 12, 18, 24],
                xlim=(0, 24),
                ylim=(ymin, ymax),
                height=300,
                responsive=True,
                legend_position="top_left",
                show_legend=(m == 1),
                hover_mode="vline",
                **STYLE,
            )
        )
    layout = hv.Layout(panels).cols(4).opts(shared_axes=True)

    peaks = monthly_peak_contrast(cycle)
    tiles = [
        pn.indicators.Number(
            name=f"{MONTHS[int(r.month)]} · south warmer by",
            value=round(float(r.diff), 1),
            format="{value} K",
            font_size="28pt",
            title_size="11pt",
            default_color=C["ink"],
        )
        for r in peaks.itertuples()
    ]
    peak_month = peaks.loc[peaks["diff"].idxmax()]
    headline = (
        f"### In {SEASONS[season]}, the average {MONTHS[int(peak_month.month)]} afternoon was "
        f"**{peak_month['diff']:.1f} K warmer** in the south-facing forest "
        f"(peak around {_hours_fmt(peak_month.hour)})."
    )
    return pn.Column(
        pn.pane.Markdown(headline),
        pn.pane.Markdown(
            "Each panel averages all days of the month into one *typical day*. "
            "At night both slopes are equally cold; the gap opens when the sun reaches the "
            "south-facing canopy. Largest difference between the two mean days per month:",
            styles={"color": C["muted"]},
        ),
        pn.Row(*tiles),
        pn.pane.HoloViews(layout, sizing_mode="stretch_width"),
    )


# --------------------------------------------------------------------------------------
# View 2: the whole season, with snow cover and data provenance
# --------------------------------------------------------------------------------------
RESOLUTION = {"Daily mean": "1D", "Hourly mean": "1h", "15 minutes": None}


def _spans(mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Contiguous True runs of a boolean time series as (start, end) pairs."""
    if not mask.any():
        return []
    grp = (mask != mask.shift()).cumsum()
    return [(g.index[0], g.index[-1]) for _, g in mask.groupby(grp) if g.iloc[0]]


def timeline_view(season: str, resolution: str, date_range):
    df = season_frame(TEMPS, season)
    rule = RESOLUTION[resolution]
    num = df[["north", "south", "diff"]]
    if rule:
        num = num.resample(rule).mean()
    start, end = (pd.Timestamp(d) for d in date_range)
    num = num.loc[start : end + pd.Timedelta("1D")]

    x_range = (start, end + pd.Timedelta("1D"))
    shared = dict(responsive=True, xlim=x_range, **STYLE)

    temps = hv.HLine(0).opts(color=C["muted"], line_width=1)
    for slope in ("north", "south"):
        temps *= num[[slope]].hvplot.line(responsive=True, 
            y=slope,
            label=LABEL[slope],
            color=C[slope],
            line_width=2 if rule == "1D" else 1.2,
            hover_tooltips=[("", LABEL[slope]), ("Time", "@time{%Y-%m-%d %H:%M}"), ("T", f"@{slope}{{0.0}} °C")],
            hover_formatters={"@time": "datetime"},
        )
    temps = temps.opts(
        ylabel="Air temperature (°C)", xlabel="", height=330, legend_position="top_left", hover_mode="vline", **shared
    )

    d = num["diff"]
    pos = d.clip(lower=0).rename("pos").to_frame()
    neg = d.clip(upper=0).rename("neg").to_frame()
    diff = (
        hv.HLine(0).opts(color=C["muted"], line_width=1)
        * pos.hvplot.area(responsive=True, y="pos", color=C["south"], alpha=0.55, line_width=0, label="South warmer")
        * neg.hvplot.area(responsive=True, y="neg", color=C["north"], alpha=0.55, line_width=0, label="North warmer")
        * d.to_frame().hvplot.line(responsive=True, 
            y="diff",
            color=C["ink"],
            line_width=0.8,
            alpha=0.6,
            hover_tooltips=[("Time", "@time{%Y-%m-%d %H:%M}"), ("South − north", "@diff{+0.0} K")],
            hover_formatters={"@time": "datetime"},
        )
    ).opts(ylabel="South − north (K)", xlabel="", height=200, legend_position="top_left", **shared)

    # Context strip: snow cover below the canopy per slope, plus HOBO gap-filled data.
    rows = [("Snow cover · north", "north"), ("Snow cover · south", "south")]
    rects, lane_names = [], []
    for i, (name, slope) in enumerate(rows):
        lane_names.append((i, name))
        sc = SNOW[(SNOW["season"] == season) & (SNOW["slope"] == slope)]
        for r in sc.itertuples():
            rects.append((r.start, i - 0.35, r.end, i + 0.35, name))
    filled = df["south_src"].eq("hobo_1m") | df["north_src"].eq("hobo_1m")
    if filled.any():
        i = len(lane_names)
        lane_names.append((i, "Gap-filled (HOBO 1 m)"))
        for a, b in _spans(filled):
            rects.append((a, i - 0.35, b, i + 0.35, "Gap-filled (HOBO 1 m)"))
    strip = hv.Rectangles(rects, vdims="what").opts(
        color=C["snow"],
        line_width=0,
        yticks=lane_names,
        invert_yaxis=True,
        ylim=(-0.6, len(lane_names) - 0.4),
        height=60 + 28 * len(lane_names),
        xlabel="",
        ylabel="",
        tools=["hover"],
        hover_tooltips=[("", "@what")],
        **shared,
    )

    layout = (temps + diff + strip).cols(1).opts(shared_axes=True)
    return pn.pane.HoloViews(layout, linked_axes=True, sizing_mode="stretch_width")


# --------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------
season_w = pn.widgets.RadioButtonGroup(
    name="Season", options={v: k for k, v in SEASONS.items()}, value="fluela_2023",
    button_type="primary", button_style="outline",
)
resolution_w = pn.widgets.RadioButtonGroup(
    name="Resolution", options=list(RESOLUTION), value="Hourly mean", button_type="primary", button_style="outline"
)
range_w = pn.widgets.DateRangeSlider(
    name="Period", step=1, start=TEMPS["time"].min().date(), end=TEMPS["time"].max().date()
)


@pn.depends(season_w, watch=True)
def _update_range(season):
    t = TEMPS.loc[TEMPS["season"] == season, "time"]
    y = season_year(season)
    range_w.param.update(
        start=t.min().date(),
        end=t.max().date(),
        value=(pd.Timestamp(f"{y}-01-01").date(), pd.Timestamp(f"{y}-04-30").date()),
    )


_update_range(season_w.value)


def _provenance(season):
    if season != "monstein_2025":
        return None
    return pn.pane.Alert(
        "**Monstein 2025:** the ventilated sensor on the south slope failed on 12 March 2025. "
        "As in the paper, gaps in the ventilated record are filled with a passive HOBO "
        "logger at 1 m on the same slope. The second tab marks these periods in its bottom strip.",
        alert_type="secondary",
    )


tabs = pn.Tabs(
    ("A typical day", pn.bind(mean_day_view, season_w)),
    (
        "Through the season",
        pn.Column(
            pn.Row(
                pn.Column(pn.pane.Markdown("**Resolution**", margin=(0, 10)), resolution_w, width=340, sizing_mode="fixed"),
                pn.Column(pn.Spacer(height=12), range_w),
            ),
            pn.bind(timeline_view, season_w, resolution_w, range_w),
        ),
    ),
    dynamic=True,
)

ABOUT = """
Two weather stations stood in the forest **on opposite sides of an Alpine valley**,
one facing north and one facing south, measuring air temperature 2.5 m above the
ground with ventilated sensors. Three winters were covered: Flüela (2023) and
Monstein (2024, 2025), both near Davos, Switzerland.

**What to look for:** at night the two slopes are just as cold. During the day the
south-facing canopy gets sun and becomes warmer, by up to a few kelvin, and more so
as spring advances.

---

**Data:** Haagmans, V., Mazzotti, G., Jonas, T. (2025). *Canopy air temperatures in
subalpine forests during three snow seasons.* EnviDat.
[doi:10.16904/envidat.722](https://doi.org/10.16904/envidat.722) · CC-BY-4.0

Processed data are averaged to 15 min. North slope at Monstein is corrected
for elevation (−0.114 K), following the authors' scripts. Times are as recorded by the
loggers.
"""

template = pn.template.FastListTemplate(
    title="Sunny side up? Forest air temperatures on opposite slopes",
    sidebar=[
        pn.pane.Markdown("**Season**"),
        season_w,
        pn.bind(_provenance, season_w),
        pn.pane.Markdown(ABOUT),
    ],
    main=[tabs],
    accent=C["north"],
    sidebar_width=360,
    theme_toggle=True,
)
template.servable()
