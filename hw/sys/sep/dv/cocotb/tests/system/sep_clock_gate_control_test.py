# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CTRL stores its one implemented bit, and that bit gates no IP.

sep_cpu_ctrl.rdl implements one bit (pka_cg_enable[0:0]); RTL sinks it into an
unused net. This test proves that the implemented bit stores in both directions, also
under an all-ones write to both halves, and that AES / HMAC / OTBN / SW_DEBUG
CSRs read the same value with the bit set and clear. That is decode /
stub-const, not a live per-IP gate -- no bit in this map clocks an IP off.
Completing OKAY on both polarities is not the contract: a witness that moved
with the enable would still answer.

Every CLOCK_GATE_CTRL readback after an enable write reads both halves of the
64-bit register without a mask. The graded value is the one specified field,
pka_cg_enable (regs/gen/adoc/blocks/sep_cpu_ctrl.adoc:92, RW, reset 0x0), which
must equal the written bit. Bits 63:1 are Reserved with no stated reset, access
or read value (sep_cpu_ctrl.adoc:91), so every readback, the one after the
all-ones write included, logs them as an OBS value only.

FCOV: every check runs first with the graded window closed. Only after all of
them pass does the leaf open the window (owner FcovOwnSepClockGateControlTest)
for two more graded CHK-STORAGE steps, write 0 then write 1, each in its own
window. They feed sep_cpu_ctrl_reg_cg.cp_clock_gate_ctrl: the next read of the
lower half after a write returns the written pka_cg_enable bit. The lower-half
read is the last read of a step, and the sample condition is the step's check,
so the bin samples only on a step whose check passes.

