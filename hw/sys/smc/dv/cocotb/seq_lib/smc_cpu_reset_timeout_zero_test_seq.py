# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A `RESET_TIMEOUT.timeout_value` of zero leaves a stuck uncore drain withheld.

cpu.adoc, "Timeout Recovery": "`CPU_CTRL.RESET_TIMEOUT` limits how long a software
uncore reset waits for the drain handshake; core resets do not wait and do not affect
it. A `timeout_value` of zero disables the timer. When the timer expires,
`timeout_mode=0` reports the timeout and continues to withhold the reset until the
drain completes, then applies it."

Four SEP_IN reads of the scratchpad are parked by holding R at the SMC boundary, so the
L2 frontend isolate cannot drain. The uncore reset bit is cleared with `timeout_mode` 1
and `timeout_value` 0: on every one of 2^16 + 64 clk_smc_i rises (past the longest
count the 16-bit field can hold) `reset_timeout` is 0, `reset_applied` is 0 and the
uncore reset is released, with `isolate_req` 1, `drained` 0 and the pending AR count
nonzero (the drain is stuck, so only the timer could apply the reset). `RESET_TIMEOUT` is then rewritten with `timeout_value` 0x40 in
`timeout_mode` 0: `reset_timeout` rises 0x40 +/- 8 rises after the write completes
while the reset stays withheld. The hold is released, the parked reads complete with
their words, the drain completes and the reset is applied; the uncore bit is set again
and both status bits read clear.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import cpu_ctrl_u32
from .smc_cpu_isolate_flush_test_seq import (
    BOOT_BOUND,
    L2_READ_RECOVERY_DATA,
    RESET_CTRL,
    RESET_TIMEOUT,
    STABLE_WINDOW_CYCLES,
    STATE_BOUND,
    TIMEOUT_MODE,
    UNCORE_RESET_N,
    WEDGE_BYTES,
    WEDGE_READ_AXI_ID,
    WEDGE_READ_BASE,
    WEDGE_READS,
    _CpuIsolateFlushSeq,
)

VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")

TIMEOUT_VALUE_BITS = 16
REARM_VALUE = 0x40
REARM_SLACK = 8
# Past the longest count the field can hold, so a timer that reads 0 as 2^16 fires inside
# the window.
DISABLED_SAMPLES = (1 << TIMEOUT_VALUE_BITS) + REARM_SLACK * 8
_WORDS_PER_READ = WEDGE_BYTES // 8

# (reset_timeout, reset_applied, uncore_reset_n, isolate_req, drained) while withheld.
_WITHHELD = (0, 0, 1, 1, 0)
_STATUS_PROBES = (
    "tb_cpu_reset_timeout",
    "tb_cpu_reset_applied",
    "tb_cpu_uncore_reset_n",
    "tb_cpu_isolate_req",
    "tb_cpu_drained",
)


def _wedge_word(index: int) -> int:
    return L2_READ_RECOVERY_DATA ^ index


def _wedge_bytes(read: int) -> bytes:
    first = read * _WORDS_PER_READ
    return b"".join(
        _wedge_word(w).to_bytes(8, "little") for w in range(first, first + _WORDS_PER_READ)
    )


