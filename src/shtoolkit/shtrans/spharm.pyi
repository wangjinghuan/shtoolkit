import numpy as np

def spharm_func(lat: float, lon: float, lmax: int) -> np.ndarray: ...
def spharm_func_map(lat: np.ndarray, lon: np.ndarray, lmax: int) -> np.ndarray: ...
