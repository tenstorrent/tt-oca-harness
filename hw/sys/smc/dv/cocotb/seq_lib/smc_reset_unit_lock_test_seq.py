# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reset unit's two write-one-to-set locks over all 32 bits, and their clear.

`RESET_UNIT.SS_CONFIG_LOCK` (0x24) guards `SS_CONFIG` (0x20) and
`RESET_UNIT.SS_COLD_RESET_LOCK` (0x70) guards `SS_COLD_RESET_N` (0x40). Both
are driven over SEP_IN AXI, which reaches the reset unit without a firmware
image (`fw/tests/cold_reset_lock_sanity` exercises the cold-reset lock from
firmware).

Expected values come from the register documentation and the clock/reset
chapter, never from the implementation:

* `hw/sys/smc/regs/gen/adoc/blocks/reset_unit.adoc`: both targets are 31:0 RW
  reset 0x0; both locks are 31:0 RW1S reset 0x0, and once bit i of a lock is
  written, bit i of the guarded register "cannot be written to again".
* `doc/trm/src/register-field-access.adoc`: a 1S bit is set by writing 1, so a
  0-write leaves it.
* `hw/sys/smc/doc/clk_rst.adoc`: the reset-unit register interface and both
  targets are reset by the primary reset, which includes the stable cool reset;
  the locks mask writes to the corresponding target bits.

The bus response to a write that hits locked bits is not specified (SF-014),
so the masked writes accept any response code, log it, and require only that
it is the same code for all 32 writes of a pair.

Per pair the walk locks bit i = 0..31 in turn. Before bit i is locked the
target is written with bit i = 1 for even i and 0 for odd i (`LOCK_PATTERN`);
after it is locked the target is written with every bit inverted from its
readback. The locked bits must then hold `LOCK_PATTERN` (so each newly locked
bit is attempted 1->0 sixteen times and 0->1 sixteen times) while every
unlocked bit must equal the written value, which proves the write reached the
register. A cool-reset pulse with the cold reset inactive must then return both
locks and both targets to 0 and leave the targets writable.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import ALL_ONES_WORD, SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

OKAY = 0
AXI_RESP_CODES = (0, 1, 2, 3)

# (label, target register, lock register, spec citation for the lock field),
# in the order the walk runs.
LOCK_PAIRS = [
    (
        "CONFIG",
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR"),
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR"),
        "reset_unit.adoc SS_CONFIG_LOCK (RW1S, reset 0x0)",
    ),
    (
        "COLD",
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR"),
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR"),
        "reset_unit.adoc SS_COLD_RESET_LOCK (RW1S, reset 0x0)",
    ),
]
TARGET_NAME = {"CONFIG": "SS_CONFIG", "COLD": "SS_COLD_RESET_N"}

#: Bit i of the target before bit i is locked: 1 for even i, 0 for odd i.
LOCK_PATTERN = 0x5555_5555
POST_RESET_WORD = 0xA5A5_A5A5
NBITS = 32

# TB bounds: ceilings for the waits, never the checked quantity. The cool assert
# bound exceeds the 32-sample cool de-glitch window plus the output
# synchronizers; the release bound covers the primary reset release.
COOL_ASSERT_BOUND_REF = 400
COOL_RELEASE_BOUND_REF = 4000
FUSE_SENSE_BOUND_SMC = 200_000
FIRST_ACCESS_BOUND_NS = 10_000

FENCE_TERMS = (
    "SETUP",
    "UNLOCKED",
    "CONFIG-WALK",
    "CONFIG-MASK",
    "COLD-WALK",
    "COLD-MASK",
    "PRIMARY-RESET",
    "POST-RESET-WRITE",
)


def _mask_upto(i: int) -> int:
    """Bits 0..i set."""
    return (1 << (i + 1)) - 1


