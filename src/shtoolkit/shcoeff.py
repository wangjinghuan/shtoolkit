import re
import copy
from pathlib import Path
from typing import Literal, Optional, Sequence

import numpy as np

from .shload import (
    read_icgem,
    read_non_icgem,
    read_technical_note_c20_c30,
    read_technical_note_deg1,
    read_gia_model,
)
from .shtrans import cilm2grid
from .shunit import convert
from .shtype import SpharmUnit, SHSmoothKind, GIAModel, LoadLoveNumDict
from .shfilter import gauss_smooth, fan_smooth

__all__ = ["SpharmCoeff", "ReplaceCoeff"]


class SpharmCoeff:
    def __init__(
        self,
        coeffs: np.ndarray,
        epochs: np.ndarray | float, 
        unit: SpharmUnit,
        errors: np.ndarray | None = None,
        error_kind: str | None = None,
        name: str | None = None,
    ):
        if errors is not None:
            if coeffs.shape != errors.shape:
                msg = f"The shape of 'coeffs' {coeffs.shape}, is unequal to that of 'errors' {errors.shape}"
                raise ValueError(msg)
            
        if coeffs.ndim == 4:
            self.coeffs = coeffs.copy()
            self.errors = errors.copy() if errors is not None else None
        elif coeffs.ndim == 3:
            self.coeffs = coeffs.copy()[np.newaxis]
            self.errors = errors.copy()[np.newaxis] if errors is not None else None
        else:
            msg = f"Invalid ndim of 'coeffs' {coeffs.ndim}, must be 4 or 3"
            raise ValueError(msg)
        
        epochs =  epochs.copy() if isinstance(epochs, np.ndarray) else np.array([epochs])
        if self.coeffs.shape[0] != epochs.shape[0]:
            msg = f"The number of 'coeffs' {self.coeffs.shape[0]} is unequal to that of 'epochs' {epochs.shape[0]}"
            raise ValueError(msg)
        
        self.lmax = coeffs.shape[-2] - 1
        self.epochs = epochs
        self.unit: SpharmUnit = unit
        self.error_kind = error_kind
        self.name = name

    @classmethod
    def from_files(
        cls,
        folder: str | Path,
        lmax: int,
        is_icgem: bool = True,
    ):
        if isinstance(folder, str):
            folder = Path(folder)

        files = [file for file in folder.iterdir()]

        if is_icgem:
            data = [read_icgem(file, lmax) for file in files]
        else:
            data = [read_non_icgem(file, lmax) for file in files]
        epochs, coeffs, errors = map(np.array, zip(*data))

        center = re.findall(r"UTCSR|GFZOP|JPLEM|COSTG|GRGS|AIUB|ITSG|HUST|Tongji", files[0].stem)
        name = f"GSM: {center[0]}\n" if center else None
        return cls(coeffs, epochs, "stokes", errors, name=name).sort()

    def rplce(
        self,
        rpname: str | Sequence[str] | None = None,
        rppath: str | Sequence[str] | None = None,
        rpcoef: Optional["ReplaceCoeff"] = None,
    ):
        if self.unit != "stokes":
            msg = "Inconsistent attribute 'unit', it only accepts 'stokes'"
            raise AttributeError(msg)

        sphcoef = copy.deepcopy(self)
        if rpcoef is None:
            lowdeg_dict = {
                "C20": ReplaceCoeff.from_technical_note_c20,
                "C30": ReplaceCoeff.from_technical_note_c30,
                "DEG1": ReplaceCoeff.from_technical_note_deg1,
            }
            if rpname is not None and rppath is not None:
                if type(rpname) == type(rppath):
                    if isinstance(rpname, str):
                        rpcoef = lowdeg_dict[rpname](rppath)
                        sphcoef = rpcoef.apply_to(sphcoef)
                    else:
                        for i in range(len(rpname)):
                            rpcoef = lowdeg_dict[rpname[i]](rppath[i])
                            sphcoef = rpcoef.apply_to(sphcoef)  # type: ignore
                else:
                    msg = f"Invalid type of rpname <{type(rpname)}> and rppath <{type(rppath)}>, must be same."
                    raise ValueError(msg)
            else:
                msg = f"Invalid value of rpname <{rpname}> and rppath <{rppath}>, must be str or sequence str."
                raise ValueError(msg)
        else:
            sphcoef = rpcoef.apply_to(self)
        return sphcoef

    def corr_gia(
        self,
        modelname: GIAModel,
        filepath: str | Path,
        mode: Literal["add", "subtract"] = "subtract",
    ):
        if mode not in ["add", "subtract"]:
            msg = f"Invalid value of mode <{mode}>, must be subtract or add."
            raise ValueError(msg)

        lmax = self.lmax
        gia_trend = read_gia_model(filepath, lmax, modelname)
        gia_coeffs = np.array([epoch * gia_trend for epoch in self.epochs])
        gia_coeffs -= gia_coeffs.mean(axis=0)

        name = self.name
        if mode == "subtract":
            coeffs = self.coeffs - gia_coeffs
            if isinstance(name, str):
                name += f"GIA: {modelname}\n"
        elif mode == "add":
            coeffs = self.coeffs + gia_coeffs

        print(f"GIA was {mode}ed by {modelname}.")

        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        sphcoef_attr["name"] = name
        return SpharmCoeff(**sphcoef_attr)

    def sort(self):
        coeffs_sorted = self.coeffs[np.argsort(self.epochs)]
        if self.errors is not None:
            errors_sorted = self.errors[np.argsort(self.epochs)]
        else:
            epochs_sorted = None

        epochs_sorted = np.sort(self.epochs)
        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs_sorted
        sphcoef_attr["errors"] = errors_sorted
        sphcoef_attr["epochs"] = epochs_sorted
        return SpharmCoeff(**sphcoef_attr)

    def remove_mean_field(self):
        coeffs = self.coeffs - self.coeffs.mean(axis=0)
        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        return SpharmCoeff(**sphcoef_attr)

    def pole_tide_correct(self, reference_time: float = 2000.0):
        """
        it is suggested to apply the method in RL05 and before.
        """
        dtime = self.epochs.copy()
        coeffs = np.copy(self.coeffs)
        delta_time = dtime - reference_time

        ai_before = np.array([0.055974, 1.8243e-3, 1.8413e-4, 7.024e-6])
        ai_after = np.array([0.023513, 7.6141e-3, 0, 0])

        bi_before = np.array([-0.346346, -1.7896e-3, 1.0729e-4, 0.908e-6])
        bi_after = np.array([-0.358891, 0.6287e-3, 0, 0])

        m1p, m2p = 0.0, 0.0
        for i in range(4):
            m1p += np.append(
                delta_time[dtime <= 2010.0] * ai_before[i],
                delta_time[dtime > 2010.0] * ai_after[i],
            ).sum()
            m2p += np.append(
                delta_time[dtime <= 2010.0] * bi_before[i],
                delta_time[dtime > 2010.0] * bi_after[i],
            ).sum()

        # m1_gia = 1.677e-3 * delta_time
        # m2_gia = - 3.46e-3 * delta_time
        m1_gia = 0.62e-3 * delta_time
        m2_gia = -3.48e-3 * delta_time

        coeffs[:, 0, 2, 1] -= -1.551e-9 * (m1p - m1_gia) - 0.012e-9 * (m2p - m2_gia)
        coeffs[:, 1, 2, 1] -= 0.021e-9 * (m1p - m1_gia) - 1.505e-9 * (m2p - m2_gia)

    def smooth(self, kind: SHSmoothKind = "gauss", radius: int = 300) -> "SpharmCoeff":
        if kind == "gauss":
            weight = gauss_smooth(self.lmax, radius)
        elif kind == "fan":
            weight = fan_smooth(self.lmax, radius)
        coeffs = self.coeffs * weight

        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        return SpharmCoeff(**sphcoef_attr)

    def expand(self, resol: int, lmax_calc: int = -1):
        from .shgrid import SphereGrid

        data = np.array([cilm2grid(cilm, resol, lmax_calc) for cilm in self.coeffs])
        return SphereGrid(data, self.epochs.copy(), self.unit)

    def unitconvert(self, new_unit: SpharmUnit, lln: LoadLoveNumDict | None = None):
        coeffs_new = convert(self.coeffs, self.unit, new_unit, lln)
        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs_new
        sphcoef_attr["unit"] = new_unit
        return SpharmCoeff(**sphcoef_attr)

    def __getitem__(self, index):
        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = sphcoef_attr["coeffs"][index]
        if isinstance(index, int):
            sphcoef_attr["epochs"] = np.array([sphcoef_attr["epochs"][index]])
        else:
            sphcoef_attr["epochs"] = sphcoef_attr["epochs"][index]
        if sphcoef_attr["errors"] is not None:
            sphcoef_attr["errors"] = sphcoef_attr["errors"][index]
        return SpharmCoeff(**sphcoef_attr)

    def __len__(self):
        if self.coeffs.ndim == 3:
            return 1
        else:
            return self.coeffs.shape[0]

    def __add__(self, other):
        if isinstance(other, SpharmCoeff):
            if self.coeffs.shape == other.coeffs.shape and np.allclose(self.epochs, other.epochs, atol=0.5):
                coeffs = self.coeffs + other.coeffs
            elif self.coeffs.shape[1:] == other.coeffs.shape[1:]:
                count = 0
                coeffs = np.copy(self.coeffs)
                for idx, t1 in enumerate(self.epochs):
                    residual = np.abs(other.epochs - t1)
                    if np.min(residual) < 0.05:
                        count += 1
                        argmin = np.argmin(residual)
                        coeffs[idx] += other.coeffs[argmin]
                if count != self.epochs.size:
                    msg = f"Invalid value of add_counts <{count}>, must be {self.epochs.size}."
                    raise ValueError(msg)
        else:
            msg = "Mathematical operator not implemented for these operands."
            raise NotImplementedError(msg)

        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        return SpharmCoeff(**sphcoef_attr)

    def __sub__(self, other):
        if isinstance(other, SpharmCoeff):
            if self.coeffs.shape == other.coeffs.shape and np.allclose(self.epochs, other.epochs, atol=0.5):
                coeffs = self.coeffs + other.coeffs
            elif self.coeffs.shape[1:] == other.coeffs.shape[1:]:
                count = 0
                coeffs = np.copy(self.coeffs)
                for idx, t1 in enumerate(self.epochs):
                    residual = np.abs(other.epochs - t1)
                    if np.min(residual) < 0.05:
                        count += 1
                        argmin = np.argmin(residual)
                        coeffs[idx] -= other.coeffs[argmin]
                if count != self.epochs.size:
                    msg = f"Invalid value of sub_counts <{count}>, must be {self.epochs.size}."
                    raise ValueError(msg)
        else:
            msg = "Mathematical operator not implemented for these operands."
            raise NotImplementedError(msg)

        sphcoef_attr = copy.deepcopy(self.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        return SpharmCoeff(**sphcoef_attr)


class ReplaceCoeff:
    def __init__(
        self,
        indice: Sequence[int] | Sequence[Sequence[int]],
        coeffs: np.ndarray,
        epochs: np.ndarray,
        unit: SpharmUnit,
        errors: np.ndarray | None = None,
        name: Sequence[str] | None = None,
    ) -> None:
        self.indice = indice
        self.coeffs = coeffs
        self.epochs = epochs
        self.unit: SpharmUnit = unit
        self.errors = errors
        self.name = name

    def apply_to(self, sphcoef: SpharmCoeff):

        coeffs = np.copy(sphcoef.coeffs)
        errors = copy.deepcopy(sphcoef.errors)

        for ori_idx, t in enumerate(sphcoef.epochs):
            if self.indice == (0, 3, 0) and t < 2018:
                continue
            residual = np.abs(self.epochs - t)
            if np.nanmin(residual) > 0.05:
                msg = f"Invalid value of epoch '{t:.4f}', which cannot be found in {self.name} epochs."
                raise ValueError(msg)
            rp_idx = np.nanargmin(residual)
            coeffs[ori_idx, *self.indice] = self.coeffs[rp_idx]
            if self.errors is not None and errors is not None:
                errors[ori_idx, *self.indice] = self.errors[rp_idx]

        sphname = sphcoef.name
        if isinstance(self.name, Sequence) and len(self.name) == 2:
            print(f"{self.name[0]} was replaced by {self.name[1]}.")
            if isinstance(sphname, str):
                sphname += f"{self.name[0]}: {self.name[1]}\n"
        elif self.name is None:
            print(f"The coeff at index {self.indice} was replaced.")
        else:
            msg = f"Invalid attribute of name <{self.name}>."
            raise AttributeError(msg)

        sphcoef_attr = copy.deepcopy(sphcoef.__dict__)
        del sphcoef_attr["lmax"]
        sphcoef_attr["coeffs"] = coeffs
        sphcoef_attr["errors"] = errors
        sphcoef_attr["name"] = sphname
        return SpharmCoeff(**sphcoef_attr)

    @classmethod
    def from_technical_note_c20(cls, filepath):
        indice = (0, 2, 0)
        epochs, c20, c20_sigma, _, _, center = read_technical_note_c20_c30(filepath)
        return cls(indice, c20, epochs, "stokes", c20_sigma, ("C20", center))

    @classmethod
    def from_technical_note_c30(cls, filepath):
        indice = (0, 3, 0)
        epochs, _, _, c30, c30_sigma, center = read_technical_note_c20_c30(filepath)
        return cls(indice, c30, epochs, "stokes", c30_sigma, ("C30", center))

    @classmethod
    def from_technical_note_deg1(cls, filepath):
        indice = tuple(zip((0, 1, 0), (0, 1, 1), (1, 1, 1)))
        epochs, deg1, deg1_sigma = read_technical_note_deg1(filepath)
        return cls(indice, deg1, epochs, "stokes", deg1_sigma, ("DEG1", "GRACE-OBP"))
