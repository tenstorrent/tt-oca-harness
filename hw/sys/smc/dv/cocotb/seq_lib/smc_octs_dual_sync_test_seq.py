# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-5 OCTS dual-chiplet sync: SECONDARY inject then PRIMARY outbound.

The DUT PRIMARY drives OCTS sync/credit pads and the master BFM tracks the
SECONDARY side. This sequence:

  1. Strap SECONDARY, check STATUS.MODE, then write TIMER_START with PRESET
     0x1_0000_1000 and check COUNT, RUNNING, the START readback and the
     sync-load pad stay idle (the write has no effect in SECONDARY mode).
  2. Inject ordered sync then credit on pad2core[55/56], hard-gate COUNT /
     STATUS.RUNNING.
  3. Strap PRIMARY, TIMER_START, hard-gate rising edges on DUT pad observe,
     STATUS.RUNNING after the start, and measure each sync-load pulse width.

Expected values: system_timer_octs.adoc (TIMER_START, STATUS, TIMER_COUNT_*
reset values) and doc/trm/src/register-field-access.adoc (1P self-clears).

Secondary-before-primary avoids RTL ExpectedCountValid_A when switching
modes with a live COUNT (primary count >> expected).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_octs_sync_bfm import (
    count_rising_edges,
    drive_secondary_sync_then_credits,
)

_OCTS_TIMER_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
_OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
_OCTS_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
_OCTS_PRESET_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR")
_OCTS_PRESET_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR")
_OCTS_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
_OCTS_COUNT_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR")
_OCTS_TIMER_GPIO_ENABLE = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR")

# CTRL: CREDIT_VAL=0x10, PULSE_WIDTH=0x02, STEP=0x01.
_OCTS_CTRL_VAL = 0x0001_0210
_OCTS_CREDIT_VAL = 0x10
_OCTS_PULSE_WIDTH = 0x02
_OCTS_PRESET_VAL = 0x1000
_OCTS_STATUS_MODE = 0x1
_OCTS_STATUS_RUNNING = 0x10
_OCTS_PRIMARY_WAIT = 256
# COUNT lands a few ticks past PRESET by the time the reload read returns.
_OCTS_RELOAD_SLACK = 0x100
# STEP=1, so the advance over the edge-count window is bounded by it.
_OCTS_MAX_ADVANCE = 4 * _OCTS_PRIMARY_WAIT
_OCTS_SEC_PRESET_HI = 0x1
_OKAY = 0

_FENCE = (
    ("S1", "SECONDARY-SETUP"),
    ("S2", "MODE"),
    ("S3", "SECONDARY-START"),
    ("S4", "EXISTING-SECONDARY"),
    ("S5", "PRIMARY-START"),
)


async def _high_times(signal, clk, max_cycles: int) -> tuple[list[int], int, int]:
    """High run lengths of ``signal`` in ``clk`` cycles over ``max_cycles`` cycles.

    Returns the completed runs, the length of a run still high at the window
    end and the number of unresolvable samples.
    """
    runs: list[int] = []
    run = 0
    unresolved = 0
    for _ in range(max_cycles):
        await RisingEdge(clk)
        if not signal.value.is_resolvable:
            unresolved += 1
            continue
        if int(signal.value):
            run += 1
        elif run:
            runs.append(run)
            run = 0
    return runs, run, unresolved


