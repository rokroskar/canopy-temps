"""Loading the harmonised data (in memory, from the zip) and computations shared by notebook and app."""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pandas as pd

from canopy_temps.prepare import SEASONS, Archive, find_zip, load_native, snow_cover, to_tidy

MONTHS = {1: "January", 2: "February", 3: "March", 4: "April"}


@functools.cache
def load(zip_path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (temperatures, snow_cover): harmonised 15-min series for all seasons.

    Built in memory straight from the EnviDat zip (located with :func:`find_zip` unless
    given). Cached per process, so all app sessions share one copy (~5 s to build).
    """
    ar = Archive(zip_path or find_zip())
    return to_tidy(load_native(ar), "15min"), snow_cover(ar)


def season_year(season: str) -> int:
    """'monstein_2024' -> 2024 (the calendar year holding January-April)."""
    return int(season.rsplit("_", 1)[1])


def season_frame(temps: pd.DataFrame, season: str) -> pd.DataFrame:
    """One season, indexed by time, with the south-minus-north difference."""
    df = temps[temps["season"] == season].set_index("time").drop(columns="season")
    df["diff"] = df["south"] - df["north"]
    return df


def diurnal_cycle(df: pd.DataFrame, year: int, months=MONTHS) -> pd.DataFrame:
    """Mean diurnal cycle per month, as in figure 2 of Haagmans et al.

    ``df`` has a DatetimeIndex and ``north``/``south`` columns (any regular resolution).
    Like ``figure_2.m``, a timestamp is dropped on both slopes if either one is missing,
    so the two curves always average the same moments.
    """
    d = df.loc[df.index.year == year, ["north", "south"]]
    d = d[d.index.month.isin(list(months))]
    d = d.where(d.notna().all(axis=1))  # pairwise NaN mask
    tod = d.index.hour + d.index.minute / 60
    out = d.groupby([d.index.month.rename("month"), np.asarray(tod)]).mean()
    out.index = out.index.set_names(["month", "hour"])
    out = out.reset_index()
    out["diff"] = out["south"] - out["north"]
    return out


def monthly_peak_contrast(cycle: pd.DataFrame) -> pd.DataFrame:
    """Largest south-minus-north difference in each month's mean day, and when it occurs."""
    idx = cycle.groupby("month")["diff"].idxmax()
    return cycle.loc[idx, ["month", "hour", "diff"]].reset_index(drop=True)


__all__ = ["SEASONS", "MONTHS", "load", "season_year", "season_frame", "diurnal_cycle", "monthly_peak_contrast"]
