# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CTRL placeholder representative.

sep_cpu_ctrl.rdl implements one bit (pka_cg_enable[0:0]); RTL sinks it into an
unused net. This test is the iconic clock-gate vehicle: it proves the
implemented bit stores, and that AES / HMAC / OTBN / SW_DEBUG CSRs still
complete OKAY with the bit 0 and 1. That is decode / stub-const, not a live
per-IP gate -- no bit in this map clocks an IP off.

no_cpu / +skip_fuse_sense. Distinct from sep_crypto_per_ip_reset_isolation_test
(SW_RESET_N isolation) and from the address-map CLOCK_GATE_CTRL storage poke.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_clock_gate_seq import (
    CLOCK_GATE_MASK,
    SepClockGate,
    SepClockGateCfg,
)


@pyuvm.test()
class sep_clock_gate_control_test(sep_base_test):
    """CLOCK_GATE_CTRL storage + stub-const witness reachability."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        cfg = SepClockGateCfg()
        gate = SepClockGate(self)
        self.logger.info("clock-gate placeholder %s", cfg.summary())

        await gate.write_enable(1)
        rb = await gate.read_enable()
        assert rb == (1 & CLOCK_GATE_MASK), (
            f"CHK-STORAGE FAIL: pka_cg_enable wrote 1, read 0x{rb:x}"
        )
        await gate.write_enable(0)
        rb = await gate.read_enable()
        assert rb == 0, f"CHK-STORAGE FAIL: pka_cg_enable wrote 0, read 0x{rb:x}"
        self.logger.info(
            "CHK-STORAGE PASS: CLOCK_GATE_CTRL.pka_cg_enable writes and reads "
            "back 1 then 0 (mask=0x%x)",
            CLOCK_GATE_MASK,
        )

        for enable, name, addr in cfg.cells():
            await gate.write_enable(enable)
            rb = await gate.read_enable()
            assert rb == (enable & CLOCK_GATE_MASK), (
                f"cell enable={enable}: CLOCK_GATE_CTRL read 0x{rb:x}"
            )
            got = await gate.read_witness(addr)
            self.logger.info(
                "CHK-STUB-CONST PASS: enable=%d witness %s @0x%08x OKAY "
                "(rdata=0x%08x) -- pka_cg_enable does not gate this IP",
                enable,
                name,
                addr,
                got & 0xFFFF_FFFF,
            )

        self.logger.info("CHK-RAND-NONE PASS: walked all %d enable x witness cells", cfg.n_cells())
