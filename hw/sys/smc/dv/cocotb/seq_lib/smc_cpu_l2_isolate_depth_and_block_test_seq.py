# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The L2 frontend isolate holds four reads and blocks a fifth; isolated, it blocks a new one.

cpu.adoc, "CPU AXI Isolation": "Two instances wrap the AXI ports listed above, each sized
for up to four outstanding transactions: the *L2 frontend* slave port, which blocks new
transactions rather than terminating them, and the *MMIO* master port, which terminates
new transactions presented while isolated with SLVERR responses".

Depth: SEP_IN R is held at the SMC boundary and five 64-byte scratchpad reads are
issued on one ID. `tb_cpu_l2_pending_ar` is sampled on every clk_smc_i rise from the
first read until every read has completed after the hold is released: it reaches 4,
never reads 5, the isolate's slave port holds an AR valid with ready low while it reads
4 (the fifth AR refused at the isolate itself), and it reads 3 then 4 again once a
read's last beat passes the isolate, so the fifth AR waited for a freed slot.

Block: with the fabric idle, a force-mode uncore reset is applied by the drain
(`reset_timeout` 0) so `tb_cpu_l2_isolated` reads 1. A fresh SEP_IN read of a preloaded
scratchpad word is issued: for 512 rises the isolate stays 1, its slave port refuses the
AR (valid with ready low) and SEP_IN sees no R handshake, so the read is neither
answered nor terminated. The uncore bit is set again: the read completes OKAY with the preloaded
word within 256 rises of the isolate falling.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_cpu_isolate_flush_test_seq import (
    BOOT_BOUND,
    RESET_CTRL,
    RESET_TIMEOUT,
    SPM_BASE,
    STABLE_WINDOW_CYCLES,
    STATE_BOUND,
    TIMEOUT_FORCE,
    UNCORE_RESET_N,
    WEDGE_BYTES,
    _CpuIsolateFlushSeq,
)

ISOLATE_DEPTH = 4
DEPTH_READS = ISOLATE_DEPTH + 1
DEPTH_READ_BASE = SPM_BASE + 0x23_000
DEPTH_READ_AXI_ID = 1
DEPTH_DATA = 0x1501_DE97_0000_0000
BLOCK_PROBE_ADDR = SPM_BASE + 0x24_000
BLOCK_PROBE_AXI_ID = 2
BLOCK_PROBE_DATA = 0x1501_B10C_0000_0005
BLOCK_SAMPLES = 512
REOPEN_BOUND = 256
_WORDS_PER_READ = WEDGE_BYTES // 8


def _depth_word(read: int, word: int) -> int:
    return DEPTH_DATA | (read << 16) | word


def _depth_bytes(read: int) -> bytes:
    return b"".join(_depth_word(read, w).to_bytes(8, "little") for w in range(_WORDS_PER_READ))


