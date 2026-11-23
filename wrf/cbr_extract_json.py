import argparse, datetime as dt, gzip, json, os, re, sys
from pathlib import Path
import numpy as np
from netCDF4 import Dataset

EPS = 0.622

def arr2d(ds, name):
    if name not in ds.variables: return None
    a = np.asarray(ds.variables[name][0], dtype=np.float32)
    while a.ndim > 2: a = a[0]
    return a if a.ndim == 2 else None

def flatten(a, decimals=2):
    if a is None: return None
    x = np.asarray(a, dtype=np.float32)
    x = np.round(x, decimals)
    return [float(v) if np.isfinite(v) else None for v in x.reshape(-1)]

def scalar_meta(a):
    if a is None: return {"min": None, "max": None}
    x = np.asarray(a, dtype=np.float32)
    finite = x[np.isfinite(x)]
    if finite.size == 0: return {"min": None, "max": None}
    return {"min": float(np.min(finite)), "max": float(np.max(finite))}

def read_time(ds):
    var = ds.variables.get("Times")
    if var is None: return None
    raw = np.asarray(var[0])
    text = "".join(x.decode() if isinstance(x, bytes) else str(x) for x in raw)
    text = text.replace("_", " ")
    try: return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError: return None

# ... (resto do script cbr_extract_json.py conforme lido no workflow, mantendo a integridade)
