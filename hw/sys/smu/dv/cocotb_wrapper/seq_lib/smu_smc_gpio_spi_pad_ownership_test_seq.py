# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP SPI host ownership of GPIO pads 0-3, 8 and 9, lsio_disable, and the undriven pads.

Spec: doc/integrator/src/smu-sep.adoc:236-270 (pads 0-3, 8, 9 driven by the SPI host; 4-7, 10 and
54 not driven; lsio_disable returns a pad to register control), hw/ip/gpio/regs/gpio_intf.rdl:62-111
(DATA_CTRL fields, lsio_enable read-only, the LSIO request outranks interface_enable).
The active level of the boundary enables core2pad_en_o / pad2core_en_o is not observed (no
bench tap).
The DATA_CTRL lsio_enable of the undriven pads is logged only.
"""

from __future__ import annotations

import math

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_bounded,
    axi_write32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_boundary_regs import gpio_intf_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_filter_helpers import (
    PASS_RW_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

DATA_CTRL_SYM = "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR"
LANES = smc_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_NUM")


def _field(name: str) -> int:
    return gpio_intf_u32(f"GPIO_INTF__DATA_CTRL__{name}_bm")


CORE2PAD = _field("CORE2PAD")
INTERFACE_ENABLE = _field("INTERFACE_ENABLE")
INTERRUPT_ENABLE = _field("INTERRUPT_ENABLE")
LSIO_DISABLE = _field("LSIO_DISABLE")
LSIO_ENABLE = _field("LSIO_ENABLE")
_RXTX_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
TX_ONLY = 0b01 << _RXTX_BP
RX_ONLY = 0b10 << _RXTX_BP
RX_TX = 0b11 << _RXTX_BP

HOST_PADS = (0, 1, 2, 3, 8, 9)
DISABLE_PADS = (0, 8, 9)
UNDRIVEN_PADS = (4, 5, 6, 7, 10, 54)

SETTLE_BOUND = 64
AXI_RESP_BOUND_CLK = 256
J2A_POLL_LIMIT = 128
J2A_WRITE_FLOOR = 4
J2A_SITE_COUNT = J2A_WRITE_FLOOR + 1
HOLD_SITE_COUNT = len(HOST_PADS) * 2 + len(DISABLE_PADS) + len(UNDRIVEN_PADS) * 2
WAIT_SITE_COUNT = len(DISABLE_PADS) * 4 + len(UNDRIVEN_PADS) * 2
AXI_ACCESS_FLOOR = (
    len(UNDRIVEN_PADS) * 1 + len(HOST_PADS) * 3 + len(DISABLE_PADS) * 7 + len(UNDRIVEN_PADS) * 5
)


class smu_smc_gpio_spi_pad_ownership_test_seq:
    """Drive DATA_CTRL of the SPI-host and undriven pads and compare levels and lanes."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.step_ts: dict[str, float] = {}
        self.sites: list[dict] = []
        self.master = None
        self.jtag = None
        self.dc_before: dict[int, int] = {}
        self.undriven_before = 0
        self.axi_timeout_ns = math.ceil(AXI_RESP_BOUND_CLK * self.cfg.smu_clk_period_ns)

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await ClockCycles(self.dut.clk_smu_i, 1)
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, name: str, bound: int, used: int, last: str, unit: str, kind: str) -> None:
        self.sites.append(
            {"name": name, "bound": bound, "used": used, "last": last, "unit": unit, "kind": kind}
        )

    async def _j2a(self, name: str, write: bool, addr: int, value: int = 0) -> int:
        t0 = get_sim_time("ns")
        try:
            if write:
                status, _ = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    value,
                    wstrb=0x0F,
                    size=SMC_DBG_AXSIZE_4B,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag,
                    addr,
                    size=SMC_DBG_AXSIZE_4B,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
        except TimeoutError as exc:
            self._site(
                f"j2a_{name}",
                J2A_POLL_LIMIT,
                J2A_POLL_LIMIT + 1,
                f"EXPIRED poll_limit={J2A_POLL_LIMIT} {exc}",
                "polls",
                "j2a",
            )
            raise
        require_jtag_tdo_resolved(f"J2A {name} @0x{addr:08x}")
        elapsed = get_sim_time("ns") - t0
        self._site(
            f"j2a_{name}",
            J2A_POLL_LIMIT,
            0,
            f"status={status} completed within poll_limit={J2A_POLL_LIMIT} elapsed_ns={elapsed}",
            "polls",
            "j2a",
        )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {name} status={status} want {J2A_STATUS_SUCCESS}")
        return 0 if write else int(raw) & 0xFFFF_FFFF

    def _ns_to_clk(self, ns: float) -> int:
        return math.ceil(ns / self.cfg.smu_clk_period_ns)

    async def _wr(self, pad: int, value: int, label: str) -> None:
        addr = smc_indexed_addr(DATA_CTRL_SYM, pad)
        name = f"axi_wr_{label}"
        t0 = get_sim_time("ns")
        try:
            resp = await axi_write32_resp_bounded(
                self.master, addr, value, label=label, timeout_ns=self.axi_timeout_ns
            )
        except AssertionError:
            self._site(
                name,
                AXI_RESP_BOUND_CLK,
                AXI_RESP_BOUND_CLK + 1,
                f"EXPIRED no response within {AXI_RESP_BOUND_CLK} clk ({self.axi_timeout_ns} ns) "
                f"addr=0x{addr:08x}",
                "clk",
                "axi",
            )
            raise
        used = self._ns_to_clk(get_sim_time("ns") - t0)
        self._site(name, AXI_RESP_BOUND_CLK, used, f"bresp={resp_name(resp)}", "clk", "axi")
        if resp != RESP_OKAY:
            raise AssertionError(f"{label} write bresp={resp_name(resp)}")

    async def _rd(self, pad: int, label: str) -> int:
        addr = smc_indexed_addr(DATA_CTRL_SYM, pad)
        name = f"axi_rd_{label}"
        t0 = get_sim_time("ns")
        try:
            data, resp = await axi_read32_resp_bounded(
                self.master, addr, label=label, timeout_ns=self.axi_timeout_ns
            )
        except AssertionError:
            self._site(
                name,
                AXI_RESP_BOUND_CLK,
                AXI_RESP_BOUND_CLK + 1,
                f"EXPIRED no response within {AXI_RESP_BOUND_CLK} clk ({self.axi_timeout_ns} ns) "
                f"addr=0x{addr:08x}",
                "clk",
                "axi",
            )
            raise
        used = self._ns_to_clk(get_sim_time("ns") - t0)
        data = int(data) & 0xFFFF_FFFF
        self._site(
            name,
            AXI_RESP_BOUND_CLK,
            used,
            f"rresp={resp_name(resp)} rdata=0x{data:08x}",
            "clk",
            "axi",
        )
        if resp != RESP_OKAY:
            raise AssertionError(f"{label} read rresp={resp_name(resp)}")
        return data

    async def _await(self, name: str, getter, want: int) -> int:
        """Wait up to SETTLE_BOUND clk for getter() == want; an expiry is recorded, not raised."""
        value = getter()
        waited = 0
        while value != want and waited < SETTLE_BOUND:
            await ClockCycles(self.dut.clk_smu_i, 1)
            waited += 1
            value = getter()
        used = waited if value == want else SETTLE_BOUND + 1
        self._site(
            name,
            SETTLE_BOUND,
            used,
            f"waited={waited} clk value={value} want={want}",
            "clk",
            "wait",
        )
        return value

    async def _hold(self, name: str, getter, want: int) -> int:
        """Observe getter() for SETTLE_BOUND clk; stop at the first value that differs from want."""
        value = getter()
        observed = 0
        while value == want and observed < SETTLE_BOUND:
            await ClockCycles(self.dut.clk_smu_i, 1)
            observed += 1
            value = getter()
        self._site(
            name,
            SETTLE_BOUND,
            observed,
            f"observed={observed} clk value={value} want={want}",
            "clk",
            "hold",
        )
        return value

    def _level(self, pad: int) -> int:
        return (sample(self.dut.gpio_pad_io, "gpio_pad_io") >> pad) & 1

    def _irq(self, pad: int) -> int:
        return (sample(self.dut.tb_gpio_interrupt, "tb_gpio_interrupt") >> pad) & 1

    def _drive_pad(self, pad: int, high: bool) -> tuple[int, int]:
        en_before = int(self.dut.tb_gpio_drive_en.value)
        val_before = int(self.dut.tb_gpio_drive_val.value)
        bit = 1 << pad
        self.dut.tb_gpio_drive_en.value = en_before | bit
        self.dut.tb_gpio_drive_val.value = (val_before | bit) if high else (val_before & ~bit)
        return en_before, val_before

    async def _s1(self, sb) -> None:
        dut = self.dut
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        await self._j2a(
            "global_base_wr", True, SMC_APERTURE_GLOBAL_BASE_REG, SMC_APERTURE_LOCAL_BASE
        )
        rb = await self._j2a("global_base_rd", False, SMC_APERTURE_GLOBAL_BASE_REG)
        sb.expect_eq("SMC aperture GLOBAL_BASE=LOCAL_BASE", rb, SMC_APERTURE_LOCAL_BASE)
        first = smc_indexed_addr(DATA_CTRL_SYM, 0)
        last = smc_indexed_addr(DATA_CTRL_SYM, LANES - 1)
        await self._j2a("inbound0_start", True, INBOUND0_START, first)
        await self._j2a("inbound0_end", True, INBOUND0_END, last + 4)
        await self._j2a("inbound0_config", True, INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG)
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        for pad in UNDRIVEN_PADS:
            await self._wr(pad, INTERRUPT_ENABLE, f"pad{pad}_irq_en")

    def _level_of(self, pad: int):
        return lambda: self._level(pad)

    def _irq_of(self, pad: int):
        return lambda: self._irq(pad)

    async def _s2(self, sb) -> None:
        obs = []
        for pad in HOST_PADS:
            dc = await self._rd(pad, f"pad{pad}_dc")
            lsio = int(bool(dc & LSIO_ENABLE))
            self.dc_before[pad] = lsio
            self._log(f"CELL pad_{pad} lsio_enable={lsio} data_ctrl=0x{dc:08x}")
            lvl = self._level_of(pad)
            before = lvl()
            word = INTERFACE_ENABLE | RX_TX
            await self._wr(pad, word | CORE2PAD, f"pad{pad}_own_c2p1")
            after1 = await self._hold(f"pad{pad}_own_c2p1_level", lvl, before)
            await self._wr(pad, word, f"pad{pad}_own_c2p0")
            after0 = await self._hold(f"pad{pad}_own_c2p0_level", lvl, before)
            self._log(
                f"CELL pad_{pad} level_before={before} level_c2p1={after1} level_c2p0={after0}"
            )
            obs.append((pad, lsio, after1 == before, after0 == before))
        self.owned = obs
        sb.expect_eq(
            f"CHK-DBG-GPIO-SPI-OWNED (pad, lsio_enable, c2p1 unchanged, c2p0 unchanged)={obs}",
            obs,
            [(p, 1, True, True) for p in HOST_PADS],
            evidence="DBG_GPIO_SPI_OWNED",
        )

    async def _s3(self, sb) -> None:
        self._log("CELL core2pad_en/pad2core_en level unobservable (no bench tap)")
        obs = []
        self.disabled = {}
        for pad in DISABLE_PADS:
            lvl = self._level_of(pad)
            irq = self._irq_of(pad)
            word = LSIO_DISABLE | INTERFACE_ENABLE | RX_TX
            await self._wr(pad, word, f"pad{pad}_dis_set")
            dc = await self._rd(pad, f"pad{pad}_dis_dc")
            lsio_after = int(bool(dc & LSIO_ENABLE))
            await self._wr(pad, word | CORE2PAD, f"pad{pad}_dis_c2p1")
            level1 = await self._await(f"pad{pad}_dis_c2p1_level", lvl, 1)
            await self._wr(pad, word, f"pad{pad}_dis_c2p0")
            level0 = await self._await(f"pad{pad}_dis_c2p0_level", lvl, 0)
            base = LSIO_DISABLE | INTERFACE_ENABLE
            await self._wr(pad, base | TX_ONLY | CORE2PAD, f"pad{pad}_dis_tx")
            tx_high = await self._await(f"pad{pad}_dis_tx_level", lvl, 1)
            en_before, val_before = self._drive_pad(pad, True)
            try:
                await self._wr(pad, base | RX_ONLY | INTERRUPT_ENABLE, f"pad{pad}_dis_rx")
                rx_irq = await self._await(f"pad{pad}_dis_rx_irq", irq, 1)
                await self._wr(pad, base | INTERRUPT_ENABLE, f"pad{pad}_dis_none")
                none_irq = await self._hold(f"pad{pad}_dis_none_irq", irq, 0)
            finally:
                self.dut.tb_gpio_drive_en.value = en_before
                self.dut.tb_gpio_drive_val.value = val_before
            self._log(
                f"CELL pad_{pad} lsio_enable_before={self.dc_before[pad]} "
                f"lsio_enable_after={lsio_after} level_c2p1={level1} level_c2p0={level0} "
                f"tx_only_level={tx_high} rx_only_irq={rx_irq} rx_none_irq={none_irq}"
            )
            self.disabled[pad] = (level1, level0)
            obs.append(
                (pad, self.dc_before[pad], lsio_after, level1, level0, tx_high, rx_irq, none_irq)
            )
        sb.expect_eq(
            "CHK-DBG-GPIO-SPI-DISABLE (pad, lsio_enable before, after, level c2p1, level c2p0, "
            f"tx-only level, rx-only irq, no-enable irq)={obs}",
            obs,
            [(p, 1, 0, 1, 0, 1, 1, 0) for p in DISABLE_PADS],
            evidence="DBG_GPIO_SPI_DISABLE",
        )

    async def _undriven_pass(self, pad: int, disable: int) -> tuple[int, int]:
        """Transmit leg then receive leg of one pad; returns (pad level after tx, irq lane)."""
        base = disable | INTERFACE_ENABLE
        tag = "dis" if disable else "own"
        lvl = self._level_of(pad)
        irq = self._irq_of(pad)
        await self._wr(pad, base | TX_ONLY | CORE2PAD, f"pad{pad}_{tag}_tx")
        if disable:
            tx_level = await self._await(f"pad{pad}_{tag}_tx_level", lvl, 1)
        else:
            tx_level = await self._hold(f"pad{pad}_{tag}_tx_level", lvl, self.undriven_before)
        en_before, val_before = self._drive_pad(pad, True)
        try:
            await self._wr(pad, base | RX_ONLY | INTERRUPT_ENABLE, f"pad{pad}_{tag}_irq")
            if disable:
                irq_value = await self._await(f"pad{pad}_{tag}_irq_lane", irq, 1)
            else:
                irq_value = await self._hold(f"pad{pad}_{tag}_irq_lane", irq, 0)
        finally:
            self.dut.tb_gpio_drive_en.value = en_before
            self.dut.tb_gpio_drive_val.value = val_before
        return tx_level, irq_value

    async def _s4(self, sb) -> None:
        obs = []
        for pad in UNDRIVEN_PADS:
            before = self._level(pad)
            self.undriven_before = before
            tx_level, irq = await self._undriven_pass(pad, 0)
            self._log(
                f"CELL pad_{pad} lsio_disable=0 level_before={before} level_tx={tx_level} irq={irq}"
            )
            tx_dis, irq_dis = await self._undriven_pass(pad, LSIO_DISABLE)
            dc = await self._rd(pad, f"pad{pad}_und_dc")
            self._log(
                f"CELL pad_{pad} lsio_enable={int(bool(dc & LSIO_ENABLE))} "
                f"lsio_disable=1 level_tx={tx_dis} irq={irq_dis}"
            )
            obs.append((pad, tx_level == before, irq, tx_dis, irq_dis))
        sb.expect_eq(
            "CHK-DBG-GPIO-SPI-UNDRIVEN (pad, tx unchanged, irq, tx level disabled, irq disabled)="
            f"{obs}",
            obs,
            [(p, True, 0, 1, 1) for p in UNDRIVEN_PADS],
            evidence="DBG_GPIO_SPI_UNDRIVEN",
        )

    def _s5(self, sb) -> None:
        changed_with_request = tuple(
            not (a and b) for p, _, a, b in self.owned if p in DISABLE_PADS
        )
        for pad, flag in zip(DISABLE_PADS, changed_with_request):
            self._log(f"CELL interface_enable_with_spi_request pad={pad} changed={flag}")
        after = tuple(self.disabled[p] == (1, 0) for p in DISABLE_PADS)
        for pad, flag in zip(DISABLE_PADS, after):
            self._log(f"CELL lsio_disable_then_register_value pad={pad} changed={flag}")
        sb.expect_eq(
            "CHK-DBG-GPIO-SPI-PRIORITY (changed with SPI request, changed after lsio_disable)",
            (changed_with_request, after),
            ((False,) * 3, (True,) * 3),
            evidence="DBG_GPIO_SPI_PRIORITY",
        )

    def _s6(self, sb) -> None:
        expired = [s["name"] for s in self.sites if s["used"] > s["bound"]]
        for s in self.sites:
            state = "EXPIRED" if s["used"] > s["bound"] else "ok"
            self._log(
                f"TIMEOUT-PATH {s['name']}: bound={s['bound']} {s['unit']} used={s['used']} "
                f"{state} last={s['last']}"
            )
        finite = all(isinstance(s["bound"], int) and s["bound"] > 0 for s in self.sites)
        has_last = all(s["last"] for s in self.sites)
        axi_bounds = {s["bound"] for s in self.sites if s["kind"] == "axi"}
        kind_counts = {
            kind: sum(1 for s in self.sites if s["kind"] == kind)
            for kind in ("j2a", "axi", "wait", "hold")
        }
        want_counts = {
            "j2a": J2A_SITE_COUNT,
            "axi": AXI_ACCESS_FLOOR,
            "wait": WAIT_SITE_COUNT,
            "hold": HOLD_SITE_COUNT,
        }
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={len(expired)} "
            f"axi_timeout_ns={self.axi_timeout_ns} axi_bound_clk={AXI_RESP_BOUND_CLK}"
        )
        sb.expect_eq(
            f"CHK-TIMEOUT-PATHS expired={expired} bounds_finite={finite} last_state={has_last} "
            f"site_counts={kind_counts}",
            (expired, finite, has_last, kind_counts, axi_bounds),
            ([], True, True, want_counts, {AXI_RESP_BOUND_CLK}),
            evidence="CHK_TIMEOUT_PATHS",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self._mark(
            "S1", "SETUP: aperture, INBOUND0 over DATA_CTRL, interrupt_enable on pads 4-7/10/54"
        )
        await self._s1(sb)
        await self._mark("S2", "SPI-host pads ignore core2pad with lsio_disable clear")
        await self._s2(sb)
        await self._mark("S3", "lsio_disable returns pads 0, 8, 9 to register control")
        await self._s3(sb)
        await self._mark("S4", "pads 4-7, 10, 54 are not driven by the SPI host")
        await self._s4(sb)
        await self._mark("S5", "priority table from the S2 and S3 records")
        self._s5(sb)
        await self._mark("S6", "TIMEOUT: bounded waits and last state")
        self._s6(sb)
        await self._mark("PASS", "fence end")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        j2a_n = sum(1 for s in self.sites if s["kind"] == "j2a" and not s["name"].endswith("_rd"))
        axi_n = sum(1 for s in self.sites if s["kind"] == "axi")
        span = self.step_ts["PASS"] - self.step_ts["S1"]
        self._log(
            f"CHK-NONVAC: PASS (ordered sim-time fence S1<S2<S3<S4<S5<S6<PASS) span_ns={span} "
            f"j2a_accesses={j2a_n} axi_accesses={axi_n} floor_j2a={J2A_WRITE_FLOOR} "
            f"floor_axi={AXI_ACCESS_FLOOR}"
        )
        sb.expect_eq(
            "CHK-NONVAC access counts and span (j2a writes, axi accesses, span > 0)",
            (j2a_n, axi_n, span > 0),
            (J2A_WRITE_FLOOR, AXI_ACCESS_FLOOR, True),
            evidence="CHK-NONVAC",
        )
        self.done = True
