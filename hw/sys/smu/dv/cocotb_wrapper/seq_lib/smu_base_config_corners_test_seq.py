# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC base configuration corners: LOCAL_BASE, GLOBAL_BASE at the top of the space.

``hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl``: LOCAL_BASE is ``sw=r``; GLOBAL_BASE
is a 56-bit ``sw=rw`` field.
``hw/sys/smu/doc/index.adoc``: the SMC rule of the SMU crossbar is
[GLOBAL_BASE, GLOBAL_BASE + REGION_SIZE), computed with 57 bits, and an ``ext_in`` request that
matches no rule answers DECERR. JTAG2AXI reaches every register at its local address whatever
GLOBAL_BASE holds; the external input reaches a register only while the crossbar rule and an
inbound filter entry admit the address it drives.

S1: TAP reset, JTAG2AXI gate open, external master created, both aperture ports sampled at reset.
S2: LOCAL_BASE written with all ones and with 0x1234_5000 (responses logged), read back after each
    write; VERSION_LO read at the local alias; both ports sampled again.
S3: entry 0 over the old base through the new window, GLOBAL_BASE moved to an aligned base, the port
    polled; the external read at the new base is OKAY, the read at the old base answers OKAY before
    and DECERR after the move; LOCAL_BASE unchanged while GLOBAL_BASE reads the new base.
S4: entry 0 over the last window, GLOBAL_BASE at the top of the 56-bit space; the external read at
    the new base is OKAY; a probe at the low window offset is logged.
S5: GLOBAL_BASE half a window below the top; smc_global_base_o equals the written base and
    smc_region_size_o is unchanged; the external read is logged; GLOBAL_BASE restored to
    LOCAL_BASE and entry 0 cleared.
