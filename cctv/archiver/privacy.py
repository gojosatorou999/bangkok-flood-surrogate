"""Face/plate blurring, applied before any frame is written to disk (PDPA, Agent rule 6).

See docs/VARUN_IMPLEMENTATION.md §6 T20.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

_face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_plate = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_russian_plate_number.xml")


def blur_sensitive(img: Image.Image) -> Image.Image:
    a = np.asarray(img).copy()
    g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    for det in (_face, _plate):
        for (x, y, w, h) in det.detectMultiScale(g, 1.1, 4, minSize=(12, 12)):
            a[y : y + h, x : x + w] = cv2.GaussianBlur(a[y : y + h, x : x + w], (0, 0), sigmaX=max(w, h) / 3)
    return Image.fromarray(a)
