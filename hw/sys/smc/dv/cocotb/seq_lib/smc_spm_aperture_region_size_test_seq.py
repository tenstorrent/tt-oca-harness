# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad window reach by aperture alias and REGION_SIZE over SEP_IN AXI.

Specs memmap.adoc (Memory Map), fabric.adoc (Local and Remote Resource Access).

The window word is the last 64-bit word of the scratchpad window, at offset 0x15_FFF8 from
LOCAL_BASE: inside a 2 MiB aperture and beyond a 1 MiB one. Every access completes before
the next starts except the in-flight groups, which keep a window access and a REGION_SIZE
write outstanding together; a passive sampler on the s_axi handshakes measures the overlap.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    SPM_MEMORY_BASE,
    SPM_MEMORY_SIZE,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
GLOBAL_BASE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")

# Spec values: the generated resets and the sizes around the window end.
CONTRACT_REGION_SIZE_RESET = 0x100_0000
CONTRACT_GLOBAL_BASE_RESET = 0x4000_0000
REGION_SIZE_2M = 0x20_0000
REGION_SIZE_1M = 0x10_0000
WINDOW_END_OFFSET = 0x16_0000

_WORD = 8
WINDOW_OFFSET = SPM_MEMORY_BASE + SPM_MEMORY_SIZE - _WORD - LOCAL_BASE_RESET
WINDOW_LOCAL = LOCAL_BASE_RESET + WINDOW_OFFSET
WINDOW_GLOBAL = GLOBAL_BASE_RESET + WINDOW_OFFSET
assert REGION_SIZE_RESET == CONTRACT_REGION_SIZE_RESET
assert GLOBAL_BASE_RESET == CONTRACT_GLOBAL_BASE_RESET
assert WINDOW_OFFSET + _WORD == WINDOW_END_OFFSET
assert REGION_SIZE_1M <= WINDOW_OFFSET < WINDOW_END_OFFSET <= REGION_SIZE_2M

PATTERN_LOCAL = 0x1111_2222_3333_4444
PATTERN_GLOBAL = 0x5555_6666_7777_8888
PATTERN_REFUSED = 0x9999_AAAA_BBBB_CCCC
PATTERN_POSITIVE = 0xDDDD_EEEE_FFFF_0123
PATTERN_GROUP_WRITE = 0x0F0F_1E1E_2D2D_3C3C

FENCE_TERMS = (
    "BRINGUP_SENSE_DONE",
    "REGION_RESET_READ",
    "ALIAS_LOCAL_TO_GLOBAL",
    "ALIAS_GLOBAL_TO_LOCAL",
    "REACH_16M",
    "REACH_2M",
    "DECERR_1M",
    "RESTORED_POSITIVE_CONTROL",
    "B2B_BOTH_ORDERS",
    "INFLIGHT_OVERLAP_MEASURED",
    "REGION_SIZE_RESTORED",
)
# Fence term that completes the step each checker line reports.
CHECKER_TERMS = (
    ("CHK-SPM-ALIAS", "ALIAS_GLOBAL_TO_LOCAL"),
    ("CHK-SPM-REGION-REACH", "REACH_2M"),
    ("CHK-SPM-REGION-DECERR", "RESTORED_POSITIVE_CONTROL"),
    ("CHK-SPM-REGION-B2B", "B2B_BOTH_ORDERS"),
    ("CHK-SPM-REGION-INFLIGHT", "INFLIGHT_OVERLAP_MEASURED"),
)

FUSE_SENSE_MAX_CYCLES = 200_000


