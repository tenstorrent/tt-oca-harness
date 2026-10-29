# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC inbound responses for between-unit, past-extent and M-mode/Xvisor addresses. SEP=1, no Force.

Spec: hw/sys/smc/regs/smc_memory_map.rdl (ocah_gap_resp, ocah_window_resp,
ocah_past_extent_resp, ocah_aperture_size), the generated SMC memory map,
hw/sys/smc/doc/memmap.adoc (Address Space Organization), doc/integrator/src/smu-smc.adoc.
The BRESP at BASE+0x001_7000 and BASE+0x001_7FFC is logged as CHK-UNMAP-0X17000-WRITE only.
A past-extent write the map declares DECERR that answers SLVERR is logged as
CHK-UNMAP-PAST-EXTENT-WRITE only.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_DECERR, RESP_SLVERR, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    smc_addr,
    smc_first_past_registers,
    smc_response_past_registers,
)
from seq_lib.smu_axi_helpers import (
    AXI_TIMEOUT_NS,
    axi_read32_resp_bounded,
    axi_write32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_filter_helpers import (
    PASS_RW_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
    SMC_APERTURE_REGION_SIZE_REG,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

BASE = SMC_APERTURE_LOCAL_BASE
WIDE_REGION_SIZE = 0x0400_0000
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
BAR_START = BASE
BAR_END = BASE + WIDE_REGION_SIZE - 1
GAP_RDATA = 0xBADCAB1E

# ocah_aperture_size of dfx_ctrl (smc.rdl) ends the last mapped aperture before the unmapped
# range that runs up to smc_base_config.
_GAP_START = smc_addr("SMC_TOP_DFX_CTRL_BASE_ADDR") + 0x800
_GAP_END = smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR")
GAP_ADDRS = (_GAP_START, (_GAP_START + _GAP_END) // 2)
EXCEPTION_ADDRS = (BASE + 0x001_7000, BASE + 0x001_7FFC)
MMODE_ADDR = BASE + 0x100_0000
XVISOR_ADDR = BASE + 0x180_0000


# Units probed at the first word past their registers. The address and the expected
# response come from the generated SMC memory map: the unit itself inside its decode
# window, the fabric's past-extent response beyond it.
PAST_EXTENT_UNITS = (
    "smc_reset_unit",
    "smc_misc_wrap",
    "gpio_intf",
    "smc_base_config",
    "smc_alias_remap",
    "dfx_ctrl",
    "smc_mailbox",
    "dma_ctrl",
    "zeroer_ctrl",
    "smc_cpu_ctrl",
    "smc_cluster_core0_wdt",
)
_RESP_CODES = {"OKAY": 0, "SLVERR": RESP_SLVERR, "DECERR": RESP_DECERR}

J2A_POLL_LIMIT = 128
REGION_POLL_CYCLES = 64
SITES = ("j2a", "region_poll", "axi_rd", "axi_wr")


class smu_smc_unmapped_response_test_seq:
    """Probe unmapped SMC offsets from ext_in and prove the responses."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.counts: dict[str, int] = {}
        self.last: dict[str, str] = {}
        self.expired: list[str] = []
        self.master = None
        self.jtag = None

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _site(self, site: str, last: str) -> None:
        self.counts[site] = self.counts.get(site, 0) + 1
        self.last[site] = last

    def _expire(self, site: str, bound: str, exc: Exception) -> None:
        line = f"{site}: bound={bound} EXPIRED last={exc}"
        self.expired.append(site)
        self._log(f"TIMEOUT-PATH {line}")

    async def _axi_wr(self, addr: int, value: int, label: str) -> int:
        try:
            resp = await axi_write32_resp_bounded(self.master, addr, value, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi_wr", f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        self._site("axi_wr", f"bresp={resp_name(resp)} addr=0x{addr:08x}")
        return resp

    async def _axi_rd(self, addr: int, label: str) -> tuple[int, int]:
        try:
            data, resp = await axi_read32_resp_bounded(self.master, addr, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi_rd", f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        data = int(data) & 0xFFFF_FFFF
        self._site("axi_rd", f"rresp={resp_name(resp)} rdata=0x{data:08x} addr=0x{addr:08x}")
        return data, resp

    async def _j2a(
        self, write: bool, addr: int, data: int = 0, *, size: int = SMC_DBG_AXSIZE_8B, wstrb=0xFF
    ) -> tuple[int, int]:
        kind = "WR" if write else "RD"
        try:
            if write:
                status, rdata = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    data,
                    wstrb=wstrb,
                    size=size,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
            else:
                status, rdata = await jtag2axi_single_read(
                    self.jtag,
                    addr,
                    size=size,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
        except TimeoutError as exc:
            self._expire("j2a", f"{J2A_POLL_LIMIT} polls", exc)
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:08x}")
        self._site("j2a", f"status={status}")
        return status, int(rdata)

    async def _j2a_wr32(self, addr: int, value: int) -> int:
        word = int(value) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        status, _ = await self._j2a(True, addr, packed, size=SMC_DBG_AXSIZE_4B, wstrb=wstrb)
        return status

    async def _j2a_rd32(self, addr: int) -> tuple[int, int]:
        status, raw = await self._j2a(False, addr, size=SMC_DBG_AXSIZE_4B)
        return status, ((raw >> 32) if addr & 0x4 else raw) & 0xFFFF_FFFF

    async def _await_region_size(self, want: int) -> None:
        pin = self.dut.smc_region_size_o
        waited = 0
        while True:
            val = pin.value
            if val.is_resolvable and int(val) == want:
                break
            if waited >= REGION_POLL_CYCLES:
                exc = AssertionError(f"smc_region_size_o={val} want 0x{want:08x}")
                self._expire("region_poll", f"{REGION_POLL_CYCLES} clk", exc)
                raise exc
            await ClockCycles(self.dut.clk_smu_i, 1)
            waited += 1
        self._site("region_poll", f"waited={waited} cycles smc_region_size_o=0x{want:08x}")

    async def _set_region_size(self, size: int, tag: str, sb) -> None:
        st = await self._j2a_wr32(SMC_APERTURE_REGION_SIZE_REG, size)
        sb.expect_eq(f"JTAG2AXI {tag} REGION_SIZE write", st, J2A_STATUS_SUCCESS)
        st, rb = await self._j2a_rd32(SMC_APERTURE_REGION_SIZE_REG)
        sb.expect_eq(f"JTAG2AXI {tag} REGION_SIZE read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq(f"{tag} REGION_SIZE readback", rb, size)
        await self._await_region_size(size)
        self._log(
            f"CELL region_size.{tag} addr=0x{SMC_APERTURE_REGION_SIZE_REG:08x} value=0x{rb:08x}"
        )

    async def _read_cell(self, name: str, addr: int) -> tuple[int, int]:
        data, resp = await self._axi_rd(addr, f"{name} read")
        self._log(f"CELL {name}.read addr=0x{addr:08x} resp={resp_name(resp)} rdata=0x{data:08x}")
        return resp, data

    async def _write_cell(self, name: str, addr: int) -> int:
        resp = await self._axi_wr(addr, 0xA5A5_5A5A, f"{name} write")
        self._log(f"CELL {name}.write addr=0x{addr:08x} resp={resp_name(resp)}")
        return resp

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, aperture, REGION_SIZE 0x0400_0000, BAR window, vip")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        st, _ = await self._j2a(
            True,
            SMC_APERTURE_GLOBAL_BASE_REG,
            SMC_APERTURE_LOCAL_BASE,
            size=SMC_DBG_AXSIZE_4B,
            wstrb=0x0F,
        )
        sb.expect_eq("JTAG2AXI GLOBAL_BASE write", st, J2A_STATUS_SUCCESS)
        st, rb = await self._j2a(False, SMC_APERTURE_GLOBAL_BASE_REG, size=SMC_DBG_AXSIZE_4B)
        sb.expect_eq("JTAG2AXI GLOBAL_BASE read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "SMC aperture GLOBAL_BASE=LOCAL_BASE", rb & 0xFFFF_FFFF, SMC_APERTURE_LOCAL_BASE
        )
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        await self._set_region_size(WIDE_REGION_SIZE, "WIDE", sb)
        for addr, data, name in (
            (INBOUND0_START, BAR_START, "BAR_START"),
            (INBOUND0_END, BAR_END, "BAR_END"),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "BAR_CONFIG"),
        ):
            st, _ = await self._j2a(True, addr, data)
            sb.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)
        st, cfg_rb = await self._j2a(False, INBOUND0_FILTER_CONFIG)
        sb.expect_eq("JTAG2AXI BAR_CONFIG read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq("INBOUND0 FILTER_CONFIG readback", cfg_rb & 0xFFFF_FFFF, PASS_RW_CONFIG)
        self._log(
            f"CELL bar addr=0x{BAR_START:08x}..0x{BAR_END:08x} config=0x{cfg_rb & 0xFFFFFFFF:08x}"
        )
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        self._mark("S2", "between-unit reads and writes")
        gap_obs = {}
        gap_exp = {}
        for i, addr in enumerate(GAP_ADDRS):
            name = f"gap{i}"
            resp, data = await self._read_cell(name, addr)
            gap_obs[f"{name}.read"] = (resp, data)
            gap_exp[f"{name}.read"] = (RESP_DECERR, GAP_RDATA)
            gap_obs[f"{name}.write"] = await self._write_cell(name, addr)
            gap_exp[f"{name}.write"] = RESP_DECERR
        for addr in EXCEPTION_ADDRS:
            name = f"gap-0x{addr - BASE:x}"
            resp, data = await self._read_cell(name, addr)
            gap_obs[f"{name}.read"] = (resp, data)
            gap_exp[f"{name}.read"] = (RESP_DECERR, GAP_RDATA)
            bresp = await self._write_cell(name, addr)
            self._log(f"CHK-UNMAP-0X17000-WRITE: addr=0x{addr:08x} bresp={resp_name(bresp)}")
        sb.expect_eq(
            "CHK-UNMAP-BETWEEN gap reads DECERR/0xBADCAB1E, gap writes DECERR",
            gap_obs,
            gap_exp,
            evidence="CHK-UNMAP-BETWEEN",
        )

        self._mark("S3", "past-extent reads and writes")
        past_obs = {}
        past_exp = {}
        for name in PAST_EXTENT_UNITS:
            addr = smc_first_past_registers(name)
            want = smc_response_past_registers(name, addr)
            resp, data = await self._read_cell(name, addr)
            past_obs[f"{name}.read"] = (resp, data)
            past_exp[f"{name}.read"] = (_RESP_CODES[want["rresp"]], want["rdata"] & 0xFFFF_FFFF)
            bresp = await self._write_cell(name, addr)
            # Where the map states DECERR the AXI-Lite crossbars refuse a write with SLVERR
            # (SF-001); that answer is logged, not compared.
            if want["bresp"] == "DECERR" and bresp == RESP_SLVERR:
                self._log(
                    f"CHK-UNMAP-PAST-EXTENT-WRITE: block={name} addr=0x{addr:08x} "
                    f"bresp={resp_name(bresp)}"
                )
                continue
            past_obs[f"{name}.write"] = bresp
            past_exp[f"{name}.write"] = _RESP_CODES[want["bresp"]]
        sb.expect_eq(
            "CHK-UNMAP-PAST-EXTENT reads and writes answer the generated SMC memory map",
            past_obs,
            past_exp,
            evidence="CHK-UNMAP-PAST-EXTENT",
        )

        self._mark("S4", "M-mode and Xvisor windows from ext_in")
        win_obs = {}
        win_exp = {}
        for name, addr in (("mmode", MMODE_ADDR), ("xvisor", XVISOR_ADDR)):
            resp, _ = await self._read_cell(name, addr)
            win_obs[f"{name}.read"] = resp
            win_obs[f"{name}.write"] = await self._write_cell(name, addr)
            win_exp[f"{name}.read"] = RESP_DECERR
            win_exp[f"{name}.write"] = RESP_DECERR
        sb.expect_eq(
            "CHK-UNMAP-MMODE-XVISOR windows answer DECERR to ext_in",
            win_obs,
            win_exp,
            evidence="CHK-UNMAP-MMODE-XVISOR",
        )

        self._mark("S5", "restore REGION_SIZE and clear INBOUND0")
        await self._set_region_size(REGION_SIZE_RESET, "RESTORE", sb)
        st, _ = await self._j2a(True, INBOUND0_FILTER_CONFIG, 0)
        sb.expect_eq("JTAG2AXI INBOUND0_CONFIG clear", st, J2A_STATUS_SUCCESS)

        self._mark("S6", "TIMEOUT: bounded waits and last state")
        bounds = {
            "j2a": f"{J2A_POLL_LIMIT} polls",
            "region_poll": f"{REGION_POLL_CYCLES} clk",
            "axi_rd": f"{AXI_TIMEOUT_NS}ns",
            "axi_wr": f"{AXI_TIMEOUT_NS}ns",
        }
        paths = []
        for site in SITES:
            if site not in self.last:
                raise AssertionError(f"bounded wait site {site} never ran")
            state = "EXPIRED" if site in self.expired else "ok"
            paths.append(
                f"{site}: bound={bounds[site]} {state} accesses={self.counts[site]} "
                f"last={self.last[site]}"
            )
        for line in paths:
            self._log(f"TIMEOUT-PATH {line}")
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(paths)} expired={len(self.expired)} "
            f"j2a_accesses_counted_at_call_sites={self.counts['j2a']}"
        )
        sb.expect_eq(
            "expired TIMEOUT-PATH records", len(self.expired), 0, evidence="CHK_TIMEOUT_PATHS"
        )
        self.done = True