class smc_cpu_l2_isolate_depth_and_block_test_seq(_CpuIsolateFlushSeq):
    """Five held reads against the four-deep isolate, then a read into the isolated port."""

    def __init__(self, name: str = "smc_cpu_l2_isolate_depth_and_block_test_seq") -> None:
        super().__init__(name)
        self.pending_trace: list[int] = []
        self.ar_trace: list[tuple[int, int]] = []
        self.slv_ar_trace: list[tuple[int, int]] = []
        self.blocked_samples = 0

    async def _wait_event(self, event, bound: int, label: str) -> None:
        for _ in range(bound + 1):
            if event.is_set():
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label} did not complete within {bound} clk_smc_i cycles")

    def _ar(self) -> tuple[int, int]:
        dut = cocotb.top
        return (
            self._value(dut.s_axi_arvalid, "s_axi_arvalid"),
            self._value(dut.s_axi_arready, "s_axi_arready"),
        )

    def _slv_ar(self) -> tuple[int, int]:
        dut = cocotb.top
        return (
            self._value(dut.tb_cpu_l2_slv_arvalid, "tb_cpu_l2_slv_arvalid"),
            self._value(dut.tb_cpu_l2_slv_arready, "tb_cpu_l2_slv_arready"),
        )

    @staticmethod
    def _ar_counts(samples: list[tuple[int, int]]) -> tuple[int, int]:
        """SEP_IN AR handshakes and rises with AR valid and not ready."""
        return (
            sum(v & r for v, r in samples),
            sum(v & (1 - r) for v, r in samples),
        )

    async def _trace_pending(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.pending_trace.append(self._value(dut.tb_cpu_l2_pending_ar, "tb_cpu_l2_pending_ar"))
            self.ar_trace.append(self._ar())
            self.slv_ar_trace.append(self._slv_ar())

    async def _depth(self, axi) -> None:
        dut = cocotb.top
        for read in range(DEPTH_READS):
            for word in range(_WORDS_PER_READ):
                await self.csr_write(
                    "DEPTH_READ_PRELOAD",
                    DEPTH_READ_BASE + read * WEDGE_BYTES + word * 8,
                    _depth_word(read, word),
                    length=8,
                )
        assert self._value(dut.tb_cpu_l2_pending_ar, "tb_cpu_l2_pending_ar") == 0, (
            "L2 pending AR count is nonzero before the depth reads are issued"
        )
        tracer = cocotb.start_soon(self._trace_pending())
        dut.tb_sep_axi_r_hold.value = 1
        try:
            events = [
                axi.init_read(
                    address=DEPTH_READ_BASE + i * WEDGE_BYTES,
                    length=WEDGE_BYTES,
                    size=3,
                    id=DEPTH_READ_AXI_ID,
                )
                for i in range(DEPTH_READS)
            ]
            await self._wait_eq(
                "tb_cpu_l2_pending_ar", ISOLATE_DEPTH, STATE_BOUND, "L2 pending AR count at depth"
            )
            await ClockCycles(dut.clk_smc_i, STABLE_WINDOW_CYCLES)
            held = len(self.pending_trace)
            dut.tb_sep_axi_r_hold.value = 0
            for read, event in enumerate(events):
                await self._wait_event(event, STATE_BOUND, f"depth read {read}")
                resp = event.data
                assert int(resp.resp) == 0 and bytes(resp.data) == _depth_bytes(read), (
                    f"depth read {read} completed with resp {int(resp.resp)} and data "
                    f"{bytes(resp.data).hex()}, expected OKAY with {_depth_bytes(read).hex()}"
                )
            await self._wait_eq("tb_cpu_l2_pending_ar", 0, STATE_BOUND, "L2 pending AR count idle")
        finally:
            dut.tb_sep_axi_r_hold.value = 0
            tracer.cancel()
        trace = self.pending_trace
        peak = max(trace)
        assert peak == ISOLATE_DEPTH, (
            f"L2 pending AR count peaked at {peak} with {DEPTH_READS} reads offered, expected "
            f"exactly {ISOLATE_DEPTH}: trace {trace}"
        )
        full = trace.index(ISOLATE_DEPTH)
        try:
            drop = next(i for i in range(full, len(trace)) if trace[i] == ISOLATE_DEPTH - 1)
            refill = next(i for i in range(drop, len(trace)) if trace[i] == ISOLATE_DEPTH)
        except StopIteration as exc:
            raise AssertionError(
                f"L2 pending AR never read {ISOLATE_DEPTH - 1} and then {ISOLATE_DEPTH} again "
                f"after first reaching {ISOLATE_DEPTH}: the fifth AR was not admitted into a "
                f"freed slot: trace {trace}"
            ) from exc
        at_depth = sum(v == ISOLATE_DEPTH for v in trace)
        ar_handshakes, ar_stalled = self._ar_counts(self.ar_trace[:held])
        assert ar_handshakes == DEPTH_READS or (ar_handshakes == ISOLATE_DEPTH and ar_stalled), (
            f"SEP_IN saw {ar_handshakes} AR handshake(s) and {ar_stalled} rise(s) with AR valid "
            f"and not ready before the hold released: the {DEPTH_READS} reads were not all "
            "offered while R was held"
        )
        refused = sum(
            v & (1 - r)
            for (v, r), pending in zip(self.slv_ar_trace[:held], trace[:held])
            if pending == ISOLATE_DEPTH
        )
        assert refused > 0, (
            f"the isolate's slave port never held an AR valid with ready low while "
            f"{ISOLATE_DEPTH} were pending: the fifth AR was not refused at the isolate"
        )
        cocotb.log.info(
            "CHK-L2-ISOLATE-DEPTH-FOUR: %d SEP_IN reads offered with R held (%d AR handshakes "
            "and %d AR-stalled rises at SEP_IN before the release; the isolate's slave port "
            "refused an AR on %d rises while %d were pending): tb_cpu_l2_pending_ar "
            "peaked at %d over %d sampled rises and never read %d; it first read %d at rise %d, "
            "read %d at rise %d and %d again at rise %d (the fifth AR admitted into the freed "
            "slot), %d rises at %d in all; the hold released at rise %d and all %d reads then "
            "completed OKAY with their preloaded words",
            DEPTH_READS,
            ar_handshakes,
            ar_stalled,
            refused,
            ISOLATE_DEPTH,
            peak,
            len(trace),
            ISOLATE_DEPTH + 1,
            ISOLATE_DEPTH,
            full,
            ISOLATE_DEPTH - 1,
            drop,
            ISOLATE_DEPTH,
            refill,
            at_depth,
            ISOLATE_DEPTH,
            held,
            DEPTH_READS,
        )

    async def _block(self, axi, reset_ctrl: int) -> None:
        dut = cocotb.top
        await self.csr_write("BLOCK_PROBE_PRELOAD", BLOCK_PROBE_ADDR, BLOCK_PROBE_DATA, length=8)
        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_FORCE, length=8)
        await self.csr_write(
            "RESET_CTRL_UNCORE_LOW", RESET_CTRL, reset_ctrl & ~UNCORE_RESET_N, length=8
        )
        await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "uncore reset applied")
        assert self._value(dut.tb_cpu_reset_timeout, "tb_cpu_reset_timeout") == 0, (
            "the idle-fabric uncore reset was applied by the force timeout, not by the drain"
        )
        await self._wait_eq("tb_cpu_l2_isolated", 1, STATE_BOUND, "L2 frontend isolated")

        event = axi.init_read(address=BLOCK_PROBE_ADDR, length=8, size=3, id=BLOCK_PROBE_AXI_ID)
        handshakes = 0
        ar_samples = []
        slv_ar_samples = []
        for sample in range(1, BLOCK_SAMPLES + 1):
            await RisingEdge(dut.clk_smc_i)
            isolated = self._value(dut.tb_cpu_l2_isolated, "tb_cpu_l2_isolated")
            handshakes += self._value(dut.s_axi_rvalid, "s_axi_rvalid") & self._value(
                dut.s_axi_rready, "s_axi_rready"
            )
            ar_samples.append(self._ar())
            slv_ar_samples.append(self._slv_ar())
            assert isolated == 1 and handshakes == 0 and not event.is_set(), (
                f"the isolated L2 frontend did not block the new read: at sample {sample} of "
                f"{BLOCK_SAMPLES} tb_cpu_l2_isolated read {isolated}, SEP_IN R handshakes "
                f"{handshakes}, read completed {event.is_set()}"
            )
        self.blocked_samples = BLOCK_SAMPLES
        ar_handshakes, ar_stalled = self._ar_counts(ar_samples)
        assert ar_handshakes + ar_stalled > 0, (
            "SEP_IN never presented the AR of the read into the isolated port during the window"
        )
        slv_accepted, slv_refused = self._ar_counts(slv_ar_samples)
        assert slv_accepted == 0 and slv_refused > 0, (
            f"the isolated L2 frontend's slave port accepted {slv_accepted} AR(s) and refused "
            f"one on {slv_refused} rises during the window: the read was not blocked there"
        )

        await self.csr_write("RESET_CTRL_RELEASE", RESET_CTRL, reset_ctrl, length=8)
        await self._wait_eq("tb_cpu_l2_isolated", 0, STATE_BOUND, "L2 frontend de-isolated")
        reopened = 0
        for reopened in range(1, REOPEN_BOUND + 1):
            await RisingEdge(dut.clk_smc_i)
            if event.is_set():
                break
        assert event.is_set(), (
            f"the blocked read did not complete within {REOPEN_BOUND} rises of the L2 frontend "
            "de-isolating"
        )
        resp = event.data
        got = int.from_bytes(bytes(resp.data), "little")
        assert int(resp.resp) == 0 and got == BLOCK_PROBE_DATA, (
            f"the blocked read completed with resp {int(resp.resp)} and data 0x{got:016x}, "
            f"expected OKAY with 0x{BLOCK_PROBE_DATA:016x}"
        )
        cocotb.log.info(
            "CHK-L2-ISOLATED-BLOCKS-NEW-ACCESS: a SEP_IN read of 0x%x issued while the uncore "
            "reset was held (%d AR handshake(s), %d AR-stalled rise(s) at SEP_IN in the window; "
            "the isolate's slave port refused its AR on %d rises and accepted none) saw "
            "tb_cpu_l2_isolated 1 and no SEP_IN R handshake on all %d sampled rises (not "
            "terminated), then completed OKAY with 0x%016x %d rises after the isolate fell "
            "(bound %d)",
            BLOCK_PROBE_ADDR,
            ar_handshakes,
            ar_stalled,
            slv_refused,
            self.blocked_samples,
            got,
            reopened,
            REOPEN_BOUND,
        )
        await self._wait_reset_released()
        await self.csr_read(
            "RESET_TIMEOUT_RELEASED", RESET_TIMEOUT, length=8, expected=TIMEOUT_FORCE
        )
        await self.csr_write("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, length=8)
        await self.csr_read("RESET_CTRL_RESTORED", RESET_CTRL, length=8, expected=reset_ctrl)

    async def body(self) -> None:
        axi = self.env.sys_axi_agent.driver.axi
        assert axi is not None, "SEP_IN AXI event API is not ready after bring-up"
        await self._wait_eq("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary at boot")
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        assert reset_ctrl & UNCORE_RESET_N, f"RESET_CTRL 0x{reset_ctrl:x}: uncore already held"
        await self._depth(axi)
        await self._block(axi, reset_ctrl)
