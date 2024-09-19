# cython: language_level=3
# cython: cdivision=True
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False

from libc.math cimport sin, cos, pi, sqrt
from libc.stdlib cimport malloc, free

import numpy as np
cimport numpy as cnp
import scipy as sp

from .legendre import fnALFs_cache

"""
Reference
---------
[1] Wieczorek, M. A., & Meschede, M. (2018). SHTools: Tools for working 
        with spherical harmonics. Geochemistry, Geophysics, Geosystems, 
        19, 2574-2592. https://doi.org/10.1029/2018GC007529
[2] Rexer, M., Hirt, C. Ultra-high-Degree Surface Spherical Harmonic Analysis 
        Using the Gauss-Legendre and the Driscoll/Healy Quadrature Theorem and 
        Application to Planetary Topography Models of Earth, Mars and Moon. 
        Surv Geophys 36, 803-830 (2015). https://doi.org/10.1007/s10712-015-9345-z
"""


def grid2cilm_fft(
    double[:,:] grid,
    int calc_lmax = -1
):
    cdef: 
        int nlat = grid.shape[0]
        int nlon = grid.shape[1]
        int resol = nlat / 2 - 1
        double c, s
        Py_ssize_t k, l, m
        tuple rad_colat = tuple(np.linspace(0, pi, nlat, endpoint=False))
        double *weight
        double complex[::1,:] lat_fft
        double[:,:,:] pilm
        double[:,:,:] cilm

    if nlat % 2 != 0:
        raise ValueError(f"Invalid value of nlat: {nlat}, (expected even)")

    if calc_lmax < 0:
        calc_lmax = resol
    elif calc_lmax > resol:
        raise ValueError(f"Invalid value of calc_lmax: {calc_lmax}, must smaller than 'resol': {2*nlat-1}")

    pilm = fnALFs_cache(rad_colat, calc_lmax)

    weight = weight_dh(nlat)
    lat_fft = np.asarray(sp.fft.rfft(grid, axis=1), order='F')
    cilm = np.zeros((2, calc_lmax + 1, calc_lmax + 1))
    for l in range(calc_lmax + 1):
        for m in range(l + 1):
            c = 0.0
            s = 0.0
            for k in range(nlat):
                c += pilm[k, l, m] * lat_fft[k, m].real * weight[k]
                # c += pilm[l, m, k] * lat_fft[k, m].real * weight[k]
                if m:
                    s += pilm[k, l, m] * (-lat_fft[k, m].imag) * weight[k]
                    # s += pilm[l, m, k] * (-lat_fft[k, m].imag) * weight[k]
            cilm[0, l, m] = c
            cilm[1, l, m] = s
    free(weight)
    return np.asarray(cilm)


def grid2cilm_fft_refined(
    double[:,:] grid,
    int calc_lmax = -1
):
    cdef: 
        int nlat = grid.shape[0]
        int nlon = grid.shape[1]
        int resol = nlat // 2 - 1
        double c, s
        int l, m
        int k, ks
        tuple rad_colat = tuple(np.linspace(0, pi, nlat, endpoint=False))
        double *weight
        double complex[:,:] lat_fft
        double complex[:] fcoef, fcoefs
        double[:,:,:] pilm
        double[:,:,:] cilm
        double[:,:] plm, plms
        
    if nlat % 2 != 0:
        raise ValueError(f"Invalid value of nlat: {nlat}, (expected even)")

    if calc_lmax < 0:
        calc_lmax = resol
    elif calc_lmax > resol:
        raise ValueError(f"Invalid value of calc_lmax: {calc_lmax}, must smaller than 'resol': {2*nlat-1}")

    pilm = fnALFs_cache(rad_colat, calc_lmax)

    weight = weight_dh(nlat)
    lat_fft = sp.fft.rfft(grid)
    cilm = np.zeros((2, calc_lmax + 1, calc_lmax + 1))

    for k in range(nlat // 2):
        ks = nlat - 1 - k

        fcoef = lat_fft[k]
        fcoefs = lat_fft[ks]

        plm = pilm[k]
        plms = pilm[ks]

        w = weight[k]
        ws = weight[ks]

        for l in range(calc_lmax + 1):
            for m in range(l + 1):
                cilm[0, l, m] += plm[l, m] * fcoef[m].real * w + plms[l, m] * fcoefs[m].real * ws
                if m:
                    cilm[1, l, m] += plm[l, m] * (- fcoef[m].imag) * w + plms[l, m] * (- fcoefs[m].imag) * ws

    free(weight)
    return np.asarray(cilm)

def grid2cilm_integral(
    double[:,:] grid,
    int calc_lmax = -1
):
    cdef: 
        int nlat = grid.shape[0] 
        int nlon = grid.shape[1]
        int resol = nlat / 2 - 1
        Py_ssize_t k, l, m
        tuple rad_colat = tuple(np.linspace(0, pi, nlat, endpoint=False))
        double[:] rad_lon = np.linspace(0, 2.0 * pi, nlon, endpoint=False)
        double *weight
        double[:,:] ccos
        double[:,:] ssin
        double[::1,:] am
        double[::1,:] bm
        double c, s
        double[:,:,:] pilm
        double[:,:,:] cilm

    if nlat % 2 != 0:
        raise ValueError(f"Invalid value of nlat: {nlat}, (expected even)")

    if calc_lmax < 0:
        calc_lmax = resol
    elif calc_lmax > resol:
        raise ValueError(f"Invalid value of calc_lmax: {calc_lmax}, must smaller than 'resol': {2*nlat-1}")

    pilm = fnALFs_cache(rad_colat, calc_lmax)

    ccos = np.zeros((nlon, calc_lmax + 1))
    ssin = np.zeros((nlon, calc_lmax + 1))
    for k in range(nlon):
        for m in range(calc_lmax + 1):
            ccos[k, m] = cos(rad_lon[k] * m)
            ssin[k, m] = sin(rad_lon[k] * m)

    weight = weight_dh(nlat)
    am = np.asarray(np.dot(grid, ccos), order='F')
    bm = np.asarray(np.dot(grid, ssin), order='F')
    cilm = np.zeros((2, calc_lmax + 1, calc_lmax + 1))
    for l in range(calc_lmax + 1):
        for m in range(l + 1):
            c = 0.0
            s = 0.0
            for k in range(nlat):
                c += pilm[k, l, m] * am[k, m] * weight[k]
                # c += pilm[l, m, k] * am[k, m] * weight[k]
                if m:
                    s += pilm[k, l, m] * bm[k, m] * weight[k]
                    # s += pilm[l, m, k] * bm[k, m] * weight[k]
            cilm[0, l, m] = c
            cilm[1, l, m] = s
    free(weight)
    return np.asarray(cilm)


cdef inline double *weight_dh(int nlat) except NULL:
    cdef:
        int lmax = nlat // 2 -1 
        double *w = <double *> malloc(sizeof(double) * nlat)
        Py_ssize_t j, l
        double s
        double colat
        double dlon = pi / nlat
        double fpi = 4 * pi

    for j in range(nlat):
        s = 0
        colat = pi * j / nlat
        for l in range(lmax + 1):
            s += sin((2 * l + 1) * colat) / (2 * l + 1)
        w[j] = s * sin(colat) * sqrt(8.0) / nlat * sqrt(2.0) * dlon / fpi
    return w