# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Environment configuration base: derived from the test cfg, read by the env, never randomized.

A bench's ``<Dut>EnvCfg`` adds agent geometry, memory sizes, monitor and
scoreboard enables, and the chosen timing; the env fills each VIP config from
it and the base test's bring-up takes the clock period from it. The SV-UVM
twin is ``ocah_env_cfg``.
"""

from __future__ import annotations

from pyuvm import uvm_object

__all__ = ["OcahEnvCfg"]


class OcahEnvCfg(uvm_object):
    """Clock period and the scoreboard features copied from the test cfg."""

    def __init__(self, name: str = "ocah_env_cfg") -> None:
        super().__init__(name)
        # System clock period the base test's clock generator uses.
        self.clk_period_ns: int = 10
        # Scoreboard features that must compare (copied from the test cfg).
        self.required_features: list[str] = []

    def __str__(self) -> str:
        return f"clk_period_ns={self.clk_period_ns} required_features={self.required_features}"