class smc_reset_unit_lock_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Each RW1S lock accumulates over 32 bits, masks its target, and clears on cool reset."""

    ASSERT_BOUND_REF_CYCLES = COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COOL_RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_reset_unit_lock_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        # (term, sim time in ps, compares) per CHK-NONVAC fence term, in the
        # order the terms completed.
        self.fence: list[tuple[str, int, int]] = []
        self._waits: list[str] = []
        # Per pair: lock readbacks of the walk, and the sim times (ps) of the
        # first lock set and of the last walk readback.
        self._walk_rbs: dict[str, int] = {}
        self._walk_times: dict[str, tuple[int, int]] = {}
        self._cool_times: tuple[int, int] = (0, 0)

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    def _term(self, term: str, count: int, at_ps: int | None = None) -> None:
        assert count > 0, f"fence term {term} completed with 0 compares"
        now = int(get_sim_time("ps")) if at_ps is None else at_ps
        self.fence.append((term, now, count))
        cocotb.log.info("STEP %s: done at %d ps with %d compares", term, now, count)

    def _chk(self, token: str, fmt: str, *args, pair: str | None = None) -> None:
        """Log `token: proof` and record it, keyed per pair when `pair` is given."""
        if pair is None:
            cocotb.log.info(f"{token}: {fmt}", *args)
            self.chk_seen.add(token)
        else:
            cocotb.log.info(f"{token}: [{pair}] {fmt}", *args)
            self.chk_seen.add(f"{token}[{pair}]")

    async def _rd(self, name: str, addr: int, expected: int, timeout_ns: int | None = None) -> int:
        """Read carrying an exact value and an OKAY response expectation."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        item.expected_resp = OKAY
        item.timeout_ns = timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"{name} @ 0x{addr:x}: no read response"
        assert item.resp_code == OKAY, f"{name} @ 0x{addr:x}: RRESP={item.resp_code}"
        got = item.rdata & ALL_ONES_WORD
        assert got == expected, f"{name} @ 0x{addr:x}: read 0x{got:08x} want 0x{expected:08x}"
        return got

    async def _rd_raw(self, name: str, addr: int) -> int:
        """OKAY read whose value the caller derives the next stimulus from."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected_resp = OKAY
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, f"{name} @ 0x{addr:x}: RRESP={item.resp_code}"
        return item.rdata & ALL_ONES_WORD

    async def _wr(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected_resp = OKAY
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, f"{name} @ 0x{addr:x}: BRESP={item.resp_code}"

    async def _wr_masked(self, name: str, addr: int, data: int) -> int:
        """Write hitting locked bits; the response code is measured, not expected (SF-014)."""
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"{name} @ 0x{addr:x}: no write response"
        assert item.resp_code in AXI_RESP_CODES, (
            f"{name} @ 0x{addr:x}: BRESP not a resolvable code ({item.resp_code})"
        )
        return item.resp_code

    # ---- S2 -------------------------------------------------------------
    async def _unlocked(self, label: str, target: int, lock: int) -> int:
        tname = TARGET_NAME[label]
        lk = await self._rd(f"{label}_LOCK_S2", lock, 0)
        await self._wr(f"{tname}_S2_ONES", target, ALL_ONES_WORD)
        ones = await self._rd(f"{tname}_S2_ONES_RB", target, ALL_ONES_WORD)
        await self._wr(f"{tname}_S2_ZERO", target, 0)
        zero = await self._rd(f"{tname}_S2_ZERO_RB", target, 0)
        self._chk(
            f"CHK-LOCK-{label}-UNLOCKED",
            "lock=0x%08x, %s rb 0x%08x/0x%08x",
            lk,
            tname,
            ones,
            zero,
        )
        return 3

    # ---- S3/S4 and S5/S6 --------------------------------------------------
    async def _walk(self, label: str, target: int, lock: int, rdl: str) -> None:
        tname = TARGET_NAME[label]
        walk_rbs = 0
        mask_writes = 0
        dirs = {"1->0": 0, "0->1": 0}
        bresps: list[int] = []
        pre_bresps: set[int] = set()
        target_rb = 0
        t_first_set = t_walk = t_mask = 0
        for i in range(NBITS):
            bit = 1 << i
            locked_before = _mask_upto(i) & ~bit
            locked_after = _mask_upto(i)

            # S4/S6 pre-lock: bit i takes its LOCK_PATTERN value while unlocked.
            pre = (target_rb & ~bit) | (LOCK_PATTERN & bit)
            pre_bresps.add(await self._wr_masked(f"{tname}_PRE_{i}", target, pre))
            exp = (LOCK_PATTERN & locked_before) | (pre & ~locked_before)
            target_rb = await self._rd(f"{tname}_PRE_{i}_RB", target, exp)
            if i == 0:
                self._chk(
                    "CHK-RESET-LOCK-ARM",
                    "the target accepted 0x%08x (read 0x%08x) with the lock at 0x00000000, "
                    "so it is writable before any lock",
                    pre,
                    target_rb,
                    pair=label,
                )

            # S3/S5: write 1<<i, 0, 1<<i; the lock reads mask(0..i) after each.
            await self._wr(f"{label}_LOCK_SET_{i}", lock, bit)
            set_rb = await self._rd(f"{label}_LOCK_SET_{i}_RB", lock, locked_after)
            if i == 0:
                t_first_set = int(get_sim_time("ps"))
            await self._wr(f"{label}_LOCK_ZERO_{i}", lock, 0)
            zero_rb = await self._rd(f"{label}_LOCK_ZERO_{i}_RB", lock, locked_after)
            await self._wr(f"{label}_LOCK_RESET_{i}", lock, bit)
            await self._rd(f"{label}_LOCK_RESET_{i}_RB", lock, locked_after)
            t_walk = int(get_sim_time("ps"))
            walk_rbs += 3
            if i == 1:
                self._chk(
                    "CHK-RESET-LOCK-WOSET",
                    "bit %d set on a 0x%08x write and survived an all-zeroes write "
                    "(0x%08x -> 0x%08x) per %s",
                    i,
                    bit,
                    set_rb,
                    zero_rb,
                    rdl,
                    pair=label,
                )

            # S4/S6 masking: invert every bit of the readback.
            inv = ~target_rb & ALL_ONES_WORD
            bresps.append(await self._wr_masked(f"{tname}_INV_{i}", target, inv))
            exp = (LOCK_PATTERN & locked_after) | (inv & ~locked_after)
            target_rb = await self._rd(f"{tname}_INV_{i}_RB", target, exp)
            t_mask = int(get_sim_time("ps"))
            dirs["1->0" if LOCK_PATTERN & bit else "0->1"] += 1
            mask_writes += 1
            if i == 1:
                self._chk(
                    "CHK-RESET-LOCK-MASKS-WRITE",
                    "one write of 0x%08x left locked bits 0x%08x at 0x%08x while the "
                    "unlocked bits followed it (read 0x%08x, lock=0x%08x)",
                    inv,
                    locked_after,
                    target_rb & locked_after,
                    target_rb,
                    locked_after,
                    pair=label,
                )
        self._term(f"{label}-WALK", walk_rbs, t_walk)
        self._walk_rbs[label] = walk_rbs
        self._walk_times[label] = (t_first_set, t_walk)
        assert mask_writes == NBITS and dirs == {"1->0": 16, "0->1": 16}, (
            f"{label}: {mask_writes} masked writes, directions {dirs}"
        )
        self._chk(
            f"CHK-LOCK-{label}-MASKS",
            "%d writes, locked bits unchanged 1->0 x%d 0->1 x%d, unlocked bits==written "
            "(%s final 0x%08x)",
            mask_writes,
            dirs["1->0"],
            dirs["0->1"],
            tname,
            target_rb,
        )
        codes = sorted(set(bresps))
        assert len(bresps) == NBITS and len(codes) == 1, (
            f"{label}: masked-write BRESP codes {bresps} are not uniform over {NBITS} writes"
        )
        self._chk(
            f"CHK-LOCK-{label}-MASKED-RESP",
            "%d masked writes, BRESP=%d (uniform), LINKED-ISSUE SF-014 (pre-lock writes "
            "BRESP %s, logged only)",
            len(bresps),
            codes[0],
            sorted(pre_bresps),
        )
        self._term(f"{label}-MASK", mask_writes, t_mask)

    # ---- S7 -------------------------------------------------------------
    async def _primary_reset(self, dut) -> tuple[dict[str, int], int]:
        pre: dict[str, int] = {}
        n = 0
        for label, target, lock, _ in LOCK_PAIRS:
            pre[f"{label}_LOCK"] = await self._rd(f"{label}_LOCK_PRE_COOL", lock, ALL_ONES_WORD)
            pre[label] = await self._rd(f"{TARGET_NAME[label]}_PRE_COOL", target, LOCK_PATTERN)
            n += 2
        flr = dut.tb_cfg_flr_pf_active.value
        assert flr.is_resolvable and int(flr) == 0, (
            f"cfg_flr_pf_active_i={flr}; the reset would not be attributable to rst_cool_ni"
        )
        cold_pin = dut.rst_cold_ni.value
        assert cold_pin.is_resolvable and int(cold_pin) == 1, (
            f"rst_cold_ni={cold_pin} before the cool pulse; the cold reset must stay inactive"
        )
        t_cool = int(get_sim_time("ps"))
        await self._send(SmcResetOp.COOL_RST_LO, item_name="lock_cool_rst_lo")
        asserted = await self._wait_state(
            "LOCK_COOL_ASSERTED",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        cold_pin = dut.rst_cold_ni.value
        assert cold_pin.is_resolvable and int(cold_pin) == 1, (
            f"rst_cold_ni={cold_pin} during the cool pulse; the cold reset must stay inactive"
        )
        await self._send(SmcResetOp.COOL_RST_HI, item_name="lock_cool_rst_hi")
        released = await self._wait_released("LOCK_COOL_RELEASED")
        self._cool_times = (t_cool, int(get_sim_time("ps")))

        cycles = 0
        done = False

        async def _count() -> None:
            nonlocal cycles
            while not done:
                await RisingEdge(dut.clk_smc_i)
                cycles += 1

        counter = cocotb.start_soon(_count())
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC)
        t0 = int(get_sim_time("ns"))
        first = await self._rd(
            "CONFIG_LOCK_FIRST_POST_COOL",
            LOCK_PAIRS[0][2],
            0,
            timeout_ns=FIRST_ACCESS_BOUND_NS,
        )
        done = True
        counter.kill()
        self._waits.append(
            f"cool assert: bound={COOL_ASSERT_BOUND_REF} ref cycles, fail path=scoreboard "
            f"WAIT_STATE expiry with last state, matched after {asserted.wait_ref_cycles}"
        )
        self._waits.append(
            f"cool release: bound={COOL_RELEASE_BOUND_REF} ref cycles, fail path=scoreboard "
            f"WAIT_STATE expiry with last state, matched after {released.wait_ref_cycles}"
        )
        self._waits.append(
            f"warm release after cool reset: bound={FUSE_SENSE_BOUND_SMC} smc cycles, fail "
            f"path=AssertionError naming the signal that never rose, released"
        )
        self._waits.append(
            f"first post-reset access: bound={FIRST_ACCESS_BOUND_NS} ns, fail path=driver "
            f"AssertionError naming the address, answered OKAY 0x{first:08x} after "
            f"{int(get_sim_time('ns')) - t0} ns"
        )
        self._term("PRIMARY-RESET", n + 1)
        return pre, cycles

    # ---- S8 -------------------------------------------------------------
    async def _post_reset(self, pre: dict[str, int], first_access: int) -> None:
        n = 0
        for label, target, lock, _ in LOCK_PAIRS:
            tname = TARGET_NAME[label]
            lk = await self._rd(f"{label}_LOCK_POST_COOL", lock, 0)
            tv = await self._rd(f"{tname}_POST_COOL", target, 0)
            await self._wr(f"{tname}_POST_COOL_A5", target, POST_RESET_WORD)
            rb = await self._rd(f"{tname}_POST_COOL_A5_RB", target, POST_RESET_WORD)
            t_clr = int(get_sim_time("ps"))
            n += 3
            set_ps, walk_ps = self._walk_times[label]
            cool_lo_ps, cool_hi_ps = self._cool_times
            walk_rbs = self._walk_rbs[label]
            assert walk_rbs == 3 * NBITS, f"{label}: {walk_rbs} lock readbacks, want {3 * NBITS}"
            self._chk(
                f"CHK-LOCK-{label}-W1S",
                "%d bits, %d/%d readbacks == mask(0..i); lifecycle set@%dps observed "
                "mask(0..31)@%dps cleared by cool pulse %d-%dps checked_cleared lock=0x%08x@%dps",
                NBITS,
                walk_rbs,
                3 * NBITS,
                set_ps,
                walk_ps,
                cool_lo_ps,
                cool_hi_ps,
                lk,
                t_clr,
            )
            self._chk(
                f"CHK-LOCK-{label}-PRIMARY-RESET",
                "lock 0x%08x->0x%08x, %s 0x%08x->0x%08x, rb 0x%08x, first-access=%d smc "
                "cycles from release (measured; SF-016 waived by proxy); lifecycle set@%dps "
                "observed 0x%08x before the pulse, cleared %d-%dps, checked_cleared@%dps",
                pre[f"{label}_LOCK"],
                lk,
                tname,
                pre[label],
                tv,
                rb,
                first_access,
                walk_ps,
                pre[f"{label}_LOCK"],
                cool_lo_ps,
                cool_hi_ps,
                t_clr,
            )
        self._term("POST-RESET-WRITE", n)

    def _check_fence(self) -> None:
        names = tuple(t for t, _, _ in self.fence)
        assert names == FENCE_TERMS, f"fence terms {names}, want {FENCE_TERMS}"
        times = [t for _, t, _ in self.fence]
        assert all(a < b for a, b in zip(times, times[1:])), f"fence out of order: {self.fence}"
        assert all(c > 0 for _, _, c in self.fence), f"zero-count fence term: {self.fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: %s)",
            " < ".join(FENCE_TERMS),
            ", ".join(f"{t}={c}@{ps}ps" for t, ps, c in self.fence),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired: %s",
            len(self._waits),
            " | ".join(self._waits),
        )
        self.chk_seen.update(("CHK-NONVAC", "CHK-TIMEOUT-PATHS"))

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC)
        self._term("SETUP", 1)
        n = 0
        for label, target, lock, _ in LOCK_PAIRS:
            n += await self._unlocked(label, target, lock)
        self._term("UNLOCKED", n)
        for label, target, lock, rdl in LOCK_PAIRS:
            await self._walk(label, target, lock, rdl)
        pre, first_access = await self._primary_reset(dut)
        await self._post_reset(pre, first_access)
        self._check_fence()
