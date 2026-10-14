# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gap, SLVERR-window and debug-module aperture responses on sep, sys and jtag at both bases.

Spec sources: memmap.adoc Address Space Organization, smc.rdl ocah_gap_resp / ocah_hole_resp /
ocah_past_extent_resp placements, smc_mailbox placement.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_inbound_window_port_matrix_test_seq import (
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
BADCAB1E = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ADMIT_POLL_BOUND_CYCLES = 6_000
AXI_TIMEOUT_NS = 50_000
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

PORTS = ("SEP", "SYS", "JTAG")
BASES = (("LOCAL", LOCAL_BASE_RESET), ("GLOBAL", GLOBAL_BASE_RESET))
COMBOS = tuple((p, b) for b in BASES for p in PORTS)
OTHER_COMBOS = tuple(c for c in COMBOS if c != ("SEP", BASES[0]))

GAP_C000 = ("GAP_C000", 0xC000, 0xFFF8)
GAP_ZC = ("GAP_ZEROER_CPU", 0x3_8300, 0x3_8FF8)
WINDOW_FIRST = 0x1_7000
WINDOW_LAST = 0x1_7FF8
BELOW_OFFSET = 0x1_6200
MAILBOX_OFFSET = smc_addr("SMC_TOP_SMC_MAILBOX_BASE_ADDR") - LOCAL_BASE_RESET

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_FENCE = (
    "SETUP<GAP_READS<GAP_WRITES<GAP_ZEROER_CPU<GAP_PORT_MATRIX<SLVERR_WINDOW<NEIGHBOURS"
    "<WINDOW_PORT_MATRIX<DEBUG"
)
_CHECKERS = (
    ("CHK-GAP-READ-DECERR", "S2"),
    ("CHK-GAP-WRITE-DECERR", "S3"),
    ("CHK-GAP-ZEROER-CPU-DECERR", "S4"),
    ("CHK-GAP-PORT-BASE-MATRIX", "S5"),
    ("CHK-SLVERR-WINDOW-WRITE-FIRST", "S6"),
    ("CHK-SLVERR-WINDOW-WRITE-LAST", "S6"),
    ("CHK-SLVERR-WINDOW-READ", "S6"),
    ("CHK-SLVERR-WINDOW-NEIGHBOURS", "S7"),
    ("CHK-SLVERR-WINDOW-PORT-BASE", "S8"),
    ("CHK-DEBUG-APERTURE-DECERR", "S9"),
)


def _rname(code) -> str:
    return _RESP_NAMES.get(code, str(code))


class smc_gap_decode_response_test_seq(SmcCsrSeq):
    """Probe the gap, window and debug-aperture addresses from the three inbound ports."""

    def __init__(self, name: str = "smc_gap_decode_response_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.admit_state = "not polled"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]
        return agent.sequencer

    def _item(self, port, op, label, addr, wdata) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        item.expected = None
        item.allow_error = True
        return item

    async def _rd(self, port: str, label: str, addr: int) -> tuple[int, int]:
        item = self._item(port, SmcSysAxiOp.READ, label, addr, 0)
        await _OneShot(item, f"{port.lower()}_{label}_os").start(self._sequencer(port))
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:08x}: no rresp recorded"
        return item.resp_code, item.rdata & 0xFFFF_FFFF

    async def _wr(self, port: str, label: str, addr: int, data: int = WRITE_PATTERN) -> int:
        item = self._item(port, SmcSysAxiOp.WRITE, label, addr, data)
        await _OneShot(item, f"{port.lower()}_{label}_os").start(self._sequencer(port))
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:08x}: no bresp recorded"
        return item.resp_code

    async def _rd_decerr(self, port: str, label: str, addr: int) -> int:
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        resp, rdata = await self._rd(port, label, addr)
        assert resp == AXI_RESP_DECERR, (
            f"{port} {label} @ 0x{addr:08x}: rresp {_rname(resp)}, want DECERR (rdata 0x{rdata:x})"
        )
        assert rdata == BADCAB1E, (
            f"{port} {label} @ 0x{addr:08x}: rdata 0x{rdata:08x}, want 0x{BADCAB1E:08x}"
        )
        return rdata

    async def _wr_decerr(self, port: str, label: str, addr: int) -> int:
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        resp = await self._wr(port, label, addr)
        assert resp == AXI_RESP_DECERR, (
            f"{port} {label} @ 0x{addr:08x}: bresp {_rname(resp)}, want DECERR"
        )
        return resp

    async def _wr_observe(self, port: str, label: str, addr: int, island: str, declared: str):
        """Write an SLVERR-declared address; either error code completes, the code is printed."""
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        resp = await self._wr(port, label, addr)
        cocotb.log.info(
            "island=%s addr=0x%08x bresp_declared=%s bresp_observed=%s",
            island,
            addr,
            declared,
            _rname(resp),
        )
        return resp

    async def _setup(self) -> str:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        dut = cocotb.top
        item = self._item("SYS", SmcSysAxiOp.READ, "S1_PROBE", LOCAL_BASE_RESET, 0)
        task = cocotb.start_soon(_OneShot(item, "sys_S1_PROBE_os").start(self._sequencer("SYS")))
        cycles = 0
        hits = 0
        while not task.done():
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            cycles += 1
            self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}"
            assert cycles <= ADMIT_POLL_BOUND_CYCLES, (
                f"sys_axi_in probe read of LOCAL_BASE not answered in {cycles} cycles"
            )
            hit = dut.tb_inb_read_hit.value
            assert hit.is_resolvable, "tb_inb_read_hit is X/Z"
            hits += int(hit) & 1
        await RisingEdge(dut.clk_smc_i)
        await task
        self.accesses += 1
        assert item.resp_code == AXI_RESP_OKAY, (
            f"admitted probe read answered {_rname(item.resp_code)}, want OKAY"
        )
        assert hits > 0, f"tb_inb_read_hit[0] never set in {cycles} cycles of the probe read"
        self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}"
        return (
            f"entry 0 pass-all programmed over sep_axi_in; sys_axi_in read of "
            f"0x{LOCAL_BASE_RESET:08X} OKAY with tb_inb_read_hit[0] high for {hits} samples "
            f"in {cycles} cycles"
        )

    async def _restore(self) -> None:
        for name, addr, want in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        ):
            await self.csr_write(f"INBOUND0_{name}_RESTORE", addr, want, length=8)
        for name, addr, want in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        ):
            await self.csr_read(f"INBOUND0_{name}_RESTORE_RB", addr, expected=want, length=8)

    async def _gap_words(self, port, base_name, base, gap, ops: str) -> str:
        tag, first, last = gap
        parts = []
        for where, off in (("FIRST", first), ("LAST", last)):
            addr = base + off
            label = f"{base_name}_{tag}_{where}"
            if "r" in ops:
                rdata = await self._rd_decerr(port, label, addr)
                parts.append(f"{where}@0x{addr:08X} rresp=DECERR rdata=0x{rdata:08X}")
            if "w" in ops:
                await self._wr_decerr(port, label, addr)
                parts.append(f"{where}@0x{addr:08X} bresp=DECERR")
        return f"{port}@{base_name} {tag} " + " ".join(parts)

    async def _window_words(self, port, base_name, base) -> tuple[dict, dict]:
        writes, reads = {}, {}
        for where, off in (("FIRST", WINDOW_FIRST), ("LAST", WINDOW_LAST)):
            addr = base + off
            writes[where] = await self._wr_observe(
                port,
                f"{base_name}_WIN_{where}_WR",
                addr,
                f"slverr_window_{where.lower()}",
                "SLVERR",
            )
        for where, off in (("FIRST", WINDOW_FIRST), ("LAST", WINDOW_LAST)):
            addr = base + off
            reads[where] = await self._rd_decerr(port, f"{base_name}_WIN_{where}_RD", addr)
        return writes, reads

    def _debug_addrs(self, base: int) -> list[tuple[str, int]]:
        first, last = generated_window("debug_module")
        size = last - first + 1
        return [
            ("FIRST", base + first),
            ("MID", base + first + ((size // 2) & ~0x7)),
            ("LAST", base + (last & ~0x7)),
        ]

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        local_name, local = BASES[0]

        admit = await self._setup()
        self._mark_step("S1")

        text = await self._gap_words("SEP", local_name, local, GAP_C000, "r")
        self._mark_step("S2")
        self._log_chk("CHK-GAP-READ-DECERR", f"{text}; {admit}")

        text = await self._gap_words("SEP", local_name, local, GAP_C000, "w")
        self._mark_step("S3")
        self._log_chk("CHK-GAP-WRITE-DECERR", text)

        text = await self._gap_words("SEP", local_name, local, GAP_ZC, "rw")
        self._mark_step("S4")
        self._log_chk("CHK-GAP-ZEROER-CPU-DECERR", text)

        texts = []
        for port, (base_name, base) in OTHER_COMBOS:
            for gap in (GAP_C000, GAP_ZC):
                texts.append(await self._gap_words(port, base_name, base, gap, "rw"))
        self._mark_step("S5")
        self._log_chk(
            "CHK-GAP-PORT-BASE-MATRIX",
            f"{len(texts)} port/base/window legs all DECERR with 0xBADCAB1E reads: "
            + "; ".join(texts),
        )

        win = {}
        win[("SEP", local_name)] = await self._window_words("SEP", local_name, local)
        wr, rd = win[("SEP", local_name)]
        self._mark_step("S6")
        for chk, where in (
            ("CHK-SLVERR-WINDOW-WRITE-FIRST", "FIRST"),
            ("CHK-SLVERR-WINDOW-WRITE-LAST", "LAST"),
        ):
            off = WINDOW_FIRST if where == "FIRST" else WINDOW_LAST
            self._log_chk(
                chk,
                f"write@0x{local + off:08X} bresp_declared=SLVERR bresp_observed="
                f"{_rname(wr[where])} (observe-only, owner value pending)",
            )
        self._log_chk(
            "CHK-SLVERR-WINDOW-READ",
            f"reads @0x{local + WINDOW_FIRST:08X} and @0x{local + WINDOW_LAST:08X} rresp=DECERR "
            f"rdata=0x{rd['FIRST']:08X}/0x{rd['LAST']:08X}",
        )

        text = await self._neighbours(local_name, local)
        self._mark_step("S7")
        self._log_chk("CHK-SLVERR-WINDOW-NEIGHBOURS", text)

        for port, (base_name, base) in OTHER_COMBOS:
            win[(port, base_name)] = await self._window_words(port, base_name, base)
        self._mark_step("S8")
        ref_w, _ = win[("SEP", local_name)]
        for (port, base_name), (wr_p, _) in win.items():
            assert wr_p == ref_w, (
                f"window bresp {port}@{base_name} {wr_p} differs from sep@LOCAL {ref_w}"
            )
        self._log_chk(
            "CHK-SLVERR-WINDOW-PORT-BASE",
            "window reads DECERR/0xBADCAB1E on all six port/base combinations; write bresp "
            + "; ".join(
                f"{p}@{b} first={_rname(w['FIRST'])} last={_rname(w['LAST'])}"
                for (p, b), (w, _) in win.items()
            )
            + "; equal across ports and bases (value observe-only, owner value pending)",
        )

        first, last = generated_window("debug_module")
        texts = []
        for port, (base_name, base) in COMBOS:
            parts = []
            for where, addr in self._debug_addrs(base):
                rdata = await self._rd_decerr(port, f"{base_name}_DBG_{where}_RD", addr)
                await self._wr_decerr(port, f"{base_name}_DBG_{where}_WR", addr)
                parts.append(f"{where}@0x{addr:08X} DECERR/0x{rdata:08X}/DECERR")
            texts.append(f"{port}@{base_name} " + " ".join(parts))
        self._mark_step("S9")
        self._log_chk(
            "CHK-DEBUG-APERTURE-DECERR",
            f"debug_module generated window 0x{LOCAL_BASE_RESET + first:08X}.."
            f"0x{LOCAL_BASE_RESET + last:08X} (owner value pending); " + "; ".join(texts),
        )

        await self._restore()

    async def _neighbours(self, base_name: str, base: int) -> str:
        rresp_decl, bresp_decl = generated_past_extent_resp("smc_outbound_filter_ctrl")
        assert rresp_decl == "DECERR", f"outbound filter past-extent rresp {rresp_decl}"
        below = base + BELOW_OFFSET
        rdata = await self._rd_decerr("SEP", f"{base_name}_BELOW_RD", below)
        bresp = await self._wr_observe(
            "SEP", f"{base_name}_BELOW_WR", below, "smc_outbound_filter_ctrl", bresp_decl
        )
        above = base + MAILBOX_OFFSET
        resp, mdata = await self._rd("SEP", f"{base_name}_ABOVE_RD", above)
        assert resp == AXI_RESP_OKAY, f"mailbox base @ 0x{above:08x} rresp {_rname(resp)}"
        wresp = await self._wr_observe("SEP", f"{base_name}_ABOVE_WR", above, "smc_mailbox", "OKAY")
        return (
            f"below@0x{below:08X} rresp=DECERR rdata=0x{rdata:08X} bresp_declared={bresp_decl} "
            f"bresp_observed={_rname(bresp)}; above@0x{above:08X} (mailbox base) rresp=OKAY "
            f"rdata=0x{mdata:08X} bresp_observed={_rname(wresp)}"
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; S1 admit poll bounded %d clk_smc_i rises, last observed %s; "
            "%d AXI accesses each bounded by the driver timeout %d ns (allow_timeout False), "
            "all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            ADMIT_POLL_BOUND_CYCLES,
            self.admit_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
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
