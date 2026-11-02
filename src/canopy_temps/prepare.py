"""Convert the EnviDat archive (doi:10.16904/envidat.722) into small, tidy Parquet files.

The authors' processed data are MATLAB ``timetable`` objects, which ``scipy`` cannot read;
we use `mat-io <https://pypi.org/project/mat-io/>`_ instead. The harmonisation below is a
faithful port of ``scripts_figures/figure_2.m`` from the archive:

* Flüela 2023: north/south ventilated stations used as-is (1-min).
* Monstein 2024: the north sensor was replaced in March; the series switches from sensor 1
  to sensor 2 at MATLAB row 531169. Only full-minute samples are kept. A lapse-rate
  correction of -0.6 K/100 m is added to the north station (it is 19 m lower).
* Monstein 2025: averaged to 15 min; the south station is discarded from MATLAB row 70434
  on (12 March, "non-sensible data"); gaps are filled with the passive HOBO logger at
  1 m on the same profile; lapse-rate correction on the north station.

Everything is read directly from the zip; nothing is extracted or written to the repository.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_ZIP = Path(
    "/home/renku/work/canopy-air-temperatures-in-sub-doi-10.16904-envidat.722/"
    "jgr_atmospheres_haagmans.zip"
)
ROOT = "JGR_Atmospheres_Haagmans/"
ZIP_NAME = "jgr_atmospheres_haagmans.zip"

# Lapse-rate correction for Monstein (figure_2.m): stations at 1888 m (S) and 1869 m (N).
LAPSE_RATE = -0.6 / 100  # K per m
LR_NORTH_COR = (1888 - 1869) * LAPSE_RATE  # = -0.114 K

SEASONS = {
    "fluela_2023": "Flüela 2023",
    "monstein_2024": "Monstein 2024",
    "monstein_2025": "Monstein 2025",
}


@dataclass
class Archive:
    """Read files straight from the EnviDat zip (e.g. on the read-only data connector mount)."""

    zip_path: Path = DEFAULT_ZIP

    def __post_init__(self) -> None:
        self._zip = zipfile.ZipFile(self.zip_path)

    def open(self, rel: str):
        """Stream any file of the archive (path relative to the archive root)."""
        return self._zip.open(ROOT + rel)

    def names(self) -> list[str]:
        return [n.removeprefix(ROOT) for n in self._zip.namelist()]

    def mat(self, rel: str) -> dict:
        """Load ``processed_data/<rel>`` and return its single top-level struct as a dict.

        ``mat-io`` only accepts a filesystem path, so the member is copied from the zip into
        a temporary file that is deleted as soon as it has been parsed.
        """
        import matio

        with tempfile.NamedTemporaryFile(suffix=".mat") as tmp:
            with self.open("processed_data/" + rel) as src:
                shutil.copyfileobj(src, tmp)
            tmp.flush()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # datetime 'fmt' property is ignored, harmless
                raw = matio.load_from_mat(tmp.name)
        (value,) = [v for k, v in raw.items() if not k.startswith("__")]
        return _struct_to_dict(value)


def _struct_to_dict(x):
    """Turn mat-io's 1x1 structured arrays into nested dicts; leave tables/arrays alone."""
    if isinstance(x, np.ndarray) and x.dtype.names:
        if x.size == 1:
            return {f: _struct_to_dict(x[f].item()) for f in x.dtype.names}
    return x


def _series(tt: pd.DataFrame, name: str) -> pd.Series:
    """A single-variable MATLAB timetable as a float Series with a clean DatetimeIndex."""
    s = tt.iloc[:, 0].astype(float).rename(name)
    s.index = pd.DatetimeIndex(s.index, name="time")
    return s


# --------------------------------------------------------------------------------------
# Per-season harmonisation (port of figure_2.m)
# --------------------------------------------------------------------------------------


def fluela_2023(ar: Archive) -> pd.DataFrame:
    v = ar.mat("ventilated_stations_fluela_202223.mat")
    df = pd.concat([_series(v["N_AT"], "north"), _series(v["S_AT"], "south")], axis=1)
    df["north_src"] = df["south_src"] = "ventilated"
    return df


def monstein_2024(ar: Archive) -> pd.DataFrame:
    v = ar.mat("ventilated_stations_monstein_202324.mat")
    n1 = _series(v["N_AT1"], "north") + LR_NORTH_COR
    n2 = _series(v["N_AT2"], "north") + LR_NORTH_COR
    switch = n1.index[531169 - 1]  # MATLAB is 1-based
    north = n1.where(n1.index < switch, n2)
    south = _series(v["S_AT"], "south")
    df = pd.concat([north, south], axis=1)
    df = df[df.index.second == 0]  # 15 s grid, but only full minutes carry data
    df["north_src"] = df["south_src"] = "ventilated"
    df.attrs["north_sensor_switch"] = str(switch)
    return df