class smc_octs_dual_sync_test_seq(SmcCsrSeq):
    """OCTS dual-chiplet sync hard-gates (secondary inject + primary pads)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int, int]] = []
        self._last_access = "none"
        self._expired = 0
        self._sec_sync_edges = -1

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps")), self.accesses))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.add(chk_id)

    async def _access(self, item: SmcSysAxiItem, what: str) -> None:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        if item.timed_out:
            self._expired += 1
        self._last_access = f"{what} resp={item.resp_code}"
        if not item.allow_error:
            assert item.resp_code == _OKAY, f"OCTS access not OKAY: {self._last_access}"

    async def csr_read(
        self, name: str, addr: int, expected: int | None = None, length: int = 4, prot: int = 0
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        item.prot = prot
        await self._access(item, f"read {name}@0x{addr:08x}")
        self._last_access += f" rdata=0x{item.rdata:x}"
        return item.rdata

    async def csr_write(
        self,
        name: str,
        addr: int,
        data: int,
        length: int = 4,
        prot: int = 0,
        allow_error: bool = False,
    ) -> int | None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.prot = prot
        item.allow_error = allow_error
        await self._access(item, f"write {name}@0x{addr:08x} wdata=0x{data:x}")
        return item.resp_code

    async def _secondary_start(self, clk) -> None:
        """S3: TIMER_START = 1 under the SECONDARY strap has no effect."""
        dut = cocotb.top
        await self.csr_write("OCTS_PRESET_LO_SEC", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI_SEC", _OCTS_PRESET_HI, _OCTS_SEC_PRESET_HI)
        count_before = await self._read_count()

        edge_task = cocotb.start_soon(
            count_rising_edges(dut.tb_octs_sync_load_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        # The response to a SECONDARY START write is not stated (SF-028); it is
        # measured and logged, not compared.
        bresp = await self.csr_write("OCTS_TIMER_START_SEC", _OCTS_TIMER_START, 1, allow_error=True)
        count_after = await self._read_count()
        status = await self.csr_read("OCTS_STATUS_SEC_START", _OCTS_STATUS)
        start_rb = await self.csr_read("OCTS_TIMER_START_SEC_RB", _OCTS_TIMER_START)
        sync_edges = await edge_task
        self._sec_sync_edges = sync_edges

        assert count_before == 0, (
            f"OCTS COUNT before the SECONDARY TIMER_START is 0x{count_before:x}, expected 0"
        )
        assert count_after == 0, (
            f"OCTS SECONDARY TIMER_START changed COUNT 0x{count_before:x} -> "
            f"0x{count_after:x}; in SECONDARY mode the write has no effect"
        )
        assert (status & _OCTS_STATUS_RUNNING) == 0, (
            f"OCTS STATUS.RUNNING set after a SECONDARY TIMER_START (STATUS=0x{status:08x})"
        )
        assert (start_rb & 0x1) == 0, (
            f"OCTS TIMER_START.START reads 1 after the write (1P self-clears): 0x{start_rb:08x}"
        )
        assert sync_edges == 0, (
            f"OCTS SECONDARY TIMER_START drove {sync_edges} sync_load rising edges on pad55 "
            f"over {_OCTS_PRIMARY_WAIT} clk_smc_i, expected 0"
        )

        await self.csr_write("OCTS_PRESET_HI_SEC_RESTORE", _OCTS_PRESET_HI, 0)
        preset_hi = await self.csr_read("OCTS_PRESET_HI_SEC_RESTORE_RB", _OCTS_PRESET_HI)
        assert preset_hi == 0, f"OCTS TIMER_PRESET_HI reads 0x{preset_hi:x} after writing 0"
        self._chk(
            "CHK-OCTS-SEC-START-IGNORED",
            f"PRESET 0x{_OCTS_SEC_PRESET_HI:x}_{_OCTS_PRESET_VAL:08x}, COUNT 0x{count_before:x}"
            f"->0x{count_after:x}, RUNNING=0 (STATUS=0x{status:08x}), TIMER_START rb="
            f"{start_rb & 0x1}, sync_load edges={sync_edges} over {_OCTS_PRIMARY_WAIT} "
            f"clk_smc_i, BRESP={bresp} (LINKED-ISSUE SF-028, logged), PRESET_HI restored "
            f"0x{preset_hi:x}",
        )
        self._stamp("S3")

    def _timeout_paths(self, windows: list[tuple[str, str]]) -> None:
        assert self._expired == 0, f"{self._expired} SEP_IN accesses expired"
        waits = [
            (
                f"SEP_IN access x{self.accesses}",
                f"{self.cfg.axi_timeout_ns}ns each(enforced-by=env/smc_sys_axi_agent.py,"
                "on-expiry=AssertionError)",
                self._last_access,
            )
        ] + [
            (name, f"{_OCTS_PRIMARY_WAIT}clk_smc_i fixed observation window", last)
            for name, last in windows
        ]
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits: "
            + "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits)
            + f"; {self._expired} expired",
        )

    def _fence(self) -> None:
        steps = tuple(s for s, _, _ in self._stamps)
        assert steps == tuple(s for s, _ in _FENCE), f"OCTS fence step order {steps}"
        times = [t for _, t, _ in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"OCTS stamps not increasing {times}"
        marks = [0] + [a for _, _, a in self._stamps]
        counts = [b - a for a, b in zip(marks, marks[1:])]
        assert all(c > 0 for c in counts), f"OCTS fence term without an access: {counts}"
        terms = dict(_FENCE)
        self._chk(
            "CHK-NONVAC",
            "ordered fence "
            + " < ".join(terms[s] for s in steps)
            + "; "
            + ", ".join(f"{terms[s]}={t}ps/{c}acc" for (s, t, _), c in zip(self._stamps, counts))
            + "; checker lines "
            + ",".join(sorted(self.chk_seen)),
        )

    async def _read_count(self) -> int:
        lo = await self.csr_read("OCTS_COUNT_LO", _OCTS_COUNT_LO)
        hi = await self.csr_read("OCTS_COUNT_HI", _OCTS_COUNT_HI)
        return (hi << 32) | lo

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        assert hasattr(dut, "tb_chiplet_is_primary"), (
            "tb_chiplet_is_primary missing; rebuild after OCTS dual-sync TB lift"
        )
        assert hasattr(dut, "tb_octs_sync_load_ext"), (
            "tb_octs_sync_load_ext missing; rebuild after OCTS dual-sync TB lift"
        )

        # --- Phase B first: SECONDARY pad inject (sync before credit).
        dut.tb_chiplet_is_primary.value = 0
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        await ClockCycles(clk, 8)

        await self.csr_write("OCTS_CTRL", _OCTS_CTRL, _OCTS_CTRL_VAL)
        await self.csr_write("OCTS_TIMER_GPIO_ENABLE", _OCTS_TIMER_GPIO_ENABLE, 1)
        await self.csr_write("OCTS_PRESET_LO", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI", _OCTS_PRESET_HI, 0)
        self._stamp("S1")

        status = await self.csr_read("OCTS_STATUS_MODE", _OCTS_STATUS)
        assert status & _OCTS_STATUS_MODE, (
            f"OCTS STATUS.MODE != SECONDARY after strap: STATUS=0x{status:08x}"
        )
        self._chk(
            "CHK-OCTS-SEC-MODE",
            f"strap=0 STATUS=0x{status:08x} MODE={status & _OCTS_STATUS_MODE} RRESP OKAY",
        )
        self._stamp("S2")

        await self._secondary_start(clk)

        # Pulse wider than CTRL.PULSE_WIDTH so pad/CDC flops see a clean edge.
        await drive_secondary_sync_then_credits(
            dut,
            clk,
            pulse_width=max(4, _OCTS_PULSE_WIDTH + 2),
            num_credits=2,
            credit_gap_cycles=_OCTS_CREDIT_VAL + 4,
        )

        await ClockCycles(clk, 4)
        count_after = await self._read_count()
        status = await self.csr_read("OCTS_STATUS_RUNNING", _OCTS_STATUS)
        assert status & _OCTS_STATUS_RUNNING, (
            f"OCTS STATUS.RUNNING not set after secondary sync (STATUS=0x{status:08x})"
        )
        # After sync+credits: COUNT near PRESET + N*CREDIT_VAL (N=2).
        expected_lo = _OCTS_PRESET_VAL + _OCTS_CREDIT_VAL
        expected_hi = _OCTS_PRESET_VAL + 2 * _OCTS_CREDIT_VAL + 16
        assert expected_lo <= count_after <= expected_hi, (
            f"OCTS secondary COUNT out of range: got 0x{count_after:x}, "
            f"expected [{expected_lo:#x}, {expected_hi:#x}]"
        )
        cocotb.log.info(
            "OCTS secondary inject PASS: STATUS=0x%x COUNT=0x%x (preset=0x%x credit=0x%x)",
            status,
            count_after,
            _OCTS_PRESET_VAL,
            _OCTS_CREDIT_VAL,
        )
        self._stamp("S4")

        # --- Phase A: PRIMARY outbound sync/credit pad edges.
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        dut.tb_chiplet_is_primary.value = 1
        await ClockCycles(clk, 8)

        status = await self.csr_read("OCTS_STATUS_PRIMARY", _OCTS_STATUS)
        assert (status & _OCTS_STATUS_MODE) == 0, (
            f"OCTS STATUS.MODE != PRIMARY after strap: STATUS=0x{status:08x}"
        )

        await self.csr_write("OCTS_CTRL", _OCTS_CTRL, _OCTS_CTRL_VAL)
        await self.csr_write("OCTS_TIMER_GPIO_ENABLE", _OCTS_TIMER_GPIO_ENABLE, 1)
        await self.csr_write("OCTS_PRESET_LO", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI", _OCTS_PRESET_HI, 0)

        edge_task_sync = cocotb.start_soon(
            count_rising_edges(dut.tb_octs_sync_load_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        edge_task_credit = cocotb.start_soon(
            count_rising_edges(dut.tb_octs_cnt_credit_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        width_task = cocotb.start_soon(
            _high_times(dut.tb_octs_sync_load_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        # COUNT is already running above PRESET here, left there by the
        # secondary phase. TIMER_START reloads it, so the reload -- not the
        # absolute value -- is what this write can be shown to have caused.
        count_before_start = await self._read_count()
        await self.csr_write("OCTS_TIMER_START", _OCTS_TIMER_START, 1)
        count_reloaded = await self._read_count()
        status_pri = await self.csr_read("OCTS_STATUS_PRI_START", _OCTS_STATUS)

        sync_edges = await edge_task_sync
        credit_edges = await edge_task_credit
        high_times, open_run, unresolved = await width_task
        assert sync_edges >= 1, f"OCTS primary pad55 sync_load edges={sync_edges}, need >= 1"
        assert credit_edges >= 2, f"OCTS primary pad56 cnt_credit edges={credit_edges}, need >= 2"

        count_pri = await self._read_count()
        # Anchored to values this run measured, not to the PRESET this sequence
        # programmed: COUNT enters this phase above PRESET, so an absolute
        # comparison against PRESET would hold with or without the TIMER_START
        # write.
        assert count_reloaded < count_before_start, (
            f"OCTS TIMER_START did not reload COUNT: 0x{count_before_start:x} -> "
            f"0x{count_reloaded:x} (a free-running counter only increases)"
        )
        assert _OCTS_PRESET_VAL <= count_reloaded <= _OCTS_PRESET_VAL + _OCTS_RELOAD_SLACK, (
            f"OCTS COUNT reloaded to 0x{count_reloaded:x}, not to PRESET "
            f"0x{_OCTS_PRESET_VAL:x} (+{_OCTS_RELOAD_SLACK} read latency)"
        )
        advance = count_pri - count_reloaded
        assert 1 <= advance <= _OCTS_MAX_ADVANCE, (
            f"OCTS COUNT advanced {advance} from 0x{count_reloaded:x} over "
            f"{_OCTS_PRIMARY_WAIT} clk_smc_i, expected 1..{_OCTS_MAX_ADVANCE}"
        )
        cocotb.log.info(
            "CHK-OCTS-DUAL-SYNC: SECONDARY strap: STATUS.MODE set, pad2core sync then "
            "%d credits gave STATUS.RUNNING and COUNT=0x%x within [0x%x, 0x%x]; PRIMARY "
            "strap: STATUS.MODE clear, %d sync_load and %d cnt_credit rising edges on "
            "the DUT pads over %d clk_smc_i, TIMER_START reloaded COUNT 0x%x -> 0x%x "
            "(PRESET 0x%x) and it advanced %d afterwards",
            2,
            count_after,
            expected_lo,
            expected_hi,
            sync_edges,
            credit_edges,
            _OCTS_PRIMARY_WAIT,
            count_before_start,
            count_reloaded,
            _OCTS_PRESET_VAL,
            advance,
        )

        assert status_pri & _OCTS_STATUS_RUNNING, (
            f"OCTS STATUS.RUNNING clear after the PRIMARY TIMER_START (STATUS=0x{status_pri:08x})"
        )
        assert unresolved == 0, (
            f"OCTS pad55 sync_load unresolvable on {unresolved} of {_OCTS_PRIMARY_WAIT} samples"
        )
        # The pulse width is counted in clk_smc_i; the timer clock that
        # PULSE_WIDTH counts is not stated (SF-027), so it is logged only.
        self._chk(
            "CHK-OCTS-PRI-START",
            f"COUNT reload 0x{count_reloaded:x} in [0x{_OCTS_PRESET_VAL:x},"
            f"0x{_OCTS_PRESET_VAL + _OCTS_RELOAD_SLACK:x}], RUNNING=1 (STATUS=0x{status_pri:08x}), "
            f"pulses={sync_edges}>=1, high_time={high_times} clk_smc_i (open at window end="
            f"{open_run}) vs PULSE_WIDTH={_OCTS_PULSE_WIDTH} (LINKED-ISSUE SF-027, logged)",
        )
        self.chk_seen.add("CHK-OCTS-DUAL-SYNC")
        self._stamp("S5")

        self._timeout_paths(
            [
                ("S3 pad55 sync_load edges", f"edges={self._sec_sync_edges}"),
                ("S5 pad55 sync_load edges", f"edges={sync_edges}"),
                ("S5 pad56 cnt_credit edges", f"edges={credit_edges}"),
                ("S5 pad55 sync_load high time", f"runs={high_times} open={open_run}"),
            ]
        )
        self._fence()
