# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""M-mode and Xvisor output remap translation across regions, edges and valid toggling.

Spec sources: output_remap.rdl REGION_ATTRS, fabric.adoc Fabric Topology and Outbound Traffic Flow.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    hold_output_responder_writes,
    jtag_axi_write,
    output_responder_counts,
)
from .smc_output_remap_window_test_seq import OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT

_MMODE = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR")
_XVISOR = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR")
_SLOT = 0x10_0000
_WORD = 8
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_VALID = 1 << 63
AXI_TIMEOUT_NS = 50_000
FUSE_BOUND = 200_000
COUNT_POLL_BOUND = 200
HOLD_CYCLES = 64

# Region words the test programs: (remap kind, region, offset target).
_M_TARGET = {0: 0x0240_0000, 3: 0x0250_0000, 7: 0x0260_0000}
_X_TARGET = {0: 0x0270_0000, 3: 0x0280_0000, 7: 0x0290_0000, 1: 0x02A0_0000, 5: 0x02B0_0000}
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = (
    "IDENTITY",
    "REGIONS_PROGRAMMED",
    "MMODE_REGIONS",
    "XVISOR_REGIONS",
    "EDGES",
    "INDEPENDENCE",
    "VALID_TOGGLE",
    "CLEANED",
)
_CHECKERS = (
    ("CHK-OUTREMAP-IDENTITY-RESET", "S2"),
    ("CHK-MMODE-REGIONS", "S4"),
    ("CHK-XVISOR-REGIONS", "S5"),
    ("CHK-MMODE-EDGES", "S6"),
    ("CHK-XVISOR-EDGES", "S6"),
    ("CHK-OUTROUTE-DIRECT-ADDRS", "S6"),
    ("CHK-XVISOR-INDEPENDENT", "S7"),
    ("CHK-OUTREMAP-VALID-TOGGLE", "S8"),
)
ACCESS_FLOOR = 83
_GROUP = 12
_GROUP_BASE = 0x400


