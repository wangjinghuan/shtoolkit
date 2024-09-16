from typing import Literal, TypedDict
from pathlib import Path

import numpy as np


__all__ = [
    "LoadLoveNumDict",
    "LeakCorrMethod",
    "SpharmUnit",
    "GIAModel",
    "SHSmoothKind",
    "MassConserveMode",
    "RepLowDegDict",
]


class LoadLoveNumDict(TypedDict):
    h_el: np.ndarray
    l_el: np.ndarray
    k_el: np.ndarray


class LeakCorrMethod(TypedDict):
    method: Literal["buf", "buf_gs", "buf_fs", "FM_gs", "FM_fs"]
    radius: int | None


class RepLowDegDict(TypedDict):
    rep: str
    file: str | Path


SpharmUnit = Literal[
    "mmewh",
    "mewh",
    "kmewh",
    "mmgeo",
    "mgeo",
    "kmgeo",
    "mmupl",
    "mupl",
    "kmupl",
    "kgm2mass",
    "stokes",
]
GIAModel = Literal["ICE6G-D", "ICE6G-C", "C18"]
SHSmoothKind = Literal["gauss", "fan"]
MassConserveMode = Literal["eustatic", "sal", "sal_rot"]
