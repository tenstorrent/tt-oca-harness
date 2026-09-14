# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OSS PyUVM environment package.

Wraps ``ocah_axi_vip`` in a UVM hierarchy:
config -> CPU-LSU AXI master agent (sequencer/driver) -> scoreboard -> env.

Bus-idle determinism (the LSU splice must never see X from the external
master) is guaranteed by the VIP itself: every OCAH AXI driver drives its
source payload signals to 0 at construction (``init_signals``). This package
does not touch cocotb or cocotbext-axi global state.
"""

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