def _attrs(kind: str, region: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_{kind}_REMAP_REGION_REGION_ATTRS_BASE_ADDR", region)


class smc_outremap_window_translate_test_seq(SmcCsrSeq):
    """Program remap regions over SEP_IN and translate JTAG writes through the windows."""

    def __init__(self, name: str = "smc_outremap_window_translate_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self.chk_seen: dict[str, str] = {}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._aw: list[int] = []
        self._watch_stop = False
        self._count_last = "unused"
        self._hold_last = "unused"
        self._probe_id = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._stamps)))
        self.chk_seen[chk_id] = text

    async def _watch_aw(self) -> None:
        dut = cocotb.top
        while not self._watch_stop:
            await RisingEdge(dut.clk_smc_i)
            vals = (dut.tb_output_axi_awvalid, dut.tb_output_axi_awready, dut.tb_output_axi_awaddr)
            assert all(s.value.is_resolvable for s in vals), "output AW probes are X/Z"
            if int(dut.tb_output_axi_awvalid.value) and int(dut.tb_output_axi_awready.value):
                self._aw.append(int(dut.tb_output_axi_awaddr.value))

    async def _wait_writes(self, want: int, label: str) -> None:
        for n in range(1, COUNT_POLL_BOUND + 1):
            have = output_responder_counts()[0]
            self._count_last = f"{label}: write_count {have}/{want} after {n - 1} clocks"
            if have == want:
                return
            assert have < want, f"{label}: tb_output_axi_write_count {have} passed {want}"
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: write_count never reached {want}; {self._count_last}")

    async def _program(self, kind: str, region: int, target: int) -> None:
        word = _VALID | target
        await self.csr_write(f"{kind}{region}_ATTRS", _attrs(kind, region), word, length=_WORD)
        await self.csr_read(f"{kind}{region}_ATTRS_RB", _attrs(kind, region), word, length=_WORD)

    def _addr(self, kind: str, region: int, offset: int) -> int:
        return (_MMODE if kind == "MMODE" else _XVISOR) + region * _SLOT + offset

    async def _probe(self, label: str, addr: int, expect: int) -> str:
        """JTAG write at ``addr``; the word must land at ``expect`` and nowhere else."""
        self._probe_id += 1
        word = 0xC0DE_0000_0000_0000 | (self._probe_id << 32) | (addr & 0xFFFF_FFFF)
        for seed in {addr, expect}:
            self.cfg.sys_out_mem.write_int(seed, _SENTINEL, _WORD)
        writes, _ = output_responder_counts()
        aw_mark = len(self._aw)
        item = await jtag_axi_write(self, addr, word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG write 0x{addr:x} resp {item.resp_code}"
        await self._wait_writes(writes + 1, label)
        got = self.cfg.sys_out_mem.read_int(expect, _WORD)
        assert got == word, (
            f"[{label}] 0x{addr:x}: SYS_OUT 0x{expect:x} holds 0x{got:016x}, want 0x{word:016x}"
        )
        if addr != expect:
            kept = self.cfg.sys_out_mem.read_int(addr, _WORD)
            assert kept == _SENTINEL, f"[{label}] SYS_OUT 0x{addr:x} changed to 0x{kept:016x}"
        assert self._aw[aw_mark:] == [expect], f"[{label}] AW addresses {self._aw[aw_mark:]}"
        return f"0x{addr:X}->0x{expect:X}"

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        watcher = cocotb.start_soon(self._watch_aw())
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"

        # S1: every region reads valid clear; sentinels are seeded per probe.
        for kind in ("MMODE", "XVISOR"):
            for region in range(8):
                await self.csr_read(
                    f"{kind}{region}_ATTRS_RESET",
                    _attrs(kind, region),
                    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    length=_WORD,
                )
        self._mark_step("S1")

        # S2: identity at reset.
        offset_targets = (0x0240_0040, 0x0270_0040)
        for target in offset_targets:
            responder.write_int(target, _SENTINEL, _WORD)
        identity = [
            await self._probe("IDENTITY_M", _MMODE + 0x40, _MMODE + 0x40),
            await self._probe("IDENTITY_X", _XVISOR + 0x40, _XVISOR + 0x40),
        ]
        for target in offset_targets:
            kept = responder.read_int(target, _WORD)
            assert kept == _SENTINEL, f"SYS_OUT 0x{target:x} holds 0x{kept:016x} at identity"
        self._mark_step("S2")
        self._log_chk(
            "CHK-OUTREMAP-IDENTITY-RESET",
            f"every region reads valid clear; {', '.join(identity)} landed at their own "
            "addresses (reset-word proof, two-state bench)",
        )

        # S3: program M0, M3, M7, X0, X3, X7.
        for region, target in _M_TARGET.items():
            await self._program("MMODE", region, target)
        for region in (0, 3, 7):
            await self._program("XVISOR", region, _X_TARGET[region])
        self._mark_step("S3")

        # S4, S5: low 20 bits kept.
        landed = [
            await self._probe(f"M{r}", self._addr("MMODE", r, 0x1A8), t | 0x1A8)
            for r, t in _M_TARGET.items()
        ]
        self._mark_step("S4")
        self._log_chk("CHK-MMODE-REGIONS", f"M-mode regions 0,3,7 landed {', '.join(landed)}")
        landed = [
            await self._probe(f"X{r}", self._addr("XVISOR", r, 0x1A8), _X_TARGET[r] | 0x1A8)
            for r in (0, 3, 7)
        ]
        self._mark_step("S5")
        self._log_chk("CHK-XVISOR-REGIONS", f"Xvisor regions 0,3,7 landed {', '.join(landed)}")

        # S6: window edges, below-window byte and direct addresses.
        below = _MMODE - _WORD
        writes, _ = output_responder_counts()
        aw_mark = len(self._aw)
        for seed in (below, 0x026F_FFF8, 0x029F_FFF8):
            responder.write_int(seed, _SENTINEL, _WORD)
        item = await jtag_axi_write(self, below, 0xBE10_0000_0000_0000, allow_error=True)
        self.jtag_accesses += 1
        assert item.resp_code is not None, f"write at 0x{below:x} returned no response code"
        self._hold_last = f"hold after 0x{below:x}: write_count stays {writes}"
        await hold_output_responder_writes(
            expected_writes=writes, label="BELOW", hold_cycles=HOLD_CYCLES
        )
        assert self._aw[aw_mark:] == [], f"AW at {self._aw[aw_mark:]} for the byte below"
        for seed in (below, 0x026F_FFF8, 0x029F_FFF8):
            kept = responder.read_int(seed, _WORD)
            assert kept == _SENTINEL, f"below-window write left 0x{kept:016x} at 0x{seed:x}"
        below_resp = item.resp_code
        m_edges = [
            await self._probe("M_FIRST", _MMODE, 0x0240_0000),
            await self._probe("M_LAST", _XVISOR - _WORD, 0x026F_FFF8),
        ]
        x_edges = [
            await self._probe("X_FIRST", _XVISOR, 0x0270_0000),
            await self._probe("X_LAST", _XVISOR + 8 * _SLOT - _WORD, 0x029F_FFF8),
        ]
        direct = [
            await self._probe("DIRECT_LOCAL", 0xC200_0008, 0xC200_0008),
            await self._probe("DIRECT_GLOBAL", 0x4200_0008, 0x4200_0008),
        ]
        self._mark_step("S6")
        self._log_chk(
            "CHK-MMODE-EDGES",
            f"{', '.join(m_edges)}; below-window 0x{below:X}: resp={below_resp} (printed, "
            f"gap-response value not stated), no AW, write_count held {writes}",
        )
        self._log_chk(
            "CHK-XVISOR-EDGES",
            f"{', '.join(x_edges)}; the 8 bytes below (0xC17F_FFF8) landed at 0x026F_FFF8 "
            "through the M-mode remap; 0xC200_0008 landed at its own address",
        )
        self._log_chk(
            "CHK-OUTROUTE-DIRECT-ADDRS", f"{', '.join(direct)} reached output_axi unchanged"
        )

        # S7: neighbours do not disturb programmed regions.
        for region in (1, 5):
            await self._program("XVISOR", region, _X_TARGET[region])
        independent = []
        for region in (0, 3, 7, 2, 4, 1, 5):
            expect = _X_TARGET.get(region, None)
            addr = self._addr("XVISOR", region, 0x40)
            independent.append(
                await self._probe(
                    f"X{region}_AGAIN", addr, addr if expect is None else expect | 0x40
                )
            )
        self._mark_step("S7")
        self._log_chk("CHK-XVISOR-INDEPENDENT", ", ".join(independent))

        # S8: valid cleared while a JTAG group is outstanding.
        items = []
        for k in range(_GROUP):
            item = SmcSysAxiItem(f"valid_toggle_{k}")
            item.op = SmcSysAxiOp.WRITE
            item.addr = _MMODE + _GROUP_BASE + _WORD * k
            item.length = _WORD
            item.wdata = 0x7061_0000_0000_0000 | k
            items.append(item)
            responder.write_int(item.addr, _SENTINEL, _WORD)
            responder.write_int(_M_TARGET[0] + _GROUP_BASE + _WORD * k, _SENTINEL, _WORD)
        writes, _ = output_responder_counts()
        group = SmcSysAxiGroupItem("valid_toggle_group", items)
        task = cocotb.start_soon(
            _OneShot(group, "valid_toggle_os").start(self.env.jtag_axi_agent.sequencer)
        )
        await self.csr_write("M0_VALID_CLEAR", _attrs("MMODE", 0), _M_TARGET[0], length=_WORD)
        await task
        self.jtag_accesses += _GROUP
        await self._wait_writes(writes + _GROUP, "VALID_TOGGLE")
        seq_land = []
        for k, item in enumerate(items):
            assert item.resp_code == 0, f"group write {k} resp {item.resp_code}"
            at_target = responder.read_int(_M_TARGET[0] + _GROUP_BASE + _WORD * k, _WORD)
            at_own = responder.read_int(item.addr, _WORD)
            assert (at_target == item.wdata) != (at_own == item.wdata), (
                f"write {k}: target 0x{at_target:016x}, own 0x{at_own:016x}, want {item.wdata:#x}"
            )
            seq_land.append("R" if at_target == item.wdata else "I")
        landing = "".join(seq_land)
        assert "IR" not in landing and landing.count("RI") <= 1, f"landing order {landing}"
        self._mark_step("S8")
        self._log_chk(
            "CHK-OUTREMAP-VALID-TOGGLE",
            f"{_GROUP} writes all OKAY; landing in issue order {landing} (R remapped, I identity); "
            "owner value pending",
        )

        # S9: restore every programmed entry to its reset word.
        for kind, regions in (("MMODE", _M_TARGET), ("XVISOR", _X_TARGET)):
            for region in regions:
                await self.csr_restore(
                    f"{kind}{region}_ATTRS",
                    _attrs(kind, region),
                    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                )
        self._mark_step("S9")
        self._watch_stop = True
        await watcher
        self._finish()

    def _finish(self) -> None:
        waits = (
            ("tb_fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", "asserted"),
            ("tb_fuse_reset_n", f"{FUSE_BOUND}clk_smc_i", "released"),
            ("tb_rst_warm_smc_clk_n", f"{FUSE_BOUND}clk_smc_i", "released"),
            ("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", f"{self.accesses} accesses done"),
            ("jtag_axi_access", f"{AXI_TIMEOUT_NS}ns", f"{self.jtag_accesses} accesses done"),
            ("output_write_count_poll", f"{COUNT_POLL_BOUND}clk_smc_i", self._count_last),
            ("output_write_hold", f"{HOLD_CYCLES}clk_smc_i", self._hold_last),
        )
        text = " ".join(f"{n}={b} last={s}" for n, b, s in waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(waits),
            text,
        )
        assert tuple(s for s, _ in self._stamps) == _STEPS, f"steps {self._stamps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        printed = tuple(c for c, _ in self._chk_marks)
        assert printed == tuple(c for c, _ in _CHECKERS), f"checker order {printed}"
        for chk_id, step in _CHECKERS:
            seen_at = dict(self._chk_marks)[chk_id]
            assert seen_at >= _STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        total = self.accesses + self.jtag_accesses
        assert total >= ACCESS_FLOOR, f"{total} accesses, floor {ACCESS_FLOOR}"
        self.chk_seen["CHK-TIMEOUT-PATHS"] = text
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; accesses %d (SEP_IN %d, "
            "JTAG %d) vs floor %d",
            " < ".join(_TERMS),
            ",".join(printed),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            total,
            self.accesses,
            self.jtag_accesses,
            ACCESS_FLOOR,
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