class _HandshakeSampler:
    """Passive per-cycle record of the s_axi address and response handshakes."""

    def __init__(self) -> None:
        self.cycle = 0
        self.ar: list[tuple[int, int]] = []
        self.aw: list[tuple[int, int]] = []
        self.r_beats: list[int] = []
        self.b_beats: list[int] = []
        self.error: str | None = None
        self._task = None

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        if not value.is_resolvable:
            raise AssertionError(f"{name} is X/Z at the handshake sample")
        return int(value)

    async def _run(self) -> None:
        dut = cocotb.top
        try:
            while True:
                await RisingEdge(dut.clk_smc_i)
                self.cycle += 1
                bit = self._bit
                if bit(dut.s_axi_arvalid, "s_axi_arvalid") and bit(
                    dut.s_axi_arready, "s_axi_arready"
                ):
                    self.ar.append((self.cycle, bit(dut.s_axi_araddr, "s_axi_araddr")))
                if bit(dut.s_axi_awvalid, "s_axi_awvalid") and bit(
                    dut.s_axi_awready, "s_axi_awready"
                ):
                    self.aw.append((self.cycle, bit(dut.s_axi_awaddr, "s_axi_awaddr")))
                if bit(dut.s_axi_rvalid, "s_axi_rvalid") and bit(dut.s_axi_rready, "s_axi_rready"):
                    self.r_beats.append(self.cycle)
                if bit(dut.s_axi_bvalid, "s_axi_bvalid") and bit(dut.s_axi_bready, "s_axi_bready"):
                    self.b_beats.append(self.cycle)
        except AssertionError as exc:
            self.error = str(exc)

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()
        assert self.error is None, self.error

    def first_at(self, events: list[tuple[int, int]], addr: int) -> int | None:
        for cyc, a in events:
            if a & 0xFFFF_FFFF == addr & 0xFFFF_FFFF:
                return cyc
        return None


