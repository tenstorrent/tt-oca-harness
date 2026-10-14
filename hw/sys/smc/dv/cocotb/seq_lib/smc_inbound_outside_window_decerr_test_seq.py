# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outside-window DECERR of the input-fabric region demux on sys_axi_in and sep_axi_in.

Spec sources: memmap.adoc Memory Map, fabric.adoc Fabric Topology, smc_base_config.rdl REGION_SIZE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
    output_responder_counts,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

AXI_RESP_DECERR = 3
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
WRITE_PATTERN = 0xA5A55A5A
SCRATCH_SEED = 0xC0DE_0001
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
MMODE_OFFSET = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - LOCAL_BASE_RESET
XVISOR_OFFSET = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR") - LOCAL_BASE_RESET
MMODE_SIZE = smc_addr("SMC_TOP_MMODE_REGION_SIZE")
XVISOR_SIZE = smc_addr("SMC_TOP_XVISOR_REGION_SIZE")
SCRATCH_OFFSET = SCRATCH_COLD_0 - LOCAL_BASE_RESET

BASES = (("LOCAL", LOCAL_BASE_RESET), ("GLOBAL", GLOBAL_BASE_RESET))
PORTS = ("SEP_IN", "SYS_IN")
OUTSIDE_CLASSES = (
    ("BELOW_LOCAL", 0x0000_1000),
    ("BETWEEN", 0x8000_0000),
    ("ABOVE_BOTH", 0xD000_0000),
    ("ABOVE_4GIB", 0x0000_0100_0000_0000),
)

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_CHECKERS = (
    "CHK-REGION-SIZE-LIMIT-DECERR",
    "CHK-BELOW-BASE-DECERR",
    "CHK-WINDOW-LAST-WORD-ROUTED",
    "CHK-OUTSIDE-WINDOW-DECERR",
    "CHK-OUTSIDE-NO-OUTPUT-REQUEST",
    "CHK-REMAP-REGION-RESET-DECERR",
)
_CHECKER_STEPS = ("S3", "S4", "S5", "S6", "S7", "S8")


