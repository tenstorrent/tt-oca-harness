# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Supplementary GPIO blocks of the external window and the eFuse SHIM boundary.

Spec sources: hw/sys/smc/doc/memmap.adoc (AXI-Lite External Window),
hw/sys/smc/regs/include/smc_external_supplementary.rdl, generated smc_addr.h.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import external_gpio_ctrl_addr, smc_addr
from .smc_decode_probe_utils import AXI_RESP_DECERR, SmcDecodeProbeSeq

INTF_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_INTF_BASE_ADDR")
INTF_SIZE = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_INTF_SIZE")
CTRL_ADDR = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_CTRL_BASE_ADDR")
SHIM_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR")
SHIM_MAP_SIZE = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_SIZE")
ABOVE_SHIM = external_gpio_ctrl_addr(0)

INTF_ADDRS = tuple(INTF_BASE + 4 * i for i in range(INTF_SIZE // 4))
WRITE_DATA = 0xA5A5_5A5A

STEP_ORDER = (
    "BRINGUP_DONE",
    "EXTRA_INTF_ROUTED",
    "EXTRA_CTRL_ROUTED",
    "RESPONSES_PRINTED",
    "SHIM_BOUNDARY",
)
CHK_ORDER = (
    ("EXTRA_INTF_ROUTED", "CHK-GPIO-EXT-EXTRA-INTF-ROUTED"),
    ("EXTRA_CTRL_ROUTED", "CHK-GPIO-EXT-EXTRA-CTRL-ROUTED"),
    ("RESPONSES_PRINTED", "CHK-GPIO-EXT-EXTRA-RESPONSE"),
    ("SHIM_BOUNDARY", "CHK-GPIO-EXT-EXTRA-SHIM-BOUNDARY"),
)
EXPECTED_ACCESSES = 8


class smc_gpio_ext_extra_decode_test_seq(SmcDecodeProbeSeq):
    """Forwarding of gpio_extra_intf / gpio_extra_ctrl and the SHIM window boundary."""

    def __init__(self, name: str = "smc_gpio_ext_extra_decode_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        # (label, kind, addr, resp, rdata or None, request cycles)
        self.rows: list[tuple[str, str, int, int, int | None, int]] = []

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, addr: int) -> None:
        label = f"EXTRA_RD_{addr:08X}"
        rdata, hits = await self.read_external_routed(label, addr, decerr=True)
        self.rows.append((label, "read", addr, AXI_RESP_DECERR, rdata, hits))

    async def _write(self, addr: int) -> None:
        label = f"EXTRA_WR_{addr:08X}"
        resp, hits = await self.write_external_routed(label, addr, WRITE_DATA)
        assert resp == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: answered resp={resp}, expected DECERR ({AXI_RESP_DECERR})"
        )
        self.rows.append((label, "write", addr, resp, None, hits))

    def _routed_text(self, rows) -> str:
        return "; ".join(
            f"{k} 0x{a:08x} presented on the external-port {'ar' if k == 'read' else 'aw'} "
            f"channel for {h} clk_smc_i cycle(s)"
            for _l, k, a, _r, _d, h in rows
        )

    async def _s1(self) -> None:
        await self.wait_fuse_sense_done()
        assert len(INTF_ADDRS) == 3 and INTF_ADDRS[-1] + 4 == CTRL_ADDR, (
            f"generated map: gpio_extra_intf {[hex(a) for a in INTF_ADDRS]}, "
            f"gpio_extra_ctrl 0x{CTRL_ADDR:08x}"
        )
        assert ABOVE_SHIM >= SHIM_BASE + SHIM_MAP_SIZE, (
            f"first block above the SHIM 0x{ABOVE_SHIM:08x} overlaps the SHIM block"
        )
        self.env.axi_monitor.expected_decerr_addrs.update(set(INTF_ADDRS) | {CTRL_ADDR, ABOVE_SHIM})
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._mark("BRINGUP_DONE")

    async def _s2(self) -> str:
        for addr in INTF_ADDRS:
            await self._read(addr)
            await self._write(addr)
        rows = self.rows[:6]
        assert len(rows) == 6 and all(r[5] > 0 for r in rows), f"intf probes {rows}"
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._mark("EXTRA_INTF_ROUTED")
        return "six probes: " + self._routed_text(rows)

    async def _s3(self) -> str:
        await self._read(CTRL_ADDR)
        await self._write(CTRL_ADDR)
        rows = self.rows[6:]
        assert len(rows) == 2 and all(r[5] > 0 for r in rows), f"ctrl probes {rows}"
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._mark("EXTRA_CTRL_ROUTED")
        return "two probes: " + self._routed_text(rows)

    async def _s4(self) -> str:
        assert len(self.rows) == EXPECTED_ACCESSES, f"{len(self.rows)} accesses recorded"
        assert all(r[3] == AXI_RESP_DECERR for r in self.rows), f"responses {self.rows}"
        self.assert_all_reachable(EXPECTED_ACCESSES, "GPIO_EXT_EXTRA_DECODE")
        parts = [
            f"{k} 0x{a:08x} resp={r} rdata=" + ("n/a" if d is None else f"0x{d:08x}")
            for _l, k, a, r, d, _h in self.rows
        ]
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._mark("RESPONSES_PRINTED")
        return (
            f"all {EXPECTED_ACCESSES} accesses completed DECERR (3); "
            + "; ".join(parts)
            + "; read data printed (not specified, measured)"
        )

    async def _s5(self) -> str:
        dut = cocotb.top
        for sig in ("tb_axil_efuse_bank_active", "tb_axil_external_arvalid"):
            assert hasattr(dut, sig), f"tb_top lacks {sig}"
        probe = dut.tb_axil_efuse_bank_active
        assert probe.value.is_resolvable and int(probe.value) == 0, (
            f"efuse bank activity before the SHIM read: {probe.value}"
        )
        active = [0]

        async def _sample() -> None:
            while True:
                await RisingEdge(dut.clk_smc_i)
                v = probe.value
                assert v.is_resolvable, "tb_axil_efuse_bank_active unresolved"
                if int(v):
                    active[0] += 1

        out: list[tuple[int, int]] = []

        async def _shim() -> None:
            out.append(await self.read_any("SHIM_BASE", SHIM_BASE))

        sampler = cocotb.start_soon(_sample())
        try:
            shim_hits = await self._count_external_requests(SHIM_BASE, "ar", _shim)
        finally:
            sampler.cancel()
        shim_resp, shim_rdata = out[0]
        assert isinstance(shim_rdata, int), "SHIM read data unresolved"
        assert active[0] > 0, (
            f"tb_axil_efuse_bank_active stayed low during the read of 0x{SHIM_BASE:08x}"
        )
        assert shim_hits == 0, (
            f"SHIM read 0x{SHIM_BASE:08x} reached the external port ({shim_hits} cycles)"
        )
        above_rdata, above_hits = await self.read_external_routed(
            "ABOVE_SHIM", ABOVE_SHIM, decerr=True
        )
        assert above_hits > 0, f"0x{ABOVE_SHIM:08x} never reached the external port"
        await ClockCycles(dut.clk_smc_i, 1)
        self._mark("SHIM_BOUNDARY")
        return (
            f"SHIM base 0x{SHIM_BASE:08x} read resp={shim_resp} rdata=0x{shim_rdata:08x}: "
            f"tb_axil_efuse_bank_active high {active[0]} cycle(s), external-port ar requests "
            f"for it {shim_hits}; first address above the SHIM block 0x{ABOVE_SHIM:08x} "
            f"presented on the external-port ar channel for {above_hits} cycle(s) "
            f"(DECERR rdata=0x{above_rdata:08x})"
        )

    async def body(self) -> None:
        await self._s1()
        cocotb.log.info("BRINGUP_DONE at %d ps", self.steps[-1][1])
        self._chk("EXTRA_INTF_ROUTED", "CHK-GPIO-EXT-EXTRA-INTF-ROUTED", await self._s2())
        self._chk("EXTRA_CTRL_ROUTED", "CHK-GPIO-EXT-EXTRA-CTRL-ROUTED", await self._s3())
        self._chk("RESPONSES_PRINTED", "CHK-GPIO-EXT-EXTRA-RESPONSE", await self._s4())
        self._chk("SHIM_BOUNDARY", "CHK-GPIO-EXT-EXTRA-SHIM-BOUNDARY", await self._s5())
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE < EXTRA_INTF_ROUTED < EXTRA_CTRL_ROUTED < "
            "RESPONSES_PRINTED < SHIM_BOUNDARY; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
