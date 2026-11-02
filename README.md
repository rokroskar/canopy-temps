# canopy-temps

A notebook and a small [Panel](https://panel.holoviz.org) app for the EnviDat dataset

> Haagmans, V., Mazzotti, G., Jonas, T. (2025). *Canopy air temperatures in subalpine forests during three snow seasons.*
> EnviDat. [doi:10.16904/envidat.722](https://doi.org/10.16904/envidat.722) (CC-BY-4.0)

Ventilated weather stations measured canopy air temperature on a **north- and a south-facing forest slope** of the same
valley during three winters (Flüela 2023, Monstein 2024 and 2025, near Davos). The south-facing forest is 1–3 K warmer
on an average early afternoon; at night the two slopes are equally cold.

## Contents

| path | what |
|---|---|
| `notebooks/canopy_air_temperatures.ipynb` | Tour of the archive: raw logger files (incl. two traps: mislabelled READMEs and a 12 h AM/PM flip in the Flüela HOBO files), the processed MATLAB data, and a Python reproduction of **Figure 2** of the paper |
| `app.py` | Panel app: *A typical day* (interactive Figure 2) and *Through the season* (timeline, south − north difference, snow cover) |
| `Procfile` | `web:` command for the Renku app launcher |
| `src/canopy_temps/prepare.py` | Reads the zip and ports the harmonisation in `scripts_figures/figure_2.m` |
| `src/canopy_temps/analysis.py` | Loading and the computations shared by notebook and app |

## Data

Nothing is stored in this repository. Everything is read **directly from the EnviDat zip** with `zipfile`, as mounted by
the Renku data connector. The zip is located in this order:

1. `$CANOPY_ZIP`, if set (e.g. as an environment variable on the app launcher);
2. `/home/renku/work/canopy-air-temperatures-in-sub-doi-10.16904-envidat.722/jgr_atmospheres_haagmans.zip`;
3. a search for `jgr_atmospheres_haagmans.zip` up to two levels below `$RENKU_MOUNT_DIR`, the working directory and its parent.

The authors' processed files are MATLAB `timetable`s, which `scipy` cannot read. They are decoded with
[`mat-io`](https://pypi.org/project/mat-io/). Since `mat-io` only accepts a file path, each `.mat` member is copied into a
temporary file that is deleted right after parsing.

The app builds its 15-min tables in memory once per process (about 5 s). `panel serve --warm` does this at startup, so the
first visitor doesn't wait.

## Running

```bash
uv sync
uv run panel serve app.py --show          # app
uv run jupyter lab notebooks/             # or open the notebook in VS Code
```

On Renku, the app launcher builds from this repository and runs the `web:` line of the `Procfile`, listening on
`$RENKU_SESSION_PORT`. The EnviDat data connector must be attached to the project, and it must be public, since apps only
mount public connectors.
