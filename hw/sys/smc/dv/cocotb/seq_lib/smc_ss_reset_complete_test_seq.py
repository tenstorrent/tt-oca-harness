# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ss_reset_complete_i to SS_RESET_COMPLETE on every bit; SW SS_WARM_RESET_N to ss_reset_ctrl_o[0]."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import ALL_ONES_WORD, SmcCsrSeq

SS_COMPLETE = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_RESET_COMPLETE_BASE_ADDR")
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

# SS_WARM_RESET_N's reset value comes from the generated reset_unit header, the
# same accessor smc_jtag_reset_ctrl_test_seq uses, so a narrowing of the field in
# the RDL rots this expectation instead of leaving a stale golden behind.
SS_WARM_RESET_VALUE = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
SS_COMPLETE_ALL_ONE = 0xFFFFFFFF
SS_COMPLETE_DROP_0_31 = 0x7FFFFFFE
_CSR_BOUND = 64
_PIN_BOUND = 64
# Scratch RW pattern. SCRATCH_COLD_WARM_0 is `scratch.rdl` SCRATCH[0]
# (sw=rw, hw=na, reset 0x0) in the misc_wrap cold+warm scratch bank.
_SCRATCH_PAT = 0xA5A5_5A5A
_SCRATCH_RESET = 0x0

# Vector legs of testcase contract SMC_COV_B1_004 (S1-S6). Every expected value
# is the driven input vector: reset_unit.adoc SS_RESET_COMPLETE is R, each bit
# the synchronised live value of its input, not latched.
SS_COMPLETE_ALL_ZERO = 0x0000_0000
WALK_BITS = 32
WALKING_ONES = tuple(1 << b for b in range(WALK_BITS))
PATTERN_VECTORS = (0x0000_0000, ALL_ONES_WORD, 0x5555_5555, 0xAAAA_AAAA, *WALKING_ONES)
RO_HOLD_VECTOR = 0xA5A5_A5A5
RO_WRITE_WORDS = (ALL_ONES_WORD, 0x0000_0000)
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
FENCE_TERMS = (
    "ALL-ZERO",
    *(t for b in range(WALK_BITS) for t in (f"ASSERT-{b}", f"RELEASE-{b}")),
    "PATTERNS",
    "RO-WRITE",
)


