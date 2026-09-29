# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register and field metadata for the CLA MMR block of the SMC_CLA aperture.

:mod:`seq_lib.smc_rdl_regmap` reads the PeakRDL IP-XACT export of the SMC
register map, which is the only generated artefact carrying the RDL software
access type, volatility and read/write modifiers of every field. The CLA
sub-block is a register file with one element, so its IP-XACT path
(``smc_cla/cla/<Name>``) and the instance symbol the generated ``smc_reg.py``
exports (``SMC_CLA_CLA_0__<NAME>_REG_ADDR``) spell the same register
differently and ``smc_rdl_regmap.rdl_register`` cannot bridge them. This module
bridges them and holds every address it hands out to the two generated views
agreeing on it.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from .smc_addr_map import _REPO
from .smc_rdl_regmap import RdlField, RdlReg, rdl_registers_under

_BLOCK = "smc_cla/cla"
_SYMBOL_PREFIX = "SMC_CLA_CLA_0__"
_SMC_REG_PY = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "py"


@lru_cache(maxsize=1)
def cla_registers() -> dict[str, RdlReg]:
    """Every CLA MMR register by RDL name, cross-checked against ``smc_reg.py``."""
    if str(_SMC_REG_PY) not in sys.path:
        sys.path.insert(0, str(_SMC_REG_PY))
    import smc_reg as _r

    out: dict[str, RdlReg] = {}
    for reg in rdl_registers_under(_BLOCK):
        name = reg.path.rsplit("/", 1)[1]
        symbol = f"{_SYMBOL_PREFIX}{name.upper()}_REG_ADDR"
        mapped = getattr(_r, symbol, None)
        assert mapped is not None, (
            f"{reg.path}: the IP-XACT map places it at 0x{reg.addr:08x} but the "
            f"generated smc_reg.py declares no {symbol}, so the two generated views "
            f"of the same RDL do not agree on this register"
        )
        assert mapped == reg.addr, (
            f"{reg.path}: IP-XACT says 0x{reg.addr:08x}, smc_reg.{symbol} says 0x{mapped:08x}"
        )
        out[name] = reg
    return out


def cla_register(name: str) -> RdlReg:
    """One CLA MMR register by its RDL name."""
    try:
        return cla_registers()[name]
    except KeyError as exc:
        raise KeyError(f"{name} is not a register of {_BLOCK}") from exc


def cla_field(reg: RdlReg, name: str) -> RdlField:
    """One field of a CLA MMR register by its RDL name."""
    for field in reg.fields:
        if field.name == name:
            return field
    raise KeyError(f"{reg.path} has no field {name} in the generated map")