Run mode: no_cpu with +skip_fuse_sense. Distinct from
sep_crypto_per_ip_reset_isolation_test (SW_RESET_N isolation) and from
sep_address_map_test (CLOCK_GATE_CTRL storage poke in sep_address_map_seq).
"""

from __future__ import annotations

import pyuvm
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from seq_lib.sep_clock_gate_seq import (
    CLOCK_GATE_CTRL,
    CLOCK_GATE_CTRL_HI,
    CLOCK_GATE_MASK,
    SepClockGate,
    SepClockGateCfg,
)

TEST = "sep_clock_gate_control_test"
# One 32-bit AXI data word.
_WORD_MASK = 0xFFFF_FFFF


@pyuvm.test()
class sep_clock_gate_control_test(sep_base_test):
    """The implemented bit stores in both directions, and witness CSRs ignore it."""

    def _grade(self, ok: bool, msg: str) -> None:
        """Close the graded window first (if open), then raise, on a failed check."""
        if not ok:
            close_graded_window(self.logger)
            raise AssertionError(msg)

    async def _read_back(self, gate: SepClockGate, chk: str, enable: int) -> tuple[int, int]:
        """Read both halves after a write of ``enable``; grade pka_cg_enable, log the rest."""
        want = enable & CLOCK_GATE_MASK
        hi = await gate.read_raw(CLOCK_GATE_CTRL_HI)
        lo = await gate.read_raw(CLOCK_GATE_CTRL)
        self.logger.info(
            "OBS-CG-RSVD: %s wrote %d, Reserved bits read 0x%08x (lower half) / 0x%08x "
            "(upper half); no stated value, not graded",
            chk,
            enable,
            lo & ~CLOCK_GATE_MASK & _WORD_MASK,
            hi,
        )
        self._grade(
            (lo & CLOCK_GATE_MASK) == want,
            f"{chk} FAIL: pka_cg_enable wrote {enable}, read 0x{lo & CLOCK_GATE_MASK:x} "
            f"(raw 0x{lo:08x} / 0x{hi:08x})",
        )
        return lo, hi

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        cfg = SepClockGateCfg()
        gate = SepClockGate(self)
        self.logger.info("clock-gate placeholder %s", cfg.summary())

        try:
            await self._scenario(cfg, gate)
            # Graded steps: the window opens only after every check above passed.
            for enable in (0, 1):
                await self._graded_storage_step(gate, enable)
        finally:
            close_graded_window(self.logger)

    async def _graded_storage_step(self, gate: SepClockGate, enable: int) -> None:
        """One CHK-STORAGE step (write, then both halves) inside its own window."""
        open_graded_window(TEST, self.logger)
        await gate.write_enable(enable)
        lo, hi = await self._read_back(gate, "CHK-STORAGE", enable)
        close_graded_window(self.logger)
        self.logger.info(
            "CHK-STORAGE PASS: graded step wrote pka_cg_enable=%d read %d (raw 0x%08x / 0x%08x)",
            enable,
            lo & CLOCK_GATE_MASK,
            lo,
            hi,
        )

    async def _scenario(self, cfg: SepClockGateCfg, gate: SepClockGate) -> None:
        # CHK-STORAGE: write 1 then 0 to pka_cg_enable and read both halves back
        # unmasked; the field must store in both directions.
        await gate.write_enable(1)
        lo1, hi1 = await self._read_back(gate, "CHK-STORAGE", 1)
        await gate.write_enable(0)
        lo0, hi0 = await self._read_back(gate, "CHK-STORAGE", 0)
        self.logger.info(
            "CHK-STORAGE PASS: CLOCK_GATE_CTRL.pka_cg_enable wrote 1 read %d, wrote 0 read %d "
            "(raw lower / upper half 0x%08x / 0x%08x, 0x%08x / 0x%08x; field mask=0x%x)",
            lo1 & CLOCK_GATE_MASK,
            lo0 & CLOCK_GATE_MASK,
            lo1,
            hi1,
            lo0,
            hi0,
            CLOCK_GATE_MASK,
        )

        # CHK-STORAGE, all-ones leg: drive all ones into both 32-bit halves. The
        # pka_cg_enable field must read 1. The Reserved bits 63:1 have no stated
        # access or read value, so their readback is logged, not graded.
        resp = {}
        for half, addr in (("lower", CLOCK_GATE_CTRL), ("upper", CLOCK_GATE_CTRL_HI)):
            try:
                await gate.write_raw(addr, 0xFFFF_FFFF)
                resp[half] = "OKAY"
            except AssertionError:
                resp[half] = "not_OKAY"
        wr = (
            f"lower=0x{CLOCK_GATE_CTRL:08x} resp={resp['lower']} "
            f"upper=0x{CLOCK_GATE_CTRL_HI:08x} resp={resp['upper']} wdata=0xffffffff"
        )
        # Same text as SepChkLog.ctrl(): the all-ones leg of CHK-STORAGE claims a
        # write to both halves, so a half whose write does not answer OKAY fails
        # the leaf.
        if set(resp.values()) != {"OKAY"}:
            self.logger.error("CTRL-MISSING CG-ALLONES-WR: %s", wr)
            self._grade(False, f"CTRL-MISSING CG-ALLONES-WR: {wr}")
        self.logger.info("CTRL-CG-ALLONES-WR seen: %s", wr)
        hi = await gate.read_raw(CLOCK_GATE_CTRL_HI)
        lo = await gate.read_raw(CLOCK_GATE_CTRL)
        self.logger.info(
            "OBS-CG-RSVD-ALLONES: all-ones write to both halves, Reserved bits read 0x%08x "
            "(lower half) / 0x%08x (upper half); no stated value, not graded",
            lo & ~CLOCK_GATE_MASK & _WORD_MASK,
            hi,
        )
        self._grade(
            (lo & CLOCK_GATE_MASK) == CLOCK_GATE_MASK,
            f"CHK-STORAGE FAIL: all-ones write, pka_cg_enable read "
            f"0x{lo & CLOCK_GATE_MASK:x}, expected 0x{CLOCK_GATE_MASK:x} "
            f"(raw 0x{lo:08x} / 0x{hi:08x})",
        )
        self.logger.info(
            "CHK-STORAGE PASS: all-ones write to both halves, pka_cg_enable read 0x%x "
            "(raw 0x%08x / 0x%08x)",
            lo & CLOCK_GATE_MASK,
            lo,
            hi,
        )
        await gate.write_raw(CLOCK_GATE_CTRL, 0)
        await gate.write_raw(CLOCK_GATE_CTRL_HI, 0)

        # A change of pka_cg_enable must leave each witness unchanged: each
        # witness must read the SAME value with the bit set and clear, so the
        # second read of a witness is compared against its first. CHK-CELL-STORAGE grades the
        # CLOCK_GATE_CTRL readback of each cell, which is also the positive probe
        # that the enable really changed between the two witness reads.
        seen: dict[str, int] = {}
        for enable, name, addr in cfg.cells():
            await gate.write_enable(enable)
            lo, hi = await self._read_back(gate, "CHK-CELL-STORAGE", enable)
            self.logger.info(
                "CHK-CELL-STORAGE PASS: enable=%d pka_cg_enable read %d (raw 0x%08x / 0x%08x)",
                enable,
                lo & CLOCK_GATE_MASK,
                lo,
                hi,
            )
            got = await gate.read_witness(addr) & _WORD_MASK
            if name in seen:
                self._grade(
                    got == seen[name],
                    f"CHK-STUB-CONST FAIL: witness {name} @0x{addr:08x} reads "
                    f"0x{got:08x} with pka_cg_enable={enable} (CLOCK_GATE_CTRL 0x{lo:08x}) "
                    f"but 0x{seen[name]:08x} with it clear -- the bit gates this IP",
                )
            else:
                seen[name] = got
            self.logger.info(
                "CHK-STUB-CONST: enable=%d CLOCK_GATE_CTRL=0x%08x witness %s @0x%08x "
                "OKAY rdata=0x%08x",
                enable,
                lo,
                name,
                addr,
                got,
            )

        # Each witness is read twice, once per polarity; enables is a frozen default
        # this test does not override.
        self.logger.info(
            "CHK-STUB-CONST PASS: %d witness(es) read the same value with "
            "pka_cg_enable set and clear (%s) -- the bit gates none of them",
            len(seen),
            ", ".join(f"{n}=0x{v:08x}" for n, v in sorted(seen.items())),
        )
