# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REGION_SIZE-gated decode of the M-mode / Xvisor regions and the PLIC, CLINT and BEU units.

Contract XBAR_025, anchor smc_region_gated_units_decode_test.
Allocated scenarios: XBAR-REMAP-REGION-DECERR.S1/S4, XBAR-DEC-CLUSTER-LOCAL.S1-S4,
INT-REGION-CLUSTER-LOCAL.
Spec sources: memmap.adoc Address Space Organization and Memory Map, smc.rdl
ocah_past_extent_resp, doc/integrator smu-smc.adoc Address Map and Aperture.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    _FILTER_CTRL_H,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
    jtag_axi_read,
    jtag_axi_write,
)

_BEU_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "bus_error_unit.h"
_CLINT_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "clint.h"

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
PAST_EXTENT_RDATA = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
SCRATCH_PATTERN = 0x5A5A_C3C3
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_32M = 0x0200_0000
REGION_SIZE_256M = 0x1000_0000
LOCAL_BASE = LOCAL_BASE_RESET
GLOBAL_BASE = GLOBAL_BASE_RESET
MMODE_FIRST = 0x0100_0000
MMODE_LAST = 0x017F_FFF8
XVISOR_FIRST = 0x0180_0000
XVISOR_LAST = 0x01FF_FFF8
REMAP_OFFSETS = (MMODE_FIRST, MMODE_LAST, XVISOR_FIRST, XVISOR_LAST)
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)

# (label, generated memory-map unit, base register address, access length, RDL reset or None)
PLIC_PRIORITY_0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY_BASE_ADDR", 0)
CLINT_MSIP_0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", 0)
PLIC_LAST = smc_addr("SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_CLAIM_COMPLETE_BASE_ADDR")
CLINT_MTIME = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
MSIP_RESET = reg_reset_word(_CLINT_H, "CLINT", "MSIP")
CAUSE_RESET = reg_reset_word(_BEU_H, "BUS_ERROR_UNIT", "CAUSE")
LOCAL_ENABLE_RESET = reg_reset_word(_BEU_H, "BUS_ERROR_UNIT", "LOCAL_ENABLE")
BEU_CAUSE = tuple(smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{c}_BEU_CAUSE_BASE_ADDR") for c in range(4))
BEU_LOCAL_ENABLE = tuple(
    smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{c}_BEU_LOCAL_ENABLE_BASE_ADDR") for c in range(4)
)

UNITS = (
    ("PLIC", "smc_cluster_plic"),
    ("CLINT", "smc_cluster_clint"),
    *((f"BEU{c}", f"smc_cluster_core{c}_beu") for c in range(4)),
)
UNIT_BASES = (
    ("PLIC", PLIC_PRIORITY_0),
    ("CLINT", CLINT_MSIP_0),
    *((f"BEU{c}", BEU_CAUSE[c]) for c in range(4)),
)

FILTER_START_RESET = reg_reset_word(_FILTER_CTRL_H, "FILTER_CTRL", "START_ADDR")
FILTER_END_RESET = reg_reset_word(_FILTER_CTRL_H, "FILTER_CTRL", "END_ADDR")
FILTER_CONFIG_RESET = reg_reset_word(_FILTER_CTRL_H, "FILTER_CTRL", "FILTER_CONFIG")
FILTER_PASS_END = 0x00FF_FFFF_FFFF_FFFF

PORTS = ("SEP", "SYS")
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "RESTORED")
_CHECKERS = (
    "CHK-CLUSTER-UNITS-RESET-DECERR",
    "CHK-REMAP-REGION-WIDENED-DECERR",
    "CHK-REMAP-REGION-JTAG-OBSERVE",
    "CHK-CLUSTER-UNITS-DECODED-AFTER-WIDEN",
    "CHK-CLUSTER-UNITS-LAST-REGISTER",
    "CHK-CLUSTER-UNITS-PAST-EXTENT",
)
_FENCE = (
    "SETUP<RESET_SIZE_DECERR<REMAP_REGIONS<JTAG_OBSERVE<DECODED_AFTER_WIDEN"
    "<LAST_REGISTERS<PAST_EXTENT<RESTORED"
)


