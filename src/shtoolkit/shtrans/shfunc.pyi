import numpy as np

def cilm2vector(coeffs: np.ndarray) -> np.ndarray: ...
def vector2cilm(vector: np.ndarray) -> np.ndarray: ...
def shreal2complex(cilm: np.ndarray) -> np.ndarray: ...
def shcomplex2real(cilm_complex: np.ndarray) -> np.ndarray: ...