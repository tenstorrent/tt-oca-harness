# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM I3C-to-fabric test over the real SEP_IN AXI ingress port.

Access-port identity: the sequence runs on ``env.sys_axi_agent``, whose driver
declares ``bus_name = "SEP_IN AXI"`` (``env/smc_sys_axi_agent.py``); the SYS_IN
port is a separate agent this test never starts.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i3c_to_fabric_test_seq import smc_i3c_to_fabric_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here as a literal rather than read
# back from the sequence's own counters: a floor derived from them shrinks
# together with a sequence that silently stopped issuing accesses.
# Composition (smc_i3c_to_fabric_test_seq, directed, no polling):
#   7 reads  (CLOCK_GATE_CONTROL, CG set-readback, CG restore-readback,
#             HCI_VERSION, HC_CONTROL entry, HC_CONTROL BUS_ENABLE readback,
#             HC_CONTROL restore-readback)
# + 4 writes (CG set, CG restore, HC_CONTROL BUS_ENABLE, HC_CONTROL restore)
I3C_TO_FABRIC_MIN_CSR_ACCESSES = 11


@pyuvm.test()
class smc_i3c_to_fabric_test(smc_base_test):
    """Run the I3C CSR decode smoke through the SMC SEP_IN AXI input."""

    required_evidence = (
        "CHK-I3C-CLOCK-GATE-RW",
        "CHK-I3C0-HC-CONTROL-BUS-ENABLE",
        "CHK-I3C0-HCI-VERSION",
        "CHK-I3C0-PADS-RESOLVABLE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_to_fabric_test_seq("i3c_to_fabric_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Every unit of the reported access count is measured by an INDEPENDENT
        # observer -- the scoreboard tallies one `sys_axi_checks_seen` per
        # completed SEP_IN AXI item from the analysis port, reads and writes
        # alike -- so no part of the `>= min_csr_accesses` compare is a literal
        # versus a literal. The sequence's own counters are
        # only its internal refactor guard.
        observed_accesses = self.env.scoreboard.sys_axi_checks_seen
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=observed_accesses,
            min_csr_accesses=I3C_TO_FABRIC_MIN_CSR_ACCESSES,
            proxy=True,
            details=(
                "I3C0 CSR-window decode over SEP_IN AXI: HCI_VERSION and "
                "HC_CONTROL value-compared against the vendor SystemRDL "
                "(base_registers.rdl) declared resets, and HC_CONTROL.BUS_ENABLE "
                "written and read back, so the real i3ccore is enabled over the "
                "fabric. I3C0 SCL/SDA external pull-low steps driven with the "
                "core enabled: pad resolvability checked, DUT-drive levels "
                "recorded OBSERVED-ONLY (no positive control exists for those "
                "nets in this TB -- see the CHK/OBSERVED-ONLY lines). No I3C bus "
                "protocol claim."
            ),
        )
