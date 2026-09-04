# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Environment base.

A bench ``<Dut>Env`` composes: it reads its ``<Dut>EnvCfg`` from ``ConfigDB``
in ``build_phase``, fills one VIP config per agent (handles, geometry,
``name_tag``), builds the VIP environments and agents, the virtual sequencer,
the scoreboard, the subscribers, and the aggregate evidence recorder; it wires
analysis ports in ``connect_phase`` and finalizes evidence once in
``check_phase``. It drives nothing and checks no protocol. The SV-UVM twin is
``ocah_env``.
"""

from __future__ import annotations

from pyuvm import uvm_env

__all__ = ["OcahEnv"]


class OcahEnv(uvm_env):
    """Composition base of every ``<Dut>Env``."""