class smc_cpu_reset_timeout_zero_test_seq(_CpuIsolateFlushSeq):
    """Hold an L2 read drain with the timer at zero, then re-arm it."""

    def __init__(self, name: str = "smc_cpu_reset_timeout_zero_test_seq") -> None:
        super().__init__(name)
        self.disabled_samples = 0
        self.rearm_fired_after: int | None = None

    async def _wait_event(self, event, bound: int, label: str) -> None:
        for _ in range(bound + 1):
            if event.is_set():
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label} did not complete within {bound} clk_smc_i cycles")

    def _status(self) -> tuple[int, ...]:
        dut = cocotb.top
        return tuple(self._value(getattr(dut, p), p) for p in _STATUS_PROBES)

    async def body(self) -> None:
        dut = cocotb.top
        axi = self.env.sys_axi_agent.driver.axi
        assert axi is not None, "SEP_IN AXI event API is not ready after bring-up"

        await self._wait_eq("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary at boot")
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        assert reset_ctrl & UNCORE_RESET_N, f"RESET_CTRL 0x{reset_ctrl:x}: uncore already held"
        await self.csr_write("RESET_TIMEOUT_DISABLED", RESET_TIMEOUT, TIMEOUT_MODE, length=8)
        await self.csr_read(
            "RESET_TIMEOUT_DISABLED_RB", RESET_TIMEOUT, length=8, expected=TIMEOUT_MODE
        )
        for word in range(WEDGE_READS * _WORDS_PER_READ):
            await self.csr_write(
                "L2_WEDGE_READ_PRELOAD", WEDGE_READ_BASE + word * 8, _wedge_word(word), length=8
            )

        dut.tb_sep_axi_r_hold.value = 1
        try:
            events = [
                axi.init_read(
                    address=WEDGE_READ_BASE + i * WEDGE_BYTES,
                    length=WEDGE_BYTES,
                    size=3,
                    id=WEDGE_READ_AXI_ID,
                )
                for i in range(WEDGE_READS)
            ]
            await self._wait_nonzero("tb_cpu_l2_pending_ar", STATE_BOUND, "L2 pending AR count")
            await self._wait_eq(
                "tb_sep_axi_r_raw_valid", 1, STATE_BOUND, "parked SEP_IN R response"
            )
            await self._hold_nonzero("tb_cpu_l2_pending_ar", STABLE_WINDOW_CYCLES, "L2 read wedge")

            await self.csr_write(
                "RESET_CTRL_UNCORE_LOW", RESET_CTRL, reset_ctrl & ~UNCORE_RESET_N, length=8
            )
            await self._wait_eq("tb_cpu_isolate_req", 1, STATE_BOUND, "CPU isolate request")
            pending_min = None
            for sample in range(1, DISABLED_SAMPLES + 1):
                await RisingEdge(dut.clk_smc_i)
                status = self._status()
                pending = self._value(dut.tb_cpu_l2_pending_ar, "tb_cpu_l2_pending_ar")
                assert status == _WITHHELD and pending != 0, (
                    f"timeout_value 0 did not hold the reset withheld: at sample {sample} of "
                    f"{DISABLED_SAMPLES} (reset_timeout, reset_applied, uncore_reset_n, "
                    f"isolate_req, drained) read {status}, expected {_WITHHELD}, L2 pending AR "
                    f"{pending}"
                )
                pending_min = pending if pending_min is None else min(pending_min, pending)
            self.disabled_samples = DISABLED_SAMPLES
            cocotb.log.info(
                "CHK-RESET-TIMEOUT-ZERO-DISABLED: with timeout_mode 1 and timeout_value 0 the "
                "withheld uncore reset read (reset_timeout, reset_applied, uncore_reset_n, "
                "isolate_req, drained) = %s on all %d clk_smc_i rises with L2 pending AR >= %d "
                "and SEP_IN R held: the timer never fired and the reset was never applied",
                _WITHHELD,
                DISABLED_SAMPLES,
                pending_min,
            )

            await self.csr_write(
                "RESET_TIMEOUT_REARM", RESET_TIMEOUT, REARM_VALUE << VALUE_BP, length=8
            )
            for rise in range(1, REARM_VALUE + REARM_SLACK + 1):
                await RisingEdge(dut.clk_smc_i)
                status = self._status()
                assert status[1:] == _WITHHELD[1:], (
                    f"report-mode timer changed the withheld state at rise {rise} after the "
                    f"re-arm: (reset_applied, uncore_reset_n, isolate_req, drained) read "
                    f"{status[1:]}, expected {_WITHHELD[1:]}"
                )
                if status[0] == 1:
                    self.rearm_fired_after = rise
                    break
            assert self.rearm_fired_after is not None, (
                f"reset_timeout stayed 0 for {REARM_VALUE + REARM_SLACK} rises after "
                f"timeout_value was rewritten to 0x{REARM_VALUE:x}"
            )
            assert self.rearm_fired_after >= REARM_VALUE - REARM_SLACK, (
                f"reset_timeout rose {self.rearm_fired_after} rises after the write completed, "
                f"before the 0x{REARM_VALUE:x} - {REARM_SLACK} floor: the timer did not count "
                "the programmed value"
            )
            await self._hold_value(
                "tb_cpu_reset_applied",
                0,
                STABLE_WINDOW_CYCLES,
                "report-mode timeout withholds the reset",
            )
            cocotb.log.info(
                "CHK-RESET-TIMEOUT-REARMS: rewriting timeout_value to 0x%x (timeout_mode 0) on "
                "the same withheld request raised reset_timeout %d clk_smc_i rises after the "
                "write completed (window 0x%x +/- %d) and reset_applied stayed 0 for %d more "
                "rises: the timer counts the programmed value and report mode withholds",
                REARM_VALUE,
                self.rearm_fired_after,
                REARM_VALUE,
                REARM_SLACK,
                STABLE_WINDOW_CYCLES,
            )

            dut.tb_sep_axi_r_hold.value = 0
            await self._wait_eq("tb_cpu_l2_pending_ar", 0, STATE_BOUND, "released L2 pending AR")
            await self._wait_eq("tb_cpu_drained", 1, STATE_BOUND, "CPU boundary drained")
            await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "drained reset applied")
            await self._wait_eq("tb_cpu_uncore_reset_n", 0, STATE_BOUND, "uncore reset asserted")
            for read, event in enumerate(events):
                await self._wait_event(event, STATE_BOUND, f"parked read {read}")
                resp = event.data
                assert int(resp.resp) == 0 and bytes(resp.data) == _wedge_bytes(read), (
                    f"parked read {read} completed with resp {int(resp.resp)} and data "
                    f"{bytes(resp.data).hex()}, expected OKAY with {_wedge_bytes(read).hex()}"
                )
            cocotb.log.info(
                "released SEP_IN R: the %d parked reads completed OKAY with their preloaded "
                "words, the drain completed and the withheld reset was applied",
                WEDGE_READS,
            )

            await self._release_reset(reset_ctrl)
            await self.csr_read(
                "RESET_TIMEOUT_RELEASED",
                RESET_TIMEOUT,
                length=8,
                expected=REARM_VALUE << VALUE_BP,
            )
            await self.csr_write("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, length=8)
            await self.csr_read("RESET_CTRL_RESTORED", RESET_CTRL, length=8, expected=reset_ctrl)
        finally:
            dut.tb_sep_axi_r_hold.value = 0