def monstein_2025(ar: Archive) -> pd.DataFrame:
    v = ar.mat("ventilated_stations_monstein_202425.mat")
    hobo = ar.mat("HOBO_monstein_202425.mat")

    def to15(tt, name):
        s = _series(tt, name)
        # MATLAB retime(...,'regular','mean','TimeStep',minutes(15),'IncludedEdge','left')
        return s.resample("15min", label="left", closed="left").mean()

    north = to15(v["N_AT"], "north")
    south = to15(v["S_AT"], "south")
    south.iloc[70434 - 1 :] = np.nan  # south station unreliable from 12 March on
    sel = slice(62303 - 1, 84013)  # window aligned with the HOBO record
    north, south = north.iloc[sel], south.iloc[sel]

    hobo_n = _series(hobo["N_V"]["cm150"], "north")  # 'cm150' = logger at 1.0 m
    hobo_s = _series(hobo["S_V"]["cm150"], "south")
    assert len(hobo_n) == len(north) == len(hobo_s) == len(south)
    # figure_2.m fills by position; check that positions really are the same timestamps
    lag = (north.index - hobo_n.index).to_series().abs().max()
    assert lag < pd.Timedelta("15min"), f"HOBO/ventilated misaligned by {lag}"

    df = pd.DataFrame(index=north.index)
    for col, vent, hb in [("north", north, hobo_n), ("south", south, hobo_s)]:
        gap = vent.isna().to_numpy()
        df[col] = np.where(gap, hb.to_numpy(), vent.to_numpy())
        df[f"{col}_src"] = np.where(gap, "hobo_1m", "ventilated")
    df["north"] += LR_NORTH_COR
    df.attrs["south_cutoff"] = str(_series(v["S_AT"], "s").resample("15min").mean().index[70434 - 1])
    return df[["north", "south", "north_src", "south_src"]]


def snow_cover(ar: Archive) -> pd.DataFrame:
    """Periods with snow cover below the canopy, per season and slope."""
    spec = {
        "fluela_2023": ("SC_periods_Fluela2223.mat", "SC_periods_north_V", "SC_periods_south_V"),
        "monstein_2024": ("SC_periods_Monstein2324.mat", "SC_periods_north", "SC_periods_south"),
        "monstein_2025": ("SC_periods_Monstein2425.mat", "SC_periods_north", "SC_periods_south"),
    }
    rows = []
    for season, (fn, n_key, s_key) in spec.items():
        m = ar.mat(fn)
        for slope, key in [("north", n_key), ("south", s_key)]:
            for start, end in np.atleast_2d(m[key]):
                rows.append((season, slope, pd.Timestamp(start), pd.Timestamp(end)))
    return pd.DataFrame(rows, columns=["season", "slope", "start", "end"])


BUILDERS = {"fluela_2023": fluela_2023, "monstein_2024": monstein_2024, "monstein_2025": monstein_2025}


def load_native(ar: Archive | None = None) -> dict[str, pd.DataFrame]:
    """Harmonised north/south canopy air temperature per season, at native resolution."""
    ar = ar or Archive(find_zip())
    return {k: f(ar) for k, f in BUILDERS.items()}


def to_tidy(native: dict[str, pd.DataFrame], freq: str = "15min") -> pd.DataFrame:
    """Resample every season to ``freq`` and stack into one long-ish table.

    A bin's ``*_src`` is ``hobo_1m`` if any sample in it came from the HOBO gap-fill.
    """
    out = []
    for season, df in native.items():
        num = df[["north", "south"]].resample(freq).mean()
        filled = df[["north_src", "south_src"]].eq("hobo_1m").resample(freq).max()
        src = pd.DataFrame(
            np.where(filled.fillna(False).astype(bool), "hobo_1m", "ventilated"),
            index=filled.index,
            columns=filled.columns,
        )
        part = num.join(src).dropna(subset=["north", "south"], how="all")
        part.insert(0, "season", season)
        out.append(part.reset_index())
    tidy = pd.concat(out, ignore_index=True)
    tidy["season"] = tidy["season"].astype("category")
    for c in ("north_src", "south_src"):
        tidy[c] = tidy[c].astype("category")
    return tidy


def find_zip() -> Path:
    """Locate the archive on the Renku data connector mount.

    Order: ``$CANOPY_ZIP``; the default session mount path; a search up to two levels
    below ``$RENKU_MOUNT_DIR``, the working directory and its parent.
    """
    if env := os.environ.get("CANOPY_ZIP"):
        return Path(env)
    if DEFAULT_ZIP.exists():
        return DEFAULT_ZIP
    roots = [os.environ.get("RENKU_MOUNT_DIR"), os.getcwd(), str(Path.cwd().parent)]
    for root in filter(None, roots):
        for pattern in (ZIP_NAME, f"*/{ZIP_NAME}", f"*/*/{ZIP_NAME}"):
            hits = sorted(Path(root).glob(pattern))
            if hits:
                return hits[0]
    raise FileNotFoundError(
        f"{ZIP_NAME} not found. Mount the EnviDat data connector or set CANOPY_ZIP to the zip's path."
    )