S6: every bounded wait reports its bound and last state.
"""

from __future__ import annotations

import math

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_addr,
)
from seq_lib.smu_axi_helpers import (
    AXI_TIMEOUT_NS,
    axi_read32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_filter_helpers import (
    INBOUND0_FILTER_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    program_inbound0_window,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

# smc_base_config.rdl: GLOBAL_BASE and LOCAL_BASE hold a 56-bit base.
ADDR_BITS = 56
ADDR_SPACE = 1 << ADDR_BITS
ADDR_MASK = ADDR_SPACE - 1

LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
# hw/sys/smc/regs/gen/c/blocks/smc_base_config.h reset values.
LOCAL_BASE = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
VERSION_OFF = VERSION_LO - LOCAL_BASE

# smc_base_config.rdl LOCAL_BASE sw=r: values written that differ from the reset value.
LOCAL_WRITE_ONES = (1 << 64) - 1
LOCAL_WRITE_PATTERN = 0x1234_5000
# smc_base_config.rdl GLOBAL_BASE: an aligned base from the 0xAA.. pattern, aligned to REGION_SIZE.
MOVED_BASE = 0xAA_AAAA_AAAA_AAAA & ~(REGION_SIZE_RESET - 1) & ADDR_MASK
# hw/sys/smu/doc/index.adoc: the last window below 2^56 and a window reaching past it.
TOP_BASE = ADDR_SPACE - REGION_SIZE_RESET
TOP_BASE_PORT = 0x00FF_FFFF_FF00_0000
BEYOND_BASE = ADDR_SPACE - REGION_SIZE_RESET // 2

OKAY = resp_name(RESP_OKAY)
DECERR = resp_name(RESP_DECERR)

J2A_POLL_LIMIT = 128
# JTAG2AXI accesses the leaf issues: S2 six, S3 six, S4 five, S5 three.
J2A_ACCESS_COUNT = 20
J2A_ACCESS_BUDGET = 28
PORT_POLL_CYCLES = 64
IDLE_CYCLES = 4
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
ACCESS_STEPS = STEPS[:-1]


def _require_map() -> None:
    facts = (
        (LOCAL_WRITE_ONES != LOCAL_BASE and LOCAL_WRITE_PATTERN != LOCAL_BASE, "write is reset"),
        (VERSION_OFF % 8 == 0, "VERSION_LO window offset"),
        (MOVED_BASE % REGION_SIZE_RESET == 0 and MOVED_BASE != GLOBAL_BASE_RESET, "moved base"),
        (TOP_BASE == TOP_BASE_PORT, "top base"),
        (TOP_BASE + REGION_SIZE_RESET == ADDR_SPACE, "top window does not end at 2^56"),
        (BEYOND_BASE + REGION_SIZE_RESET > ADDR_SPACE, "window does not pass 2^56"),
    )
    bad = [msg for ok, msg in facts if not ok]
    if bad:
        raise RuntimeError("base config corners map: " + "; ".join(bad))


_require_map()


class smu_base_config_corners_test_seq:
    """SMC base configuration corners at JTAG2AXI, the external master and the aperture ports."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = cocotb.top.clk_smu_i
        self.jtag = None
        self.master = None
        self.step = ""
        self.step_ts: dict[str, float] = {}
        self.step_access = {step: {"j2a": 0, "ext": 0, "port": 0} for step in STEPS}
        self.sites: dict[str, dict] = {}
        self.ports_reset = (0, 0)
        self.bound_clk = math.ceil(AXI_TIMEOUT_NS / self.cfg.smu_clk_period_ns)

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, name: str, bound: int, used: int, last: str, unit: str) -> None:
        site = self.sites.setdefault(
            name, {"bound": bound, "used": 0, "last": last, "unit": unit, "count": 0}
        )
        site["count"] += 1
        site["used"] = max(site["used"], used)
        site["last"] = last

    def _chk(self, sb, chk: str, name: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {name}", observed, expected, evidence=chk)

    def _ports(self) -> tuple[int, int]:
        vals = []
        for name in ("smc_global_base_o", "smc_region_size_o"):
            val = getattr(self.dut, name).value
            if not val.is_resolvable:
                raise AssertionError(f"X/Z on {name}: {val}")
            vals.append(int(val))
        self.step_access[self.step]["port"] += 1
        return vals[0], vals[1]

    async def _await_ports(self, tag: str, *, base: int | None, size: int | None) -> tuple:
        """Poll the aperture ports until they equal the wanted values."""
        waited = 0
        while True:
            got = self._ports()
            if (base is None or got[0] == base) and (size is None or got[1] == size):
                break
            if waited >= PORT_POLL_CYCLES:
                self._site(
                    f"port_{tag}",
                    PORT_POLL_CYCLES,
                    PORT_POLL_CYCLES + 1,
                    f"EXPIRED ports=(0x{got[0]:x},0x{got[1]:x})",
                    "clk",
                )
                raise AssertionError(
                    f"TIMEOUT port_{tag} bound={PORT_POLL_CYCLES} clk "
                    f"ports=(0x{got[0]:x},0x{got[1]:x}) want base={base} size={size}"
                )
            await ClockCycles(self.clk, 1)
            waited += 1
        self._site(
            f"port_{tag}",
            PORT_POLL_CYCLES,
            waited,
            f"waited={waited} clk ports=(0x{got[0]:x},0x{got[1]:x})",
            "clk",
        )
        return got

    async def _j2a(self, tag: str, write: bool, addr: int, value: int = 0, *, size=None):
        kwargs = {} if size is None else {"size": size}
        if write and size is not None:
            word = int(value) & 0xFFFF_FFFF
            value, kwargs["wstrb"] = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        t0 = get_sim_time("ns")
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    value,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                    **kwargs,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag, addr, poll_limit=J2A_POLL_LIMIT, require_complete=True, **kwargs
                )
        except TimeoutError as exc:
            self._site(f"j2a_{tag}", J2A_POLL_LIMIT, J2A_POLL_LIMIT + 1, f"EXPIRED {exc}", "polls")
            raise
        require_jtag_tdo_resolved(f"J2A {tag} @0x{addr:08x}")
        cycles = math.ceil((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        self._site(
            f"j2a_{tag}",
            J2A_POLL_LIMIT,
            0,
            f"status={status} completed inside the poll limit, elapsed_clk={cycles}",
            "polls",
        )
        self.step_access[self.step]["j2a"] += 1
        if raw is not None and size == SMC_DBG_AXSIZE_4B and not write:
            raw = ((raw >> 32) if addr & 0x4 else raw) & 0xFFFF_FFFF
        return status, int(raw)

    async def _j2a_ok_wr(self, tag: str, addr: int, value: int, *, size=None) -> None:
        status, _ = await self._j2a(tag, True, addr, value, size=size)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {tag} status={status} want {J2A_STATUS_SUCCESS}")

    async def _j2a_ok_rd(self, tag: str, addr: int, *, size=None) -> int:
        status, raw = await self._j2a(tag, False, addr, size=size)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {tag} status={status} want {J2A_STATUS_SUCCESS}")
        return raw

    async def _set_entry(self, tag: str, lo: int, hi: int) -> None:
        await program_inbound0_window(self.jtag, lo, hi, tag=tag)
        self.step_access[self.step]["j2a"] += 3
        self._site(f"j2a_{tag}", J2A_POLL_LIMIT, 0, "three entry writes completed", "polls")

    async def _ext_rd(self, tag: str, addr: int) -> tuple[str, int]:
        name = f"ext_rd_{tag}"
        t0 = get_sim_time("ns")
        try:
            data, resp = await axi_read32_resp_bounded(self.master, addr, label=name)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._site(
                    name, self.bound_clk, self.bound_clk + 1, f"EXPIRED addr=0x{addr:014x}", "clk"
                )
            raise
        used = math.ceil((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        name_resp = resp_name(resp)
        self._site(name, self.bound_clk, used, f"resp={name_resp} addr=0x{addr:014x}", "clk")
        self.step_access[self.step]["ext"] += 1
        await ClockCycles(self.clk, IDLE_CYCLES)
        return name_resp, int(data) & 0xFFFF_FFFF

    async def _s1(self, sb) -> None:
        dut = self.dut
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or (int(gate) & 1) != 0:
            raise AssertionError(f"SMC J2A gated after TCK sync: {gate}")
        self.master = await make_smu_axi_master(dut, self.clk, smc_primary_reset(dut))
        self.ports_reset = self._ports()
        self._log(f"PORTS at reset base=0x{self.ports_reset[0]:x} size=0x{self.ports_reset[1]:x}")

    async def _s2(self, sb) -> None:
        initial = (await self._j2a_ok_rd("local_base_rd_reset", LOCAL_BASE_REG)) & ADDR_MASK
        reads = []
        for tag, value in (("ones", LOCAL_WRITE_ONES), ("pattern", LOCAL_WRITE_PATTERN)):
            status, _ = await self._j2a(f"local_base_wr_{tag}", True, LOCAL_BASE_REG, value)
            self._log(
                f"OBSERVATION LOCAL_BASE write value=0x{value:x} J2A status={status} "
                "measured and logged only"
            )
            raw = await self._j2a_ok_rd(f"local_base_rd_{tag}", LOCAL_BASE_REG)
            reads.append(raw & ADDR_MASK)
        self._chk(
            sb,
            "CHK-BASECFG-LOCAL-RO",
            "LOCAL_BASE after two writes",
            [initial, *reads],
            [LOCAL_BASE, LOCAL_BASE, LOCAL_BASE],
            f"LOCAL_BASE reads 0x{LOCAL_BASE:x} at reset and after the writes of "
            f"0x{LOCAL_WRITE_ONES:x} and 0x{LOCAL_WRITE_PATTERN:x}",
        )
        status, version = await self._j2a("version_lo", False, VERSION_LO, size=SMC_DBG_AXSIZE_4B)
        self._chk(
            sb,
            "CHK-BASECFG-LOCAL-VIEW",
            "VERSION_LO at the local alias",
            (status, version),
            (J2A_STATUS_SUCCESS, VERSION_LO_RESET),
            f"VERSION_LO at 0x{VERSION_LO:08x} returns SUCCESS and the reset value after the "
            "LOCAL_BASE writes",
        )
        after = self._ports()
        self._chk(
            sb,
            "CHK-BASECFG-PORTS-LOCAL",
            "ports before and after the LOCAL_BASE writes",
            (self.ports_reset, after),
            ((GLOBAL_BASE_RESET, REGION_SIZE_RESET),) * 2,
            f"smc_global_base_o 0x{GLOBAL_BASE_RESET:x} and smc_region_size_o "
            f"0x{REGION_SIZE_RESET:x} at reset and after the writes",
        )

    async def _s3(self, sb) -> None:
        old_addr = GLOBAL_BASE_RESET + VERSION_OFF
        new_addr = MOVED_BASE + VERSION_OFF
        await self._set_entry("entry_move", GLOBAL_BASE_RESET, MOVED_BASE + REGION_SIZE_RESET - 1)
        before = await self._ext_rd("old_before", old_addr)
        await self._j2a_ok_wr("global_base_moved", SMC_APERTURE_GLOBAL_BASE_REG, MOVED_BASE)
        port = await self._await_ports("global_moved", base=MOVED_BASE, size=None)
        at_new = await self._ext_rd("new", new_addr)
        at_old = await self._ext_rd("old_after", old_addr)
        self._chk(
            sb,
            "CHK-BASECFG-GLOBAL-MOVE",
            "GLOBAL_BASE move",
            (port[0], before, at_new, at_old[0]),
            (MOVED_BASE, (OKAY, VERSION_LO_RESET), (OKAY, VERSION_LO_RESET), DECERR),
            f"smc_global_base_o follows to 0x{MOVED_BASE:x} within {PORT_POLL_CYCLES} clk, "
            "VERSION_LO answers OKAY at the new base and at the old base before the move, and "
            "the old base answers DECERR after it",
        )
        local = (await self._j2a_ok_rd("local_base_after_move", LOCAL_BASE_REG)) & ADDR_MASK
        global_rb = (await self._j2a_ok_rd("global_base_rb", SMC_APERTURE_GLOBAL_BASE_REG)) & (
            ADDR_MASK
        )
        self._chk(
            sb,
            "CHK-BASECFG-LOCAL-ISOLATED",
            "LOCAL_BASE beside the moved GLOBAL_BASE",
            (local, global_rb),
            (LOCAL_BASE, MOVED_BASE),
            f"LOCAL_BASE reads 0x{LOCAL_BASE:x} while GLOBAL_BASE reads 0x{MOVED_BASE:x}",
        )

    async def _s4(self, sb) -> None:
        await self._set_entry("entry_top", TOP_BASE, ADDR_MASK)
        await self._j2a_ok_wr("global_base_top", SMC_APERTURE_GLOBAL_BASE_REG, TOP_BASE)
        port = await self._await_ports("global_top", base=TOP_BASE_PORT, size=None)
        global_rb = (await self._j2a_ok_rd("global_base_top_rb", SMC_APERTURE_GLOBAL_BASE_REG)) & (
            ADDR_MASK
        )
        at_top = await self._ext_rd("top", TOP_BASE + VERSION_OFF)
        low = await self._ext_rd("low_probe", VERSION_OFF)
        self._log(
            f"OBSERVATION low-address probe addr=0x{VERSION_OFF:x} resp={low[0]} "
            f"data=0x{low[1]:08x} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-BASECFG-GLOBAL-TOP",
            "GLOBAL_BASE at the top of the space",
            (port[0], global_rb, at_top),
            (TOP_BASE_PORT, TOP_BASE, (OKAY, VERSION_LO_RESET)),
            f"smc_global_base_o equals 0x{TOP_BASE_PORT:014x} and VERSION_LO at the new base "
            f"answers OKAY; low probe resp={low[0]} data=0x{low[1]:08x} measured and logged only",
        )

    async def _s5(self, sb) -> None:
        await self._j2a_ok_wr("global_base_beyond", SMC_APERTURE_GLOBAL_BASE_REG, BEYOND_BASE)
        await ClockCycles(self.clk, PORT_POLL_CYCLES)
        port = self._ports()
        beyond = await self._ext_rd("beyond", BEYOND_BASE + VERSION_OFF)
        self._log(
            f"OBSERVATION window past 2^56: external read addr=0x{BEYOND_BASE + VERSION_OFF:x} "
            f"resp={beyond[0]} data=0x{beyond[1]:08x} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-BASECFG-GLOBAL-BEYOND-OBS",
            "GLOBAL_BASE half a window below the top",
            port,
            (BEYOND_BASE, REGION_SIZE_RESET),
            f"smc_global_base_o equals the written 0x{BEYOND_BASE:014x} and smc_region_size_o "
            f"stays 0x{REGION_SIZE_RESET:x} after {PORT_POLL_CYCLES} clk; the external read "
            f"resp={beyond[0]} data=0x{beyond[1]:08x} is measured and logged only",
        )
        await self._j2a_ok_wr("global_base_restore", SMC_APERTURE_GLOBAL_BASE_REG, LOCAL_BASE)
        await self._await_ports("global_restore", base=LOCAL_BASE, size=None)
        await self._j2a_ok_wr("entry_clear", INBOUND0_FILTER_CONFIG, 0)

    def _s6(self, sb) -> None:
        expired = [n for n, s in self.sites.items() if s["used"] > s["bound"]]
        for name, site in self.sites.items():
            state = "EXPIRED" if name in expired else "ok"
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} "
                f"max_used={site['used']} count={site['count']} {state} last={site['last']}"
            )
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] for s in self.sites.values())
        j2a_accesses = sum(self.step_access[s]["j2a"] for s in STEPS)
        self._chk(
            sb,
            "CHK-TIMEOUT-PATHS",
            "bounded waits",
            (expired, finite, has_last, j2a_accesses),
            ([], True, True, J2A_ACCESS_COUNT),
            f"sites={len(self.sites)} expired={len(expired)} ext_bound={self.bound_clk} clk "
            f"j2a_poll_limit={J2A_POLL_LIMIT} port_bound={PORT_POLL_CYCLES} clk; j2a_accesses "
            f"against the budget {J2A_ACCESS_BUDGET}",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(self.clk, 16)
        plan = (
            ("S1", "SETUP: TAP, gate, external master, ports at reset", self._s1),
            ("S2", "LOCAL_BASE written with ones and a pattern", self._s2),
            ("S3", "GLOBAL_BASE moved to an aligned base", self._s3),
            ("S4", "GLOBAL_BASE at the top of the 56-bit space", self._s4),
            ("S5", "GLOBAL_BASE past the top, restored to LOCAL_BASE", self._s5),
        )
        for step, text, body in plan:
            await self._mark(step, text)
            await body(sb)
        await self._mark("S6", "TIMEOUT: bounded waits and last state")
        self._s6(sb)
        await ClockCycles(self.clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*ACCESS_STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        counts = " ".join(
            f"{s}:j2a={self.step_access[s]['j2a']},ext={self.step_access[s]['ext']},"
            f"port={self.step_access[s]['port']}"
            for s in STEPS
        )
        increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
        every_step_accessed = all(sum(self.step_access[s].values()) > 0 for s in ACCESS_STEPS)
        self._log(f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; accesses {counts}")
        self._chk(
            sb,
            "CHK-NONVAC",
            "ordered fence and per-step access counts",
            (increasing, every_step_accessed),
            (True, True),
            "step stamps strictly increase to the pass point and every step S1..S5 counted at "
            "least one access or port sample",
        )