class _ProbeWatch:
    """Counts clk_smc_i cycles of output_axi request valids and inbound read/write hits."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.aw_cycles = 0
        self.ar_cycles = 0
        self.read_hit0_cycles = 0
        self.write_hit0_cycles = 0
        self.unresolved = 0

    def snapshot(self) -> tuple[int, int, int, int]:
        return (self.aw_cycles, self.ar_cycles, self.read_hit0_cycles, self.write_hit0_cycles)

    async def run(self) -> None:
        names = (
            "tb_output_axi_awvalid",
            "tb_output_axi_arvalid",
            "tb_inb_read_hit",
            "tb_inb_write_hit",
        )
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            vals = []
            for name in names:
                value = getattr(self.dut, name).value
                if not value.is_resolvable:
                    self.unresolved += 1
                    vals.append(0)
                else:
                    vals.append(int(value))
            self.aw_cycles += vals[0] & 1
            self.ar_cycles += vals[1] & 1
            self.read_hit0_cycles += vals[2] & 1
            self.write_hit0_cycles += vals[3] & 1


class smc_inbound_outside_window_decerr_test_seq(SmcCsrSeq):
    """Drive both inbound ports outside the local and global windows at the reset REGION_SIZE."""

    def __init__(self, name: str = "smc_inbound_outside_window_decerr_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.watch: _ProbeWatch | None = None
        self.read_data: list[str] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _access(
        self,
        port: str,
        label: str,
        write: bool,
        addr: int,
        *,
        decerr: bool,
        expected: int | None = None,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{port.lower()}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        if write:
            item.wdata = WRITE_PATTERN
        item.allow_error = True
        if decerr:
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
        if expected is not None:
            item.expected = expected
            item.allow_error = False
        if port == "SEP_IN":
            await self.start_item(item)
            await self.finish_item(item)
        else:
            await _OneShot(item, f"{item.get_name()}_os").start(self.env.sys_in_axi_agent.sequencer)
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:x}: no response recorded"
        if decerr:
            assert item.resp_code == AXI_RESP_DECERR, (
                f"{port} {label} {'write' if write else 'read'} @ 0x{addr:x}: resp "
                f"{_RESP_NAMES.get(item.resp_code, item.resp_code)}, want DECERR "
                f"(rdata 0x{item.rdata:x})"
            )
        return item

    async def _decerr_pair(self, port: str, label: str, addr: int) -> str:
        rd = await self._access(port, label, False, addr, decerr=True)
        wr = await self._access(port, label, True, addr, decerr=True)
        self.read_data.append(f"{port}.{label}@0x{addr:X}=0x{rd.rdata & 0xFFFF_FFFF:08X}")
        return (
            f"{port}.{label}@0x{addr:X} rresp={_RESP_NAMES[rd.resp_code]} "
            f"rdata=0x{rd.rdata & 0xFFFF_FFFF:08X} bresp={_RESP_NAMES[wr.resp_code]}"
        )

    async def _decerr_sweep(self, addrs: list[tuple[str, int]]) -> str:
        parts = []
        for port in PORTS:
            for label, addr in addrs:
                parts.append(await self._decerr_pair(port, label, addr))
        return "; ".join(parts)

    def _expected_addrs(self) -> list[int]:
        addrs: list[int] = []
        for _, base in BASES:
            addrs += [base + REGION_SIZE_RESET, base - 4, base + REGION_SIZE_RESET - 8]
            for first, size in ((MMODE_OFFSET, MMODE_SIZE), (XVISOR_OFFSET, XVISOR_SIZE)):
                addrs += [base + first, base + first + size - 8]
        addrs += [addr for _, addr in OUTSIDE_CLASSES]
        return addrs

    def _sample_probes(self, label: str) -> None:
        dut = cocotb.top
        for name in (
            "tb_output_axi_awvalid",
            "tb_output_axi_arvalid",
            "tb_output_axi_write_count",
            "tb_output_axi_read_count",
            "tb_inb_read_hit",
        ):
            assert getattr(dut, name).value.is_resolvable, f"{name} is X/Z at {label}"

    def _output_silence(self, base_counts, base_watch) -> str:
        self._sample_probes("silence")
        counts = output_responder_counts(cocotb.top)
        now = self.watch.snapshot()
        assert self.watch.unresolved == 0, f"{self.watch.unresolved} unresolvable probe samples"
        assert counts == base_counts, f"output_axi counters moved {base_counts}->{counts}"
        assert now[:2] == base_watch[:2], (
            f"output_axi awvalid/arvalid cycles moved {base_watch[:2]}->{now[:2]}"
        )
        return (
            f"awvalid/arvalid cycles {now[0]}/{now[1]} unchanged from "
            f"{base_watch[0]}/{base_watch[1]}; write/read counters {counts} unchanged from "
            f"{base_counts}; inbound hit[0] read/write cycles {now[2]}/{now[3]}; unresolved 0"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.watch = _ProbeWatch(dut)
        cocotb.start_soon(self.watch.run())

        # S1: inbound entry 0 pass-all over SEP_IN.
        self.env.axi_monitor.expected_decerr_addrs.update(self._expected_addrs())
        await self.csr_write("INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("SCRATCH_COLD0_SEED", SCRATCH_COLD_0, SCRATCH_SEED, length=4)
        self._mark_step("S1")

        # S2: REGION_SIZE and the in-window positive control.
        self._sample_probes("S2")
        base_counts = output_responder_counts(dut)
        base_watch = self.watch.snapshot()
        region_sizes = []
        for port in PORTS:
            item = await self._access(
                port,
                "REGION_SIZE",
                False,
                REGION_SIZE_REG,
                decerr=False,
                expected=REGION_SIZE_RESET,
            )
            region_sizes.append(f"{port}=0x{item.rdata & 0xFFFF_FFFF:08X}")
        controls = []
        for port in PORTS:
            for bname, base in BASES:
                item = await self._access(
                    port,
                    f"SCRATCH_{bname}",
                    False,
                    base + SCRATCH_OFFSET,
                    decerr=False,
                    expected=SCRATCH_SEED,
                )
                controls.append(f"{port}.{bname}=0x{item.rdata & 0xFFFF_FFFF:08X}")
        control_hits = self.watch.read_hit0_cycles - base_watch[2]
        assert control_hits > 0, "tb_inb_read_hit[0] never moved over the sys_axi_in controls"
        self._mark_step("S2")

        # S3: first address at BASE+REGION_SIZE.
        limit = await self._decerr_sweep(
            [(f"{b}_LIMIT", base + REGION_SIZE_RESET) for b, base in BASES]
        )
        self._mark_step("S3")
        self._log_chk(
            "CHK-REGION-SIZE-LIMIT-DECERR",
            f"REGION_SIZE {','.join(region_sizes)} == 0x{REGION_SIZE_RESET:08X}; positive control "
            f"SCRATCH_COLD[0] {','.join(controls)}; DECERR on read and write: {limit}",
        )

        # S4: one word below each base.
        below = await self._decerr_sweep([(f"{b}_BELOW", base - 4) for b, base in BASES])
        self._mark_step("S4")
        self._log_chk("CHK-BELOW-BASE-DECERR", f"DECERR on read and write: {below}")

        # S5: last word of each window, answered by the local crossbar; response observe-only.
        last_parts = []
        for port in PORTS:
            for bname, base in BASES:
                addr = base + REGION_SIZE_RESET - 8
                rd = await self._access(port, f"{bname}_LAST", False, addr, decerr=False)
                wr = await self._access(port, f"{bname}_LAST", True, addr, decerr=False)
                last_parts.append(
                    f"{port}.{bname}@0x{addr:X} rresp={_RESP_NAMES.get(rd.resp_code)} "
                    f"rdata=0x{rd.rdata & 0xFFFF_FFFF:08X} (marker 0xBADCAB1E) "
                    f"bresp={_RESP_NAMES.get(wr.resp_code)}"
                )
        assert self.watch.snapshot()[:2] == base_watch[:2], "output_axi request during S5"
        self._mark_step("S5")
        self._log_chk(
            "CHK-WINDOW-LAST-WORD-ROUTED",
            f"answered within the guard, output_axi idle (aw/ar valid cycles "
            f"{self.watch.aw_cycles}/{self.watch.ar_cycles}); "
            f"observe-only: {'; '.join(last_parts)}",
        )

        # S6: address classes outside both windows.
        outside = await self._decerr_sweep(list(OUTSIDE_CLASSES))
        self._mark_step("S6")
        self._log_chk(
            "CHK-OUTSIDE-WINDOW-DECERR",
            f"DECERR on read and write: {outside}; read data (not specified, measured)",
        )

        # S7: positive control after the DECERR accesses shows the probes are live.
        self._sample_probes("S7")
        hits_before = self.watch.read_hit0_cycles
        item = await self._access(
            "SYS_IN", "SCRATCH_LIVE", False, SCRATCH_COLD_0, decerr=False, expected=SCRATCH_SEED
        )
        live_hits = self.watch.read_hit0_cycles - hits_before
        assert live_hits > 0, "tb_inb_read_hit[0] did not move for the in-window control"
        self._mark_step("S7")
        live = (
            f"SCRATCH_COLD[0]=0x{item.rdata & 0xFFFF_FFFF:08X} "
            f"tb_inb_read_hit[0] cycles {live_hits}"
        )
        silence = self._output_silence(base_counts, base_watch)
        self._log_chk(
            "CHK-OUTSIDE-NO-OUTPUT-REQUEST",
            f"{silence} across the DECERR accesses of S3-S6; positive control {live}",
        )

        # S8: the M-mode and Xvisor regions at the reset REGION_SIZE.
        remap_addrs = []
        for bname, base in BASES:
            for rname, first, size in (
                ("MMODE", MMODE_OFFSET, MMODE_SIZE),
                ("XVISOR", XVISOR_OFFSET, XVISOR_SIZE),
            ):
                remap_addrs.append((f"{bname}_{rname}_FIRST", base + first))
                remap_addrs.append((f"{bname}_{rname}_LAST", base + first + size - 8))
        remap = await self._decerr_sweep(remap_addrs)
        self._mark_step("S8")
        silence = self._output_silence(base_counts, base_watch)
        self._log_chk(
            "CHK-REMAP-REGION-RESET-DECERR",
            f"DECERR on read and write: {remap}; output_axi silent through S8: {silence}",
        )

        self.watch.stop = True

        await self.csr_write("SCRATCH_COLD0_RESTORE", SCRATCH_COLD_0, 0, length=4)
        await self.csr_read("SCRATCH_COLD0_RESTORE_RB", SCRATCH_COLD_0, expected=0, length=4)

        # Restore the inbound entry to its reset.
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses on SEP_IN and SYS_IN each bounded by the driver "
            "timeout %d ns (allow_timeout False), all answered; probe watch is a passive "
            "sampler with no wait; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECKER_STEPS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<POSITIVE_CONTROL<LIMIT<BELOW_BASE<LAST_WORD<"
            "OUTSIDE_CLASSES<NO_OUTPUT_REQUEST<REMAP_REGIONS; checker lines %s; accesses %d >= "
            "floor %d; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
