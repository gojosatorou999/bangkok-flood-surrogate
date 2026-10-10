"""Per-frame quality assessment. See docs/VARUN_IMPLEMENTATION.md §6 T20.

Check order: STALE (camera stuck on the same image) -> NIGHT_IR (too dark /
low saturation) -> BLUR (out of focus) -> OK.
"""
from __future__ import annotations

import cv2
import imagehash
import numpy as np
from PIL import Image

DEFAULT_CFG = {"stale_consecutive": 3, "night_mean_saturation": 12, "blur_laplacian_var": 40}


def assess(img: Image.Image, phash_hist: list[str], cfg: dict | None = None) -> dict:
    """Returns {quality_flag, sat_mean, lap_var, phash}.

    `phash_hist` is this camera's previous pHashes, most recent last; the
    caller is responsible for appending the returned `phash` to it afterward.
    """
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    phash = str(imagehash.phash(img))

    hsv = np.asarray(img.convert("HSV"))
    sat_mean = float(hsv[:, :, 1].mean())
    gray = np.asarray(img.convert("L"))
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    stale_n = cfg["stale_consecutive"]
    recent = (phash_hist + [phash])[-stale_n:]
    if len(recent) == stale_n and len(set(recent)) == 1:
        flag = "STALE"
    elif sat_mean < cfg["night_mean_saturation"]:
        flag = "NIGHT_IR"
    elif lap_var < cfg["blur_laplacian_var"]:
        flag = "BLUR"
    else:
        flag = "OK"

    return {"quality_flag": flag, "sat_mean": sat_mean, "lap_var": lap_var, "phash": phash}
