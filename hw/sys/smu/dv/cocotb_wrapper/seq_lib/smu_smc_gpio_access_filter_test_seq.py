# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO bank AxPROT access filter on the external AXI path, pad 11.

Contract SMU_WRAPPER_DEBUG_PATHS_022, anchor smu_smc_gpio_access_filter_test.
Spec: hw/ip/gpio/regs/gpio_intf.rdl:17-52 (ACCESS_FILTER reset 0x0001_0100; with an enable set an
access requires an exact match between AxPROT and the requirement), hw/ip/gpio/doc/memmap.adoc:36,
hw/ip/gpio/regs/gpio_intf.rdl:62-111 (DATA_CTRL), hw/ip/axi_filter/regs/filter_ctrl.rdl:36-42
(an inbound entry matches when AxPROT[1] equals its allow_ns field).
The response code and read data of a refused access are SF-019: they are logged and compared
with OKAY only.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    filter_ctrl_bm,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_boundary_regs import gpio_intf_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_filter_helpers import (
    _F_ALLOW_NS,
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
ACCESS_FILTER_SYM = "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR"
IN_CFG_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
IN_START_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
IN_END_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"
PAD = 11
assert PAD < smc_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_NUM")

DATA_CTRL = smc_indexed_addr(DATA_CTRL_SYM, PAD)
ACCESS_FILTER = smc_indexed_addr(ACCESS_FILTER_SYM, PAD)


def _dc(name: str) -> int:
    return gpio_intf_u32(f"GPIO_INTF__DATA_CTRL__{name}_bm")


def _af(name: str, field: str) -> int:
    return gpio_intf_u32(f"GPIO_INTF__ACCESS_FILTER__{name}_{field}")


CORE2PAD = _dc("CORE2PAD")
DC_READ_ONLY = _dc("LSIO_ENABLE") | _dc("PAD2CORE")
INTERFACE_ENABLE = _dc("INTERFACE_ENABLE")
TX_ONLY = 0b01 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
DC_BASE = INTERFACE_ENABLE | TX_ONLY

WRITE_FILTER_ENABLE = _af("WRITE_FILTER_ENABLE", "bm")
READ_FILTER_ENABLE = _af("READ_FILTER_ENABLE", "bm")
AWPROT_BP = _af("AWPROT_REQUIREMENT", "bp")
ARPROT_BP = _af("ARPROT_REQUIREMENT", "bp")
AF_RESET = sum(
    _af(f, "reset") << _af(f, "bp")
    for f in (
        "WRITE_FILTER_ENABLE",
        "READ_FILTER_ENABLE",
        "AWPROT_REQUIREMENT",
        "ARPROT_REQUIREMENT",
    )
)
AF_REQ = 1
AF_WRITE_ON = WRITE_FILTER_ENABLE | (AF_REQ << AWPROT_BP) | (AF_REQ << ARPROT_BP)
AF_READ_ON = READ_FILTER_ENABLE | (AF_REQ << AWPROT_BP) | (AF_REQ << ARPROT_BP)

CFG_NONSECURE = PASS_RW_CONFIG
CFG_SECURE = PASS_RW_CONFIG & ~_F_ALLOW_NS
_CFG_CMP_MASK = (
    filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
    | _F_ALLOW_NS
)

OBSERVE_CYCLES = 32
SETTLE_BOUND = 64
AXI_RESP_BOUND_CLK = 256
J2A_POLL_LIMIT = 128
PROTS = range(8)

# Accesses the contract steps need, counted from the step text.
# J2A: S1 aperture write and read (2) + per inbound entry config clear, start, end, config enable
# and config readback (5 each, two entries).
FLOOR_J2A = 2 + 2 * 5
# ext_in: S2 ACCESS_FILTER read, two DATA_CTRL writes, two DATA_CTRL reads (5); S3 filter write and
# readback, eight DATA_CTRL writes, filter clear and readback (12); S4 filter write and readback,
# known DATA_CTRL write, eight DATA_CTRL reads, filter re-read, restore write and readback (14).
FLOOR_AXI = 5 + 12 + 14


class smu_smc_gpio_access_filter_test_seq:
    """Drive DATA_CTRL and ACCESS_FILTER of pad 11 with AxPROT 0..7 over the external AXI port."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.step_ts: dict[str, float] = {}
        self.sites: list[dict] = []
        self.master = None
        self.jtag = None
        self.period_ns = float(test.cfg.smu_clk_period_ns)
        self.axi_bound_ns = round(AXI_RESP_BOUND_CLK * self.period_ns)

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await ClockCycles(self.dut.clk_smu_i, 1)
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, name: str, bound: int, used: int, last: str, unit: str) -> None:
        self.sites.append({"name": name, "bound": bound, "used": used, "last": last, "unit": unit})

    async def _j2a(self, name: str, write: bool, addr: int, value: int = 0) -> int:
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
            self._site(f"j2a_{name}", J2A_POLL_LIMIT, J2A_POLL_LIMIT + 1, f"EXPIRED {exc}", "polls")
            raise
        require_jtag_tdo_resolved(f"J2A {name} @0x{addr:08x}")
        self._site(f"j2a_{name}", J2A_POLL_LIMIT, 0, f"status={status}", "polls")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {name} status={status} want {J2A_STATUS_SUCCESS}")
        return 0 if write else int(raw) & 0xFFFF_FFFF

    def _cycles_since(self, start_ns: float) -> int:
        return -(-round((get_sim_time("ns") - start_ns) * 1000) // round(self.period_ns * 1000))

    async def _wr(self, addr: int, value: int, prot: int, label: str) -> int:
        start = get_sim_time("ns")
        result = await self.master.write_bytes_result(
            addr,
            value.to_bytes(4, byteorder="little"),
            prot=prot,
            check_response=False,
            timeout_ns=self.axi_bound_ns,
            allow_timeout=True,
        )
        if result.timed_out:
            self._site(
                f"axi_wr_{label}",
                AXI_RESP_BOUND_CLK,
                AXI_RESP_BOUND_CLK + 1,
                f"EXPIRED no_bresp addr=0x{addr:08x} awprot={prot}",
                "clk",
            )
            raise AssertionError(f"TIMEOUT axi_wr_{label}: last_state=no_bresp awprot={prot}")
        self._site(
            f"axi_wr_{label}",
            AXI_RESP_BOUND_CLK,
            self._cycles_since(start),
            f"bresp={resp_name(result.resp)}",
            "clk",
        )
        return result.resp

    async def _rd(self, addr: int, prot: int, label: str) -> tuple[int, int]:
        start = get_sim_time("ns")
        result = await self.master.read_bytes_result(
            addr,
            4,
            prot=prot,
            check_response=False,
            timeout_ns=self.axi_bound_ns,
            allow_timeout=True,
        )
        if result.timed_out:
            self._site(
                f"axi_rd_{label}",
                AXI_RESP_BOUND_CLK,
                AXI_RESP_BOUND_CLK + 1,
                f"EXPIRED no_rresp addr=0x{addr:08x} arprot={prot}",
                "clk",
            )
            raise AssertionError(f"TIMEOUT axi_rd_{label}: last_state=no_rresp arprot={prot}")
        data = int(result.data) & 0xFFFF_FFFF
        self._site(
            f"axi_rd_{label}",
            AXI_RESP_BOUND_CLK,
            self._cycles_since(start),
            f"rresp={resp_name(result.resp)} rdata=0x{data:08x}",
            "clk",
        )
        return data, result.resp

    async def _settle(self, name: str, expect: int | None = None) -> None:
        """Poll the pad for `expect` (at most SETTLE_BOUND clk); None observes a fixed window."""
        if expect is None:
            await ClockCycles(self.dut.clk_smu_i, OBSERVE_CYCLES)
            self._site(name, SETTLE_BOUND, OBSERVE_CYCLES, f"window={OBSERVE_CYCLES} clk", "clk")
            return
        level = self._level()
        for cycles in range(SETTLE_BOUND + 1):
            if level == expect:
                self._site(name, SETTLE_BOUND, cycles, f"pad={level} want={expect}", "clk")
                return
            if cycles < SETTLE_BOUND:
                await ClockCycles(self.dut.clk_smu_i, 1)
                level = self._level()
        self._site(
            name, SETTLE_BOUND, SETTLE_BOUND + 1, f"EXPIRED pad={level} want={expect}", "clk"
        )
        raise AssertionError(f"TIMEOUT {name}: pad={level} want={expect} bound={SETTLE_BOUND} clk")

    def _level(self) -> int:
        return (sample(self.dut.gpio_pad_io, "gpio_pad_io") >> PAD) & 1

    async def _program_inst(self, inst: int, start: int, end: int, config: int, tag: str) -> None:
        cfg_addr = smc_indexed_addr(IN_CFG_SYM, inst)
        await self._j2a(f"{tag}_config_clear", True, cfg_addr, 0)
        await self._j2a(f"{tag}_start", True, smc_indexed_addr(IN_START_SYM, inst), start)
        await self._j2a(f"{tag}_end", True, smc_indexed_addr(IN_END_SYM, inst), end)
        await self._j2a(f"{tag}_config", True, cfg_addr, config)
        rb = await self._j2a(f"{tag}_config_rb", False, cfg_addr)
        if (rb & _CFG_CMP_MASK) != (config & _CFG_CMP_MASK):
            raise AssertionError(f"{tag} CONFIG readback 0x{rb:x} want 0x{config:x}")

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
        await self._program_inst(0, DATA_CTRL, ACCESS_FILTER + 4, CFG_SECURE, "secure")
        await self._program_inst(1, DATA_CTRL, ACCESS_FILTER + 4, CFG_NONSECURE, "nonsecure")
        await ClockCycles(dut.clk_smu_i, 50)
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        dut.tb_gpio_drive_en.value = 0

    async def _s2(self, sb) -> None:
        af, af_resp = await self._rd(ACCESS_FILTER, 0, "af_reset")
        self._log(f"CELL reset_value value=0x{af:08x} rresp={resp_name(af_resp)}")
        resps = []
        pads = []
        reads = []
        word_hi = DC_BASE | CORE2PAD
        word_lo = DC_BASE
        resps.append(await self._wr(DATA_CTRL, word_hi, 0, "s2_wr_prot0"))
        await self._settle("s2_prot0_settle", 1)
        pads.append(self._level())
        resps.append(await self._wr(DATA_CTRL, word_lo, 7, "s2_wr_prot7"))
        await self._settle("s2_prot7_settle", 0)
        pads.append(self._level())
        for prot in (0, 7):
            data, resp = await self._rd(DATA_CTRL, prot, f"s2_rd_prot{prot}")
            resps.append(resp)
            reads.append(data & ~DC_READ_ONLY)
        self._log(
            f"CELL prot_0x0_admitted wresp={resp_name(resps[0])} pad={pads[0]} "
            f"rresp={resp_name(resps[2])} data=0x{reads[0]:08x}"
        )
        self._log(
            f"CELL prot_0x7_admitted wresp={resp_name(resps[1])} pad={pads[1]} "
            f"rresp={resp_name(resps[3])} data=0x{reads[1]:08x}"
        )
        sb.expect_eq(
            f"CHK-DBG-GPIO-FILTER-RESET (reset, resp, pad, read)=({af:#x}, {resps}, {pads}, "
            f"{[hex(r) for r in reads]})",
            (af, af_resp, tuple(resps), tuple(pads), tuple(reads)),
            (AF_RESET, RESP_OKAY, (RESP_OKAY,) * 4, (1, 0), (word_lo, word_lo)),
            evidence="DBG_GPIO_FILTER_RESET",
        )

    async def _set_filter(self, value: int, wprot: int, rprot: int, tag: str) -> int:
        resp = await self._wr(ACCESS_FILTER, value, wprot, f"{tag}_wr")
        rb, rresp = await self._rd(ACCESS_FILTER, rprot, f"{tag}_rb")
        self._log(
            f"CELL access_filter_{tag} wresp={resp_name(resp)} rresp={resp_name(rresp)} "
            f"wrote=0x{value:08x} readback=0x{rb:08x}"
        )
        return int(rb == value and resp == RESP_OKAY and rresp == RESP_OKAY)

    async def _s3(self, sb) -> None:
        set_ok = await self._set_filter(AF_WRITE_ON, 0, 0, "write_on")
        obs = []
        for prot in PROTS:
            before = self._level()
            target = 1 - before
            word = DC_BASE | (CORE2PAD if target else 0)
            resp = await self._wr(DATA_CTRL, word, prot, f"s3_awprot{prot}")
            await self._settle(f"s3_awprot{prot}_settle", target if prot == AF_REQ else None)
            after = self._level()
            self._log(
                f"CELL awprot_{prot} resp={resp_name(resp)} pad_before={before} pad_after={after}"
            )
            if resp != RESP_OKAY:
                self._log(
                    f"CHK-DBG-GPIO-FILTER-WRITE: awprot={prot} refused_code={resp_name(resp)} "
                    "LINKED-ISSUE SF-019"
                )
            obs.append((resp == RESP_OKAY, after == target))
        clear_ok = await self._set_filter(AF_RESET, AF_REQ, 0, "write_off")
        want = [(p == AF_REQ, p == AF_REQ) for p in PROTS]
        sb.expect_eq(
            f"CHK-DBG-GPIO-FILTER-WRITE (filter set, (admitted, pad followed) per AWPROT, "
            f"filter cleared)=({set_ok}, {obs}, {clear_ok})",
            (set_ok, obs, clear_ok),
            (1, want, 1),
            evidence="DBG_GPIO_FILTER_WRITE",
        )

    async def _s4(self, sb) -> None:
        resp = await self._wr(ACCESS_FILTER, AF_READ_ON, 0, "s4_read_on_wr")
        rb, rresp = await self._rd(ACCESS_FILTER, AF_REQ, "s4_read_on_rb")
        self._log(
            f"CELL access_filter_read_on wresp={resp_name(resp)} rresp={resp_name(rresp)} "
            f"wrote=0x{AF_READ_ON:08x} readback=0x{rb:08x}"
        )
        set_ok = int(rb == AF_READ_ON and resp == RESP_OKAY and rresp == RESP_OKAY)
        known = DC_BASE | CORE2PAD
        known_resp = await self._wr(DATA_CTRL, known, 0, "s4_known_wr")
        await self._settle("s4_known_settle", 1)
        obs = []
        for prot in PROTS:
            raw, resp = await self._rd(DATA_CTRL, prot, f"s4_arprot{prot}")
            data = raw & ~DC_READ_ONLY
            self._log(f"CELL arprot_{prot} resp={resp_name(resp)} data=0x{raw:08x}")
            if resp != RESP_OKAY:
                self._log(
                    f"CHK-DBG-GPIO-FILTER-READ: arprot={prot} refused_code={resp_name(resp)} "
                    f"data=0x{raw:08x} LINKED-ISSUE SF-019"
                )
                obs.append((False, None))
            else:
                obs.append((True, data))
        af_now, af_resp = await self._rd(ACCESS_FILTER, AF_REQ, "s4_restore_rd")
        restore_ok = await self._set_filter(AF_RESET, AF_REQ, AF_REQ, "read_off")
        self._log(f"CELL access_filter_before_restore value=0x{af_now:08x}")
        want = [(p == AF_REQ, known if p == AF_REQ else None) for p in PROTS]
        sb.expect_eq(
            f"CHK-DBG-GPIO-FILTER-READ (filter set, known write, (admitted, data) per ARPROT, "
            f"filter before restore, restored)=({set_ok}, {known_resp}, {obs}, {af_now:#x}, "
            f"{restore_ok})",
            (set_ok, known_resp, obs, af_now, af_resp, restore_ok),
            (1, RESP_OKAY, want, AF_READ_ON, RESP_OKAY, 1),
            evidence="DBG_GPIO_FILTER_READ",
        )

    def _s5(self, sb) -> None:
        expired = [s["name"] for s in self.sites if s["used"] > s["bound"]]
        for s in self.sites:
            state = "EXPIRED" if s["used"] > s["bound"] else "ok"
            self._log(
                f"TIMEOUT-PATH {s['name']}: bound={s['bound']} {s['unit']} {state} last={s['last']}"
            )
        finite = all(isinstance(s["bound"], int) and s["bound"] > 0 for s in self.sites)
        has_last = all(s["last"] for s in self.sites)
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={len(expired)} "
            f"axi_timeout_ns={self.axi_bound_ns}"
        )
        sb.expect_eq(
            f"CHK-TIMEOUT-PATHS expired={expired} bounds_finite={finite} last_state={has_last}",
            (expired, finite, has_last, bool(self.sites)),
            ([], True, True, True),
            evidence="CHK_TIMEOUT_PATHS",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self._mark("S1", "SETUP: aperture, inbound entries 0 (secure) and 1 (non-secure)")
        await self._s1(sb)
        await self._mark("S2", "ACCESS_FILTER reset value and unfiltered AxPROT 0 and 7")
        await self._s2(sb)
        await self._mark("S3", "write filter over AWPROT 0..7")
        await self._s3(sb)
        await self._mark("S4", "read filter over ARPROT 0..7")
        await self._s4(sb)
        await self._mark("S5", "TIMEOUT: bounded waits and last state")
        self._s5(sb)
        await self._mark("PASS", "fence end")
        order = ["S1", "S2", "S3", "S4", "S5", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        n_j2a = sum(s["name"].startswith("j2a_") for s in self.sites)
        n_axi = sum(s["name"].startswith("axi_") for s in self.sites)
        self._log(
            f"CHK-NONVAC: PASS (ordered sim-time fence S1<S2<S3<S4<S5<PASS) "
            f"j2a_accesses={n_j2a} axi_accesses={n_axi} "
            f"floor_j2a={FLOOR_J2A} floor_axi={FLOOR_AXI}"
        )
        sb.expect_eq(
            f"CHK-NONVAC access counts (j2a, axi)=({n_j2a}, {n_axi})",
            (n_j2a, n_axi),
            (FLOOR_J2A, FLOOR_AXI),
            evidence="CHK-NONVAC",
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            len({self.step_ts[k] for k in order}),
            len(order),
            evidence="CHK-NONVAC",
        )
        self.done = True