class smc_ss_reset_complete_test_seq(SmcCsrSeq):
    """Pin 1→drop bits 0/31→1 on CSR; SW warm bit 0 1→0→1 on SS0 pin."""

    def __init__(self, name: str = "smc_ss_reset_complete_test_seq") -> None:
        super().__init__(name)
        # Values captured for the evidence tokens and the testcase-level gate.
        #   * `idle_csr` / `drop_csr` / `restore_csr` come from `_await_csr`,
        #     which raises unless the value matches, so they hold the wanted
        #     constants; the fail-capable content is `_await_csr`'s expiry path.
        #   * `warm_pins` likewise comes from `_await_warm_pin`.
        #   * `warm_csr` holds three plain `csr_read` words with NO `expected=`;
        #     this sequence asserts only bit 0 of the asserted/released reads, so
        #     a full-word compare at testcase level covers the other 31 bits
        #     ([NO-ALWAYS-PASS-CHECKER]).
        self.idle_csr: int | None = None
        self.drop_csr: int | None = None
        self.restore_csr: int | None = None
        self.warm_csr: tuple[int, int, int] | None = None
        self.warm_pins: tuple[int, int, int] | None = None
        # label -> polls/cycles the matching wait actually consumed. This is the
        # varying measured quantity the tokens report.
        self.polls: dict[str, int] = {}
        # (term, sim time in ps, compares) per CHK-NONVAC fence term, in the
        # order the terms completed.
        self.fence: list[tuple[str, int, int]] = []
        # (label, bound, polls consumed, driven vector, last readback) per
        # bounded vector poll of S1-S4.
        self.waits: list[tuple[str, int, int, int, int]] = []
        self.assert_polls: list[int] = []
        self.release_polls: list[int] = []
        self.patterns_matched = 0
        self.ro_readbacks: list[int] = []
        self.ro_bresps: list[int] = []

    async def _await_csr(self, want: int, label: str) -> int:
        """Poll until the CSR mirrors `want`, or raise on expiry.

        NOTE ON WHAT THIS PROVES: the returned value can only ever BE `want` --
        every other outcome raises. So a token that prints the return value is
        printing a constant. The fail-capable content is the expiry path, and
        the varying measured quantity is the poll count, recorded in
        `self.polls[label]` and reported in the evidence tokens.
        """
        last = None
        for polls in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_COMPLETE", SS_COMPLETE)
            if last == want:
                self.polls[label] = polls
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: SS_RESET_COMPLETE last=0x{last:x} want=0x{want:x} after {_CSR_BOUND} polls"
        )

    def _term(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} completed with 0 compares"
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count))
        cocotb.log.info("STEP %s: done at %d ps with %d compares", term, now, count)

    async def _drive_and_poll(self, dut, vector: int, label: str, prior: int | None = None) -> int:
        """Drive the reset-complete inputs to `vector` and poll until the CSR equals it.

        With `prior` given, every readback before the match must equal `prior`:
        a single-bit walk step has no other legal intermediate value, so any
        other word fails at once. Returns the polls consumed; expiry fails with
        the driven vector and the last readback.
        """
        dut.tb_ss_reset_complete.value = vector
        last = None
        for polls in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_COMPLETE", SS_COMPLETE) & ALL_ONES_WORD
            if last == vector:
                self.waits.append((label, _CSR_BOUND, polls, vector, last))
                return polls
            assert prior is None or last == prior, (
                f"{label}: SS_RESET_COMPLETE read 0x{last:08x} while the driven vector "
                f"moved 0x{prior:08x} -> 0x{vector:08x} (a bit other than the walked one changed)"
            )
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label}: SS_RESET_COMPLETE last=0x{last:08x} driven=0x{vector:08x} "
            f"after {_CSR_BOUND} polls"
        )

    async def _ro_write(self, label: str, data: int) -> int:
        """Write SS_RESET_COMPLETE and return BRESP; any code is accepted, none compared."""
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = SS_COMPLETE
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: write of 0x{data:08x} got no BRESP"
        return item.resp_code

    async def _vector_legs(self, dut) -> None:
        """Contract SMC_COV_B1_004 S1-S6 on the 32 reset-complete inputs."""
        await self._drive_and_poll(dut, SS_COMPLETE_ALL_ZERO, "S1_ALL_ZERO")
        self._term("ALL-ZERO", 1)

        for b, word in enumerate(WALKING_ONES):
            self.assert_polls.append(
                await self._drive_and_poll(dut, word, f"S2_ASSERT_{b}", SS_COMPLETE_ALL_ZERO)
            )
            self._term(f"ASSERT-{b}", 1)
            self.release_polls.append(
                await self._drive_and_poll(dut, SS_COMPLETE_ALL_ZERO, f"S3_RELEASE_{b}", word)
            )
            self._term(f"RELEASE-{b}", 1)
        assert len(self.assert_polls) == len(self.release_polls) == WALK_BITS
        cocotb.log.info(
            "CHK-SSRC-ASSERT: %d/%d bits read exactly 1<<i, polls=%d..%d "
            "(measured, no spec latency; LINKED-ISSUE SF-023)",
            len(self.assert_polls),
            WALK_BITS,
            min(self.assert_polls),
            max(self.assert_polls),
        )
        cocotb.log.info(
            "CHK-SSRC-RELEASE: %d/%d bits 1->0, register 0x%08x after each release, polls=%d..%d",
            len(self.release_polls),
            WALK_BITS,
            SS_COMPLETE_ALL_ZERO,
            min(self.release_polls),
            max(self.release_polls),
        )

        for word in PATTERN_VECTORS:
            await self._drive_and_poll(dut, word, f"S4_PATTERN_{word:08x}")
            self.patterns_matched += 1
        assert self.patterns_matched == len(PATTERN_VECTORS) == 36
        cocotb.log.info(
            "CHK-SSRC-PATTERNS: %d/%d driven vectors read back exactly "
            "(0x00000000, 0xFFFFFFFF, 0x55555555, 0xAAAAAAAA, 32 walking ones)",
            self.patterns_matched,
            len(PATTERN_VECTORS),
        )
        self._term("PATTERNS", self.patterns_matched)

        await self._drive_and_poll(dut, RO_HOLD_VECTOR, "S5_RO_HOLD")
        for word in RO_WRITE_WORDS:
            self.ro_bresps.append(await self._ro_write(f"S5_RO_WRITE_{word:08x}", word))
            rb = await self.csr_read(
                f"S5_RO_WRITE_{word:08x}_RB", SS_COMPLETE, expected=RO_HOLD_VECTOR
            )
            rb &= ALL_ONES_WORD
            assert rb == RO_HOLD_VECTOR, (
                f"SS_RESET_COMPLETE read 0x{rb:08x} after a 0x{word:08x} write, "
                f"want the input vector 0x{RO_HOLD_VECTOR:08x}"
            )
            self.ro_readbacks.append(rb)
        cocotb.log.info(
            "CHK-SSRC-RO-WRITE: rb after 0x%08x write=0x%08x, after 0x%08x write=0x%08x, "
            "BRESP=%s/%s (measured, not compared; LINKED-ISSUE SF-024)",
            RO_WRITE_WORDS[0],
            self.ro_readbacks[0],
            RO_WRITE_WORDS[1],
            self.ro_readbacks[1],
            RESP_NAMES.get(self.ro_bresps[0], str(self.ro_bresps[0])),
            RESP_NAMES.get(self.ro_bresps[1], str(self.ro_bresps[1])),
        )
        self._term("RO-WRITE", len(self.ro_readbacks))

        terms = tuple(t for t, _, _ in self.fence)
        assert terms == FENCE_TERMS, f"fence terms {terms}, want {FENCE_TERMS}"
        times = [t for _, t, _ in self.fence]
        assert all(a < b for a, b in zip(times, times[1:])), f"fence times not increasing: {times}"
        assert all(n > 0 for _, _, n in self.fence)
        fence = {t: (ps, n) for t, ps, n in self.fence}
        walk = " ".join(
            f"A{b}@{fence[f'ASSERT-{b}'][0]}/R{b}@{fence[f'RELEASE-{b}'][0]}"
            for b in range(WALK_BITS)
        )
        cocotb.log.info(
            "CHK-NONVAC: ALL-ZERO(n=%d)@%d < ASSERT-i < RELEASE-i (x%d, n=1 each: %s) "
            "< PATTERNS(n=%d)@%d < RO-WRITE(n=%d)@%d ps",
            fence["ALL-ZERO"][1],
            fence["ALL-ZERO"][0],
            WALK_BITS,
            walk,
            fence["PATTERNS"][1],
            fence["PATTERNS"][0],
            fence["RO-WRITE"][1],
            fence["RO-WRITE"][0],
        )

        expired = sum(1 for _, bound, polls, _, _ in self.waits if polls >= bound)
        assert expired == 0
        per_wait = " ".join(
            f"{label}={polls}/{bound}:0x{last:08x}" for label, bound, polls, _, last in self.waits
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait "
            "(expiry raises with driven vector and last readback), %d expired: %s",
            len(self.waits),
            expired,
            per_wait,
        )

    def _warm_pin(self, dut) -> int:
        pin = dut.tb_ss0_warm_reset_n
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on tb_ss0_warm_reset_n: {pin.value}")
        return int(pin.value) & 1

    async def _await_warm_pin(self, dut, want: int, label: str) -> int:
        """Wait for the pin to reach `want`, or raise on expiry.

        Same caveat as `_await_csr`: the return value is `want` by construction,
        so it is NOT an independently checked measurement. The cycle count is,
        and it is recorded in `self.polls[label]`.
        """
        last = -1
        for cycles in range(_PIN_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = self._warm_pin(dut)
            if last == want:
                self.polls[label] = cycles
                return last
        raise AssertionError(f"{label}: ss0 warm_reset_n stuck {last} want {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ss_reset_complete"), "tb_ss_reset_complete missing"
        assert hasattr(dut, "tb_ss0_warm_reset_n"), "tb_ss0_warm_reset_n missing"

        dut.tb_ss_reset_complete.value = SS_COMPLETE_ALL_ONE
        self.idle_csr = await self._await_csr(SS_COMPLETE_ALL_ONE, "IDLE")
        cocotb.log.info("CHK-SS-COMPLETE-IDLE: CSR=0x%x pin=all-1", self.idle_csr)

        dut.tb_ss_reset_complete.value = SS_COMPLETE_DROP_0_31
        self.drop_csr = await self._await_csr(SS_COMPLETE_DROP_0_31, "DROP")
        cocotb.log.info(
            "CHK-SS-COMPLETE-DROP: CSR=0x%x pin=0x%x bits 0 and 31 low",
            self.drop_csr,
            SS_COMPLETE_DROP_0_31,
        )

        dut.tb_ss_reset_complete.value = SS_COMPLETE_ALL_ONE
        self.restore_csr = await self._await_csr(SS_COMPLETE_ALL_ONE, "RESTORE")
        cocotb.log.info("CHK-SS-COMPLETE-RESTORE: CSR=0x%x pin=all-1", self.restore_csr)

        warm0 = await self.csr_read("SS_WARM_IDLE", SS_WARM)
        assert warm0 == SS_WARM_RESET_VALUE, (
            f"SS_WARM_RESET_N idle 0x{warm0:x} want the generated reset value "
            f"0x{SS_WARM_RESET_VALUE:x}"
        )
        pin0 = await self._await_warm_pin(dut, 1, "WARM_IDLE")
        await self.csr_write("SS_WARM_SS0_LO", SS_WARM, SS_WARM_RESET_VALUE & ~0x1)
        pin1 = await self._await_warm_pin(dut, 0, "WARM_ASSERT")
        warm1 = await self.csr_read("SS_WARM_ASSERTED", SS_WARM)
        assert (warm1 & 0x1) == 0, f"SS_WARM bit0 stuck 1: 0x{warm1:x}"
        await self.csr_write("SS_WARM_SS0_HI", SS_WARM, SS_WARM_RESET_VALUE)
        pin2 = await self._await_warm_pin(dut, 1, "WARM_RELEASE")
        warm2 = await self.csr_read("SS_WARM_RELEASED", SS_WARM)
        assert (warm2 & 0x1) == 1, f"SS_WARM bit0 stuck 0: 0x{warm2:x}"
        self.warm_csr = (warm0, warm1, warm2)
        self.warm_pins = (pin0, pin1, pin2)
        cocotb.log.info(
            "CHK-SS-WARM-SS0: pin %d→%d→%d (these are the WANTED values by "
            "construction -- _await_warm_pin raises unless matched; the "
            "fail-capable content is the bounded wait and the CSR compares) "
            "reached in %s/%s/%s clk_smc_i cycles; CSR=0x%x→0x%x→0x%x read "
            "without expected= and compared here and at testcase level",
            pin0,
            pin1,
            pin2,
            self.polls.get("WARM_IDLE"),
            self.polls.get("WARM_ASSERT"),
            self.polls.get("WARM_RELEASE"),
            warm0,
            warm1,
            warm2,
        )
        # SCRATCH_COLD_WARM_0 read/write/restore. This scenario drives no SMC
        # warm or cool reset -- the SW SS_WARM_RESET_N bit exercised above is
        # subsystem 0's OUTBOUND pin, not the SMC warm domain -- so no claim is
        # made here about reset clearing this register (that property is proven
        # by smc_jtag_reset_ctrl_test, which causes a real cool reset). What is
        # proven is that the register is a live sw=rw scratch cell.
        await self.csr_write("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, _SCRATCH_PAT)
        wrote = await self.csr_read(
            "SCRATCH_COLD_WARM_0_RB", SCRATCH_COLD_WARM_0, expected=_SCRATCH_PAT
        )
        await self.csr_write("SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0, _SCRATCH_RESET)
        restored = await self.csr_read(
            "SCRATCH_COLD_WARM_0_RESTORE_RB",
            SCRATCH_COLD_WARM_0,
            expected=_SCRATCH_RESET,
        )
        cocotb.log.info(
            "CHK-SS-COMPLETE-SCRATCH-RW: SCRATCH_COLD_WARM_0 took 0x%08x then "
            "0x%08x on write/readback (no SMC warm or cool reset occurs in this "
            "scenario, so no reset-clearing claim is made)",
            wrote,
            restored,
        )
        await self._vector_legs(dut)
