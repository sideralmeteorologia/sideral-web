#!/usr/bin/env python3
"""Composição vertical nativa de REFL_10CM, sem remapeamento ou preenchimento."""
from __future__ import annotations
import numpy as np

def native_composite_reflectivity(ds):
    if "REFL_10CM" not in ds.variables:
        raise KeyError("wrfout sem REFL_10CM; refletividade nativa indisponível")
    field = ds["REFL_10CM"]
    if "Time" in field.dims:
        field = field.isel(Time=0)
    vertical = [d for d in field.dims if d not in ("south_north", "west_east")]
    if len(vertical) > 1:
        raise ValueError(f"Dimensões inesperadas em REFL_10CM: {field.dims}")
    if vertical:
        field = field.max(dim=vertical[0], skipna=True)
    result = np.asarray(field.values, dtype=np.float32)
    if result.ndim != 2:
        raise ValueError(f"REFL_10CM deveria produzir grade 2D; shape={result.shape}")
    return result
