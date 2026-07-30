# SPDX-License-Identifier: Apache-2.0
"""SEP OSS PyUVM environment package.

Wraps the open-source cocotbext-axi VIP in a UVM hierarchy:
config -> CPU-LSU AXI master agent (sequencer/driver) -> scoreboard -> env.

A 32-bit read on the 64-bit LSU bus leaves the unused byte lanes unknown; resolve
X->0 (and disable cocotbext-axi source X-init) on import, before any cocotbext-axi
object is constructed, so int() conversions are robust on 4-state and VPI paths.
"""

import os


def _apply_axi_x_resolution() -> None:
    try:
        # Intentional OSS exception: this patches cocotbext stream initialization
        # before any SEP AXI master is constructed.
        from cocotbext.axi import stream as _axi_stream

        _axi_stream.StreamSource._init_x = False
    except Exception:
        pass
    try:
        import cocotb.binary as _cb

        if os.getenv("COCOTB_RESOLVE_X") is None:
            _cb.resolve_x_to = _cb._ResolveXToValue.ZEROS
            _cb._resolve_table = _cb._ResolveTable()
    except Exception:
        pass


_apply_axi_x_resolution()

from .sep_axi_agent import SepAxiAgent, SepAxiDriver, SepAxiItem, SepAxiOp
from .sep_env import SepEnv
from .sep_env_cfg import SepEnvCfg
from .sep_scoreboard import SepScoreboard

__all__ = [
    "SepAxiAgent",
    "SepAxiDriver",
    "SepAxiItem",
    "SepAxiOp",
    "SepEnv",
    "SepEnvCfg",
    "SepScoreboard",
]