class _OutputWatch:
    """Samples the SYS_OUT request probes at every clk_smc_i edge until stopped."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.aw_addrs: list[int] = []
        self.ar_addrs: list[int] = []
        self.samples = 0

    def _sample(self, name: str) -> int:
        value = getattr(self.dut, name).value
        assert value.is_resolvable, f"{name} is X/Z"
        return int(value)

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            self.samples += 1
            if self._sample("tb_output_axi_awvalid"):
                self.aw_addrs.append(self._sample("tb_output_axi_awaddr"))
            if self._sample("tb_output_axi_arvalid"):
                self.ar_addrs.append(self._sample("tb_output_axi_araddr"))

    def mark(self) -> tuple[int, int]:
        return len(self.aw_addrs), len(self.ar_addrs)

    def since(self, mark: tuple[int, int]) -> tuple[list[int], list[int]]:
        return self.aw_addrs[mark[0] :], self.ar_addrs[mark[1] :]


class smc_region_gated_units_decode_test_seq(SmcCsrSeq):
    """Gate PLIC, CLINT, BEU and the remap regions on REGION_SIZE over SEP_IN and SYS_IN."""

    def __init__(self, name: str = "smc_region_gated_units_decode_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "unsampled"
        self.watch: _OutputWatch | None = None
        self.region_size_saved: int | None = None
        self.past_text = ""
        self.restore_text = ""

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _xfer(
        self,
        port: str,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        length: int = 4,
        wdata: int = 0,
        expected: int | None = None,
        expect_resp: int | None = None,
        tolerate: bool = False,
    ) -> SmcSysAxiItem:
        """One access on ``port`` (SEP or SYS).

        ``expect_resp`` makes the scoreboard enforce that exact error code; ``tolerate``
        accepts any response for an observe-only leg; otherwise the access must be OKAY.
        """
        kind = "rd" if op == SmcSysAxiOp.READ else "wr"
        item = SmcSysAxiItem(f"{kind}_{port}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = wdata
        item.expected = expected
        if expect_resp is not None:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = expect_resp
        elif tolerate:
            item.allow_error = True
        if port == "SEP":
            await self.start_item(item)
            await self.finish_item(item)
        else:
            await _OneShot(item, f"{kind}_{port}_{label}_os").start(
                self.env.sys_in_axi_agent.sequencer
            )
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:08x}: no response recorded"
        if expect_resp is not None:
            assert item.resp_code == expect_resp, (
                f"{port} {label} @ 0x{addr:08x}: resp "
                f"{_RESP_NAMES.get(item.resp_code, item.resp_code)}, want "
                f"{_RESP_NAMES.get(expect_resp)} (rdata 0x{item.rdata:x})"
            )
        elif not tolerate:
            assert item.resp_code == AXI_RESP_OKAY, (
                f"{port} {label} @ 0x{addr:08x}: resp "
                f"{_RESP_NAMES.get(item.resp_code, item.resp_code)}, want OKAY"
            )
        return item

    def _expect_decerr(self, *addrs: int) -> None:
        self.env.axi_monitor.expected_decerr_addrs.update(addrs)

    async def _write_region_size(self, label: str, value: int) -> None:
        await self.csr_write(f"REGION_SIZE_{label}", REGION_SIZE, value)
        await self.csr_read(f"REGION_SIZE_{label}_RB", REGION_SIZE, expected=value)

    async def _step_setup(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.watch = _OutputWatch(cocotb.top)
        cocotb.start_soon(self.watch.run())
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, FILTER_PASS_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read("INBOUND0_START_RB", INBOUND0_START, expected=0x0, length=8)
        await self.csr_read("INBOUND0_END_RB", INBOUND0_END, expected=FILTER_PASS_END, length=8)
        await self.csr_read(
            "INBOUND0_CONFIG_RB", INBOUND0_FILTER_CONFIG, expected=PASS_ALL_CONFIG, length=8
        )
        self.region_size_saved = await self.csr_read(
            "REGION_SIZE_SAVE", REGION_SIZE, expected=REGION_SIZE_RESET
        )
        for _label, unit in UNITS:
            first, _last = generated_window(unit)
            self._expect_decerr(LOCAL_BASE + first)
        self._mark_step("S1")

    async def _step_reset_decerr(self) -> str:
        rows = []
        for port in PORTS:
            for label, addr in UNIT_BASES:
                rd = await self._xfer(
                    port, f"{label}_BASE_RESET", SmcSysAxiOp.READ, addr, expect_resp=AXI_RESP_DECERR
                )
                wr = await self._xfer(
                    port,
                    f"{label}_BASE_RESET",
                    SmcSysAxiOp.WRITE,
                    addr,
                    wdata=WRITE_PATTERN,
                    expect_resp=AXI_RESP_DECERR,
                )
                rows.append(
                    f"{port}:{label}@0x{addr:08X} rresp={_RESP_NAMES[rd.resp_code]} "
                    f"rdata=0x{rd.rdata & 0xFFFF_FFFF:08X} bresp={_RESP_NAMES[wr.resp_code]}"
                )
        self._mark_step("S2")
        return (
            f"at REGION_SIZE 0x{REGION_SIZE_RESET:X} the base of the PLIC, CLINT and four BEU "
            f"units answered DECERR on read and write over sep_axi_in and sys_axi_in; "
            f"rdata vs 0x{PAST_EXTENT_RDATA:08X} (SF-007 observe-only): {'; '.join(rows)}"
        )

    async def _step_remap_regions(self) -> str:
        await self._write_region_size("32M", REGION_SIZE_32M)
        counts_before = self._output_counts()
        mark = self.watch.mark()
        self._expect_decerr(
            *(base + off for base in (LOCAL_BASE, GLOBAL_BASE) for off in REMAP_OFFSETS)
        )
        rows = []
        for port in PORTS:
            for base_name, base in (("LOCAL", LOCAL_BASE), ("GLOBAL", GLOBAL_BASE)):
                for off in REMAP_OFFSETS:
                    addr = base + off
                    tag = f"{base_name}_{off:08X}"
                    rd = await self._xfer(
                        port, tag, SmcSysAxiOp.READ, addr, length=8, expect_resp=AXI_RESP_DECERR
                    )
                    wr = await self._xfer(
                        port,
                        tag,
                        SmcSysAxiOp.WRITE,
                        addr,
                        length=8,
                        wdata=WRITE_PATTERN,
                        expect_resp=AXI_RESP_DECERR,
                    )
                    rows.append(f"{port}:0x{addr:08X} r={rd.resp_code} w={wr.resp_code}")
        controls = []
        for port in PORTS:
            await self._xfer(
                port,
                "SCRATCH_COLD0_PATTERN",
                SmcSysAxiOp.WRITE,
                SCRATCH_COLD_0,
                wdata=SCRATCH_PATTERN,
            )
            got = await self._xfer(
                port,
                "SCRATCH_COLD0_RB",
                SmcSysAxiOp.READ,
                SCRATCH_COLD_0,
                expected=SCRATCH_PATTERN,
            )
            await self._xfer(
                port, "SCRATCH_COLD0_CLEAR", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=0
            )
            controls.append(f"{port}=0x{got.rdata & 0xFFFF_FFFF:08X}")
        aw_seen, ar_seen = self.watch.since(mark)
        counts_after = self._output_counts()
        assert not aw_seen and not ar_seen, (
            f"output_axi request during REGION_SIZE 0x{REGION_SIZE_32M:X} remap-region DECERR: "
            f"aw {[hex(a) for a in aw_seen]} ar {[hex(a) for a in ar_seen]}"
        )
        assert counts_after == counts_before, (
            f"SYS_OUT counters moved {counts_before} -> {counts_after} during the remap-region legs"
        )
        self._mark_step("S3")
        return (
            f"REGION_SIZE 0x{REGION_SIZE_32M:X}: first and last word of the M-mode "
            f"(0x{MMODE_FIRST:X}, 0x{MMODE_LAST:X}) and Xvisor (0x{XVISOR_FIRST:X}, "
            f"0x{XVISOR_LAST:X}) regions at LOCAL_BASE 0x{LOCAL_BASE:X} and GLOBAL_BASE "
            f"0x{GLOBAL_BASE:X} answered DECERR on read and write on both ports "
            f"({len(rows)} pairs, all resp=3); output_axi awvalid/arvalid idle over "
            f"{self.watch.samples} samples, SYS_OUT write/read counts {counts_after} unchanged; "
            f"in-window SCRATCH_COLD[0] positive control OKAY read-back {', '.join(controls)}"
        )

    def _output_counts(self) -> tuple[int, int]:
        counts = []
        for name in ("tb_output_axi_write_count", "tb_output_axi_read_count"):
            value = getattr(cocotb.top, name).value
            assert value.is_resolvable, f"{name} is X/Z"
            counts.append(int(value))
        return counts[0], counts[1]

    async def _step_jtag_observe(self) -> str:
        rows = []
        for region, off in (("MMODE", MMODE_FIRST), ("XVISOR", XVISOR_FIRST)):
            addr = LOCAL_BASE + off
            for kind in ("READ", "WRITE"):
                mark = self.watch.mark()
                counts_before = self._output_counts()
                if kind == "READ":
                    item = await jtag_axi_read(self, addr, allow_error=True)
                else:
                    item = await jtag_axi_write(self, addr, WRITE_PATTERN, allow_error=True)
                self.accesses += 1
                assert item.resp_code is not None, f"JTAG {kind} {region} @ 0x{addr:08x}: no resp"
                aw_seen, ar_seen = self.watch.since(mark)
                counts_after = self._output_counts()
                rows.append(
                    f"jtag {kind.lower()} {region}@0x{addr:08X} resp={_RESP_NAMES[item.resp_code]} "
                    f"output_aw={[hex(a) for a in aw_seen]} output_ar={[hex(a) for a in ar_seen]} "
                    f"sys_out_counts {counts_before}->{counts_after}"
                )
        self._mark_step("S4")
        return "; ".join(rows) + " (observe-only, SF-005)"

    async def _step_decoded_after_widen(self) -> str:
        await self._write_region_size("256M", REGION_SIZE_256M)
        rows = []
        for port in PORTS:
            for label, addr, reset in (
                ("PLIC_PRIORITY0", PLIC_PRIORITY_0, None),
                ("CLINT_MSIP0", CLINT_MSIP_0, MSIP_RESET),
                *((f"BEU{c}_CAUSE", BEU_CAUSE[c], CAUSE_RESET) for c in range(4)),
            ):
                item = await self._xfer(
                    port, f"{label}_WIDENED", SmcSysAxiOp.READ, addr, expected=reset
                )
                rows.append(f"{port}:{label}=0x{item.rdata & 0xFFFF_FFFF:X}")
        self._mark_step("S5")
        return (
            f"after REGION_SIZE 0x{REGION_SIZE_256M:X} CLINT MSIP[0] and the four BEU CAUSE read "
            f"{MSIP_RESET}/{CAUSE_RESET} with OKAY and the PLIC first register answered OKAY "
            f"(reset undeclared, SF-025: value printed); the same bases answered DECERR at the reset "
            f"size: {', '.join(rows)}"
        )

    async def _step_last_registers(self) -> str:
        rows = []
        for port in PORTS:
            item = await self._xfer(port, "PLIC_CORE3_SEIP_CLAIM", SmcSysAxiOp.READ, PLIC_LAST)
            rows.append(f"{port}:PLIC_CORE3_SEIP_CLAIM_COMPLETE=0x{item.rdata & 0xFFFF_FFFF:X}")
            item = await self._xfer(port, "CLINT_MTIME", SmcSysAxiOp.READ, CLINT_MTIME, length=8)
            rows.append(f"{port}:CLINT_MTIME=0x{item.rdata:X}")
            for core in range(4):
                item = await self._xfer(
                    port,
                    f"BEU{core}_LOCAL_ENABLE",
                    SmcSysAxiOp.READ,
                    BEU_LOCAL_ENABLE[core],
                    expected=LOCAL_ENABLE_RESET,
                )
                rows.append(f"{port}:BEU{core}_LOCAL_ENABLE=0x{item.rdata & 0xFFFF_FFFF:X}")
        self._mark_step("S6")
        return (
            "last register of each unit answered OKAY (PLIC CORE3_SEIP_CLAIM_COMPLETE @0x207004 "
            "and CLINT MTIME @0xBFF8 reset undeclared, value printed; BEU LOCAL_ENABLE @0x28 "
            f"reset 0x{LOCAL_ENABLE_RESET:X} compared): {', '.join(rows)}"
        )

    async def _step_past_extent(self) -> None:
        rows = []
        targets = []
        for label, unit in UNITS:
            first, last = generated_window(unit)
            extent = generated_decoded_extent(unit)
            rresp_name, _bresp_name = generated_past_extent_resp(unit)
            assert rresp_name == "DECERR", f"{unit}: RDL past-extent rresp {rresp_name}"
            past = LOCAL_BASE + first + extent
            top = (LOCAL_BASE + last) & ~0x3
            assert LOCAL_BASE + first < past < top, f"{unit}: past 0x{past:x} top 0x{top:x}"
            targets.append((label, unit, past, top))
        self._expect_decerr(*(a for _l, _u, past, top in targets for a in (past, top)))
        for port in PORTS:
            for label, unit, past, top in targets:
                _rr, declared = generated_past_extent_resp(unit)
                for where, addr in (("PAST", past), ("TOP", top)):
                    rd = await self._xfer(
                        port,
                        f"{label}_{where}",
                        SmcSysAxiOp.READ,
                        addr,
                        expect_resp=AXI_RESP_DECERR,
                    )
                    got = rd.rdata & 0xFFFF_FFFF
                    assert got == PAST_EXTENT_RDATA, (
                        f"{port} {label} {where} @ 0x{addr:08x}: rdata 0x{got:08x}, "
                        f"want 0x{PAST_EXTENT_RDATA:08x}"
                    )
                    wr = await self._xfer(
                        port,
                        f"{label}_{where}",
                        SmcSysAxiOp.WRITE,
                        addr,
                        wdata=WRITE_PATTERN,
                        tolerate=True,
                    )
                    rows.append(
                        f"{port}:{label}.{where}@0x{addr:08X} rresp=DECERR rdata=0x{got:08X} "
                        f"bresp_declared={declared} bresp_observed={_RESP_NAMES[wr.resp_code]}"
                    )
        self._mark_step("S7")
        self.past_text = "; ".join(rows)

    async def _step_restore(self) -> None:
        await self._write_region_size("RESTORE", REGION_SIZE_RESET)
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE", INBOUND0_FILTER_CONFIG, FILTER_CONFIG_RESET, length=8
        )
        await self.csr_write("INBOUND0_START_RESTORE", INBOUND0_START, FILTER_START_RESET, length=8)
        await self.csr_write("INBOUND0_END_RESTORE", INBOUND0_END, FILTER_END_RESET, length=8)
        await self.csr_read(
            "INBOUND0_START_RESTORE_RB", INBOUND0_START, expected=FILTER_START_RESET, length=8
        )
        await self.csr_read(
            "INBOUND0_END_RESTORE_RB", INBOUND0_END, expected=FILTER_END_RESET, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CONFIG_RESET,
            length=8,
        )
        self.watch.stop = True
        self._mark_step("RESTORED")

    async def body(self) -> None:
        await self._step_setup()
        text = await self._step_reset_decerr()
        self._log_chk("CHK-CLUSTER-UNITS-RESET-DECERR", text)
        text = await self._step_remap_regions()
        self._log_chk("CHK-REMAP-REGION-WIDENED-DECERR", text)
        text = await self._step_jtag_observe()
        self._log_chk("CHK-REMAP-REGION-JTAG-OBSERVE", text)
        text = await self._step_decoded_after_widen()
        self._log_chk("CHK-CLUSTER-UNITS-DECODED-AFTER-WIDEN", text)
        text = await self._step_last_registers()
        self._log_chk("CHK-CLUSTER-UNITS-LAST-REGISTER", text)
        await self._step_past_extent()
        await self._step_restore()
        self._log_chk(
            "CHK-CLUSTER-UNITS-PAST-EXTENT",
            f"{self.past_text}; REGION_SIZE restored to 0x{REGION_SIZE_RESET:X} (saved "
            f"0x{self.region_size_saved:X}) and read back, inbound filter entry 0 restored to its "
            f"reset words",
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses on sep_axi_in, sys_axi_in and jtag_axi_in each bounded "
            "by the driver timeout %d ns (allow_timeout False), all answered; output_axi probe "
            "sampler is a free-running task with no wait on a proof path, %d samples, stopped "
            "after the restore; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.watch.samples,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        chk_steps = ("S2", "S3", "S4", "S5", "S6", "RESTORED")
        for (chk_id, when), step in zip(self._chk_marks, chk_steps):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; stamps %s",
            _FENCE,
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