class smc_spm_aperture_region_size_test_seq(SmcCsrSeq):
    """Alias, REGION_SIZE reach, limit, back-to-back and in-flight legs on one SPM word."""

    def __init__(self, name: str = "smc_spm_aperture_region_size_test_seq") -> None:
        super().__init__(name)
        self.value_reads = 0
        self.stamps: list[tuple[str, int]] = []
        self.events: list[tuple[str, str]] = []
        self.chk_lines: list[str] = []
        self.waits: list[tuple[str, str, str, str]] = []
        self.word = 0

    # -- ledger helpers -------------------------------------------------------------------
    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        self.events.append(("step", term))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self.events.append(("chk", chk_id))
        self.chk_lines.append(chk_id)

    def _note_wait(self, name: str, bound: str, expiry: str, last: str) -> None:
        self.waits.append((name, bound, expiry, last))

    # -- access helpers -------------------------------------------------------------------
    async def _read_exact(self, label: str, addr: int, expected: int, length: int = 8) -> int:
        self.value_reads += 1
        return await self.csr_read(label, addr, expected=expected, length=length)

    async def _write_word(self, label: str, addr: int, data: int) -> None:
        await self.csr_write(label, addr, data, length=_WORD)

    async def _read_decerr(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: expected DECERR, got resp={item.resp_code} "
            f"rdata=0x{item.rdata:x}"
        )
        return item.rdata

    async def _write_decerr(self, label: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD
        item.wdata = data
        item.allow_error = True
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: expected DECERR, got resp={item.resp_code}"
        )

    async def _set_region_size(self, label: str, size: int) -> None:
        await self.csr_write(label, REGION_SIZE, size)

    async def _restore_region_size(self, label: str) -> None:
        await self._set_region_size(f"{label}_RESTORE", REGION_SIZE_RESET)
        self.value_reads += 1
        await self.csr_read(f"{label}_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)

    # -- steps ----------------------------------------------------------------------------
    async def _s1_setup(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._stamp("BRINGUP_SENSE_DONE")
        self._note_wait(
            "wait_fuse_sense_done",
            f"{FUSE_SENSE_MAX_CYCLES} clk_smc cycles",
            "AssertionError naming the signal that never asserted",
            "tb_fuse_sense_done asserted and warm reset released",
        )
        self.env.axi_monitor.expected_decerr_addrs.add(WINDOW_LOCAL)
        await self._read_exact("REGION_SIZE_RESET", REGION_SIZE, REGION_SIZE_RESET, length=4)
        await self._read_exact(
            "GLOBAL_BASE_RESET", GLOBAL_BASE_ADDR, GLOBAL_BASE_RESET & 0xFFFF_FFFF, length=4
        )
        self._stamp("REGION_RESET_READ")

    async def _s2_alias(self) -> None:
        await self._write_word("ALIAS_LOCAL_WR", WINDOW_LOCAL, PATTERN_LOCAL)
        via_global = await self._read_exact("ALIAS_GLOBAL_RD", WINDOW_GLOBAL, PATTERN_LOCAL)
        self._stamp("ALIAS_LOCAL_TO_GLOBAL")
        await self._write_word("ALIAS_GLOBAL_WR", WINDOW_GLOBAL, PATTERN_GLOBAL)
        via_local = await self._read_exact("ALIAS_LOCAL_RD", WINDOW_LOCAL, PATTERN_GLOBAL)
        self.word = PATTERN_GLOBAL
        self._stamp("ALIAS_GLOBAL_TO_LOCAL")
        self._chk(
            "CHK-SPM-ALIAS",
            "local 0x%x <- 0x%x read through global 0x%x = 0x%x (OKAY); global write 0x%x read "
            "through local = 0x%x (OKAY)",
            WINDOW_LOCAL,
            PATTERN_LOCAL,
            WINDOW_GLOBAL,
            via_global,
            PATTERN_GLOBAL,
            via_local,
        )

    async def _s3_reach(self) -> None:
        at_16m = await self._read_exact("REACH_16M", WINDOW_LOCAL, self.word)
        self._stamp("REACH_16M")
        await self._set_region_size("REACH_2M_SET", REGION_SIZE_2M)
        self.value_reads += 1
        await self.csr_read("REACH_2M_RB", REGION_SIZE, expected=REGION_SIZE_2M)
        at_2m = await self._read_exact("REACH_2M", WINDOW_LOCAL, self.word)
        await self._restore_region_size("REACH")
        self._stamp("REACH_2M")
        self._chk(
            "CHK-SPM-REGION-REACH",
            "window word 0x%x read OKAY 0x%x at REGION_SIZE 0x%x and 0x%x at 0x%x",
            WINDOW_LOCAL,
            at_16m,
            REGION_SIZE_RESET,
            at_2m,
            REGION_SIZE_2M,
        )

    async def _s4_limit(self) -> None:
        await self._set_region_size("LIMIT_1M_SET", REGION_SIZE_1M)
        rdata = await self._read_decerr("LIMIT_RD", WINDOW_LOCAL)
        await self._write_decerr("LIMIT_WR", WINDOW_LOCAL, PATTERN_REFUSED)
        self._stamp("DECERR_1M")
        await self._restore_region_size("LIMIT")
        kept = await self._read_exact("LIMIT_KEPT", WINDOW_LOCAL, self.word)
        await self._write_word("POSITIVE_WR", WINDOW_LOCAL, PATTERN_POSITIVE)
        fresh = await self._read_exact("POSITIVE_RD", WINDOW_LOCAL, PATTERN_POSITIVE)
        self.word = PATTERN_POSITIVE
        self._stamp("RESTORED_POSITIVE_CONTROL")
        self._chk(
            "CHK-SPM-REGION-DECERR",
            "at REGION_SIZE 0x%x read and write of 0x%x answered DECERR (owner value pending: "
            "DECERR read data 0x%x printed, not compared); after restore the word read 0x%x, "
            "not the refused 0x%x, and the fresh 0x%x read back 0x%x",
            REGION_SIZE_1M,
            WINDOW_LOCAL,
            rdata,
            kept,
            PATTERN_REFUSED,
            PATTERN_POSITIVE,
            fresh,
        )

    async def _s5_back_to_back(self) -> None:
        await self._set_region_size("B2B_SMALL_1", REGION_SIZE_1M)
        await self._set_region_size("B2B_LARGE_1", REGION_SIZE_RESET)
        after_small_large = await self._read_exact("B2B_SL_RD", WINDOW_LOCAL, self.word)
        await self._set_region_size("B2B_LARGE_2", REGION_SIZE_RESET)
        await self._set_region_size("B2B_SMALL_2", REGION_SIZE_1M)
        rdata = await self._read_decerr("B2B_LS_RD", WINDOW_LOCAL)
        await self._restore_region_size("B2B")
        self._stamp("B2B_BOTH_ORDERS")
        self._chk(
            "CHK-SPM-REGION-B2B",
            "REGION_SIZE 0x%x then 0x%x: next window read OKAY 0x%x; 0x%x then 0x%x: next window "
            "read DECERR (read data 0x%x printed)",
            REGION_SIZE_1M,
            REGION_SIZE_RESET,
            after_small_large,
            REGION_SIZE_RESET,
            REGION_SIZE_1M,
            rdata,
        )

    async def _group(self, label: str, window_item: SmcSysAxiItem) -> None:
        region_item = SmcSysAxiItem(f"wr_{label}_REGION")
        region_item.op = SmcSysAxiOp.WRITE
        region_item.addr = REGION_SIZE
        region_item.length = 4
        region_item.wdata = REGION_SIZE_1M
        group = SmcSysAxiGroupItem(label, [window_item, region_item])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 2
        for member in group.items:
            assert member.resp_code in (AXI_RESP_OKAY, AXI_RESP_DECERR), (
                f"{label} {member.get_name()}: resp={member.resp_code}, expected OKAY or DECERR"
            )

    def _overlap(self, label: str, sampler: _HandshakeSampler, is_read: bool) -> str:
        window_addr = WINDOW_LOCAL
        region_aw = sampler.first_at(sampler.aw, REGION_SIZE)
        if is_read:
            first_req = sampler.first_at(sampler.ar, window_addr)
            responses = sampler.r_beats
        else:
            first_req = sampler.first_at(sampler.aw, window_addr)
            responses = sampler.b_beats
        assert first_req is not None and region_aw is not None and responses, (
            f"{label}: handshakes not observed: window request={first_req} "
            f"REGION_SIZE AW={region_aw} responses={responses}"
        )
        first_resp = responses[0]
        assert first_req <= region_aw < first_resp, (
            f"{label}: no overlap: window request cycle {first_req}, REGION_SIZE AW cycle "
            f"{region_aw}, first response beat cycle {first_resp}"
        )
        return (
            f"{label}: window {'AR' if is_read else 'AW'} cycle {first_req}, REGION_SIZE AW cycle "
            f"{region_aw}, first {'R' if is_read else 'B'} beat cycle {first_resp}"
        )

    async def _s6_in_flight(self) -> None:
        measured = []
        for label, is_read in (("INFLIGHT_RD", True), ("INFLIGHT_WR", False)):
            item = SmcSysAxiItem(f"{label}_WINDOW")
            item.op = SmcSysAxiOp.READ if is_read else SmcSysAxiOp.WRITE
            item.addr = WINDOW_LOCAL
            item.length = _WORD
            item.allow_error = True
            if not is_read:
                item.wdata = PATTERN_GROUP_WRITE
            sampler = _HandshakeSampler()
            sampler.start()
            try:
                await self._group(label, item)
            finally:
                sampler.stop()
            window_resp = item.resp_code
            measured.append(self._overlap(label, sampler, is_read))
            measured[-1] += f" window resp={window_resp}"
            if not is_read and window_resp == AXI_RESP_OKAY:
                self.word = PATTERN_GROUP_WRITE
            after = await self._read_decerr(f"{label}_AFTER", WINDOW_LOCAL)
            measured[-1] += f"; following read DECERR data 0x{after:x}"
            if is_read:
                await self._restore_region_size(label)
        self._stamp("INFLIGHT_OVERLAP_MEASURED")
        self._chk(
            "CHK-SPM-REGION-INFLIGHT",
            "each in-flight access completed OKAY or DECERR within the driver bound and the "
            "following access answered DECERR; overlap cycles: %s",
            " | ".join(measured),
        )
        await self._restore_region_size("INFLIGHT_WR")
        self._stamp("REGION_SIZE_RESTORED")

    # -- fence ----------------------------------------------------------------------------
    def _check_fence(self) -> None:
        steps = [t for t, _ in self.stamps]
        assert steps == list(FENCE_TERMS), f"fence terms out of order or missing: {steps}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence stamps not increasing: {times}"
        assert self.chk_lines == [c for c, _ in CHECKER_TERMS], self.chk_lines
        last_index = -1
        for chk_id, term in CHECKER_TERMS:
            step_idx = self.events.index(("step", term))
            chk_idx = self.events.index(("chk", chk_id))
            assert chk_idx > step_idx, f"{chk_id} printed before its step {term}"
            assert chk_idx > last_index, f"{chk_id} printed out of CHK order"
            last_index = chk_idx

    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        await self._s1_setup()
        await self._s2_alias()
        await self._s3_reach()
        await self._s4_limit()
        await self._s5_back_to_back()
        await self._s6_in_flight()

        compares = sb.sys_axi_value_checks_seen - value_checks_before
        assert compares >= self.value_reads, (
            f"scoreboard booked {compares} exact-value compares, {self.value_reads} were issued"
        )
        axi_bound = self.env.cfg.axi_timeout_ns
        self._note_wait(
            "sep_in_access",
            f"{axi_bound} ns per access and per group member",
            "driver raises AssertionError naming the access address",
            f"{self.accesses} accesses answered",
        )
        self._note_wait(
            "inflight_group",
            f"{axi_bound} ns per member",
            "driver raises AssertionError naming the member address",
            "both groups completed",
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self.waits),
            " ".join(f"{n}={b} fail-on-expiry={e} last={s};" for n, b, e, s in self.waits),
        )
        self._check_fence()
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            " < ".join(self.chk_lines),
            " ".join(f"{t}={ps}" for t, ps in self.stamps),
        )
