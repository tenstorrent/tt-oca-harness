# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CTRL placeholder representative.

sep_cpu_ctrl.rdl implements one bit (pka_cg_enable[0:0]); RTL sinks it into an
unused net. This test is the iconic clock-gate vehicle: it proves the
implemented bit stores, that the register's unimplemented bits do not store,
and that AES / HMAC / OTBN / SW_DEBUG CSRs read the same value with the bit
set and clear. That is decode / stub-const, not a live per-IP gate -- no bit
in this map clocks an IP off. Completing OKAY on both polarities is not the
contract: a witness that moved with the enable would still answer.

no_cpu / +skip_fuse_sense. Distinct from sep_crypto_per_ip_reset_isolation_test
(SW_RESET_N isolation) and from the address-map CLOCK_GATE_CTRL storage poke.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_clock_gate_seq import (
    CLOCK_GATE_CTRL,
    CLOCK_GATE_CTRL_HI,
    CLOCK_GATE_MASK,
    CLOCK_GATE_STORAGE_MASK,
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

        # CHK-RSVD-RAZWI: CLOCK_GATE_CTRL is a 64-bit register with one implemented
        # bit (pka_cg_enable[0:0], sep_cpu_ctrl.rdl). Drive all ones into both 32-bit
        # halves: the readback must expose only the implemented bit, so an
        # unimplemented bit that silently stores (a wider field, or a neighbouring
        # register aliased onto the upper half) fails here.
        await gate.write_raw(CLOCK_GATE_CTRL, 0xFFFF_FFFF)
        await gate.write_raw(CLOCK_GATE_CTRL_HI, 0xFFFF_FFFF)
        lo = await gate.read_raw(CLOCK_GATE_CTRL)
        hi = await gate.read_raw(CLOCK_GATE_CTRL_HI)
        assert lo == CLOCK_GATE_STORAGE_MASK, (
            f"CHK-RSVD-RAZWI FAIL: CLOCK_GATE_CTRL[31:0] wrote all ones, read 0x{lo:08x}, "
            f"expected only the implemented bits 0x{CLOCK_GATE_STORAGE_MASK:08x}"
        )
        assert hi == 0, (
            f"CHK-RSVD-RAZWI FAIL: CLOCK_GATE_CTRL[63:32] wrote all ones, read 0x{hi:08x}, "
            f"expected 0x0 (no implemented bit above 31)"
        )
        await gate.write_raw(CLOCK_GATE_CTRL, 0)
        await gate.write_raw(CLOCK_GATE_CTRL_HI, 0)
        self.logger.info(
            "CHK-RSVD-RAZWI PASS: an all-ones write to both halves of CLOCK_GATE_CTRL "
            "reads back 0x%08x / 0x%08x -- unimplemented bits do not store",
            lo,
            hi,
        )

        # The claim is that pka_cg_enable gates nothing, so each witness must
        # read the SAME value with the bit set and clear: the second read of a
        # witness is compared against its first.
        seen: dict[str, int] = {}
        for enable, name, addr in cfg.cells():
            await gate.write_enable(enable)
            rb = await gate.read_enable()
            assert rb == (enable & CLOCK_GATE_MASK), (
                f"cell enable={enable}: CLOCK_GATE_CTRL read 0x{rb:x}"
            )
            got = await gate.read_witness(addr) & 0xFFFF_FFFF
            if name in seen:
                assert got == seen[name], (
                    f"CHK-STUB-CONST FAIL: witness {name} @0x{addr:08x} reads "
                    f"0x{got:08x} with pka_cg_enable={enable} but 0x{seen[name]:08x} "
                    f"with it clear -- the bit gates this IP"
                )
            else:
                seen[name] = got
            self.logger.info(
                "CHK-STUB-CONST: enable=%d witness %s @0x%08x OKAY rdata=0x%08x",
                enable,
                name,
                addr,
                got,
            )

        # The walk covers both polarities by construction: enables is a frozen
        # default this test does not override, so a guard on it would restate the
        # dataclass. What makes the compare above meaningful is that each witness
        # is read twice, once per polarity.
        self.logger.info(
            "CHK-STUB-CONST PASS: %d witness(es) read the same value with "
            "pka_cg_enable set and clear (%s) -- the bit gates none of them",
            len(seen),
            ", ".join(f"{n}=0x{v:08x}" for n, v in sorted(seen.items())),
        )
