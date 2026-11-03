# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_006 ANCHOR: smc_axil_narrow_zero_strobe_write_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: b32eaa21a08f9bf4474335e824b910f1c8842a360b9ef27e7fc7cdff28aaa092
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Narrow and zero-strobe writes over SEP_IN to the 64-bit AXI-Lite register links.

Every access goes through SEP_IN, one at a time, with an explicit WSTRB where a
step names a strobe; a disabled lane carries its byte of the written data.

* PLAIN: CPU_CTRL RESET_VECTOR, SCRATCH, REFERENCE_COUNTER and DUMMY_ROM_NULL take
  one 64-bit pattern under eleven strobes and a full-width restore. REFERENCE_COUNTER
  follows its write-once-then-poll rule: each strobed lane above lane 0 is written with a
  byte that differs from its pre-write byte and polled until it reads that byte, WSTRB 0x01
  is not driven, and WSTRB 0x00 is its last write.
* RESET_UNIT / BASE_CONFIG / ZERO_STROBE: the 32-bit reset-unit registers on the 64-bit
  link, GLOBAL_BASE and REGION_SIZE with their own value, and WSTRB 0x00 writes.
* WATCHDOG: the byte-enable rule and the KEY protocol of the core 3 watchdog (`wdt.adoc`).
* MUTEX, MAILBOX, ZEROER: acquire-on-read and release-on-write, the mailbox hole and
  past-extent answers, and the zeroer start.
* SIDE_EFFECT, LOCKS: ISOLATE_REQ_SMC_REG, RESET_CTRL start bits, WDT_TIMEOUT_RESET, SEMA
  and the two lock registers.

The stated behaviours are CHK lines; every unstated strobe semantics is an OBS line that is
printed and never compared (SF-012 .. SF-017, SF-034).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _REPO,
    LOCAL_BASE_RESET,
    generated_decoded_extent,
    generated_unit_at,
    generated_window,
    reg_field_encode,
)
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq
from .smc_rdl_regmap import RdlReg, rdl_register

RESP_OKAY = 0
RESP_EXOKAY = 1
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
FUSE_BOUND = 200_000
ALL64 = (1 << 64) - 1
DEADSPACE_RDATA = 0xBADCAB1E

PATTERN = 0xA1B2_C3D4_E5F6_0718
PAT32 = 0xA1B2_C3D4
ZERO_PATTERN = 0x5A5A_5A5A_5A5A_5A5A
STROBES = (0x0F, 0xF0, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x00)
BASE_STROBES = (0x03, 0x0C, 0x30, 0xC0, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x00)

# wdt.adoc:11-13, 87-95; wdt.h field masks are repeated here only as bit positions of
# the documented CTRL fields.
WDT_KEY = 0x51F15E
WDT_FEED = 0x0D09_F00D
WDT_CTRL_MASK = 0xF | (1 << 8) | (1 << 9) | (1 << 12) | (1 << 13)
WDT_CTRL_AWAKE_BITS = (1 << 12) | (1 << 13)

_ZEROER_CTRL_H = _REPO / "hw" / "ip" / "zeroer" / "regs" / "gen" / "c" / "zeroer_ctrl.h"
ZEROER_INT_EN = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
ZEROER_STATUS = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)
ZEROER_BYTES = 0x40
ZEROER_DEST_OFFSET = 0x30000
UNBACKED_LOCAL = 0xC000_1900

# Liveness ceilings, not checked quantities: expiry fails.
ZEROER_POLL_BOUND = 20_000
PULSE_BOUND = 400
FLR_POLL_BOUND = 64
REFCNT_POLL_BOUND = 64
# REFERENCE_COUNTER strobes the write-then-poll rule leaves without an observable lane.
REFCNT_NOT_DRIVEN = (0x01,)
PROBE_EDGES = 128

TERMS = (
    "SETUP",
    "PLAIN",
    "RESET_UNIT",
    "BASE_CONFIG",
    "ZERO_STROBE",
    "WATCHDOG",
    "MUTEX",
    "MAILBOX",
    "ZEROER",
    "SIDE_EFFECT",
    "LOCKS",
)
# Writes planned per fence term (strobe patterns x registers, restores and unlocks).
PLANNED_WRITES = {
    "SETUP": 6,
    "PLAIN": 13 * (len(STROBES) + 1) - len(REFCNT_NOT_DRIVEN),
    "RESET_UNIT": 4 + 3,
    "BASE_CONFIG": 2 * (len(BASE_STROBES) + 1),
    "ZERO_STROBE": 3 * 2,
    "WATCHDOG": 49,
    "MUTEX": 32,
    "MAILBOX": 6,
    "ZEROER": 5 * 11 + 3,
    "SIDE_EFFECT": 8 + 4 + 4 + 6,
    "LOCKS": 8,
}
PLANNED_OBS = {
    "OBS-PLAIN-STROBE": 13 * len(STROBES) - len(REFCNT_NOT_DRIVEN) + 10 + 2 * len(BASE_STROBES),
    "OBS-ZERO-STROBE": 5,
    "OBS-MUTEX-NARROW-RELEASE": 3,
    "OBS-MAILBOX-ACCESS": 7,
    "OBS-ZEROER-NARROW": 5,
    "OBS-SIDEEFFECT-NARROW": 16,
}
# Narrow writes: plain strobes, reset-unit pairs, base configuration and the WSTRB 0x00 targets.
PLANNED_NARROW = 13 * len(STROBES) - len(REFCNT_NOT_DRIVEN) + 5 + 2 * len(BASE_STROBES) + 3
CHECKERS = (
    "CHK-NARROW-WRITE-ACCEPTED",
    "CHK-FULL-WIDTH-RESTORE",
    "CHK-BASE-CONFIG-LEGAL",
    "CHK-OBS-PLAIN-STROBE",
    "CHK-OBS-ZERO-STROBE",
    "CHK-WDT-KEY-UNLOCK-COUNT",
    "CHK-WDT-PARTIAL-COUNT-IGNORED",
    "CHK-WDT-SCALED-CMP-BYTES",
    "CHK-WDT-CTRL-BYTES",
    "CHK-WDT-FEED-KEY-64BIT",
    "CHK-WDT-ZERO-STROBE-AND-LOCK",
    "CHK-MUTEX-LOWER-READ-ACQUIRE",
    "CHK-MUTEX-UPPER-READ-HELD",
    "CHK-MUTEX-RELEASE-AND-INDEPENDENCE",
    "CHK-OBS-MUTEX-NARROW-RELEASE",
    "CHK-MAILBOX-HOLE-SLVERR",
    "CHK-OBS-MAILBOX-ACCESS",
    "CHK-ZEROER-FULL-START",
    "CHK-OBS-ZEROER-NARROW",
    "CHK-ZEROER-COMPLETION-NOT-SUCCESS",
    "CHK-ISOLATE-SMC-W1C-STROBE",
    "CHK-RESET-CTRL-START-BIT",
    "CHK-SEMA-FULL-WRITE",
    "CHK-LOCK-BIT0-MASKS-WRITES",
    "CHK-OBS-SIDEEFFECT-NARROW",
    "CHK-TIMEOUT-PATHS",
    "CHK-NONVAC",
)


def _reg(path: str) -> RdlReg:
    return rdl_register(path)


def _hx(value: int) -> str:
    return f"0x{value:x}"


class _Core3Monitor:
    """Passive clk_smc_i sampler of the core 3 reset probe."""

    def __init__(self) -> None:
        self.falls = 0
        self.rises = 0
        self.samples = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        prev = None
        while True:
            await RisingEdge(dut.clk_smc_i)
            sample = dut.tb_cpu_core_resets_n.value
            assert sample.is_resolvable, f"tb_cpu_core_resets_n is X/Z: {sample}"
            bit = (int(sample) >> 3) & 1
            if prev is not None:
                self.falls += 1 if (prev and not bit) else 0
                self.rises += 1 if (not prev and bit) else 0
            prev = bit
            self.samples += 1


class _ZeroerMonitor:
    """Passive clk_smc_i sampler of zeroer busy and its completion interrupt."""

    def __init__(self) -> None:
        self.busy_seen = 0
        self.intp_rises = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        prev_intp = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            busy, intp = dut.tb_zeroer_busy.value, dut.tb_zeroer_intp.value
            assert busy.is_resolvable and intp.is_resolvable, f"zeroer probe X/Z {busy} {intp}"
            if int(busy):
                self.busy_seen = 1
            if int(intp) and not prev_intp:
                self.intp_rises += 1
            prev_intp = int(intp)


class smc_axil_narrow_zero_strobe_write_test_seq(output_fabric_pass_all_cfg_seq):
    """Narrow and zero-strobe writes to plain, watchdog, mutex, mailbox, zeroer and lock registers."""

    def __init__(self, name: str = "smc_axil_narrow_zero_strobe_write_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self.writes = 0
        self._stamps: list[tuple[str, int, int]] = []
        self._term_start = 0
        self._last = "none"
        self._fuse_last = "not sampled"
        self._bounded: list[tuple[str, str, str]] = []
        self.narrow_resps: list[tuple[int, int]] = []
        self.narrow_regs: set[str] = set()
        self.restored = 0
        self.held: list[str] = []
        self.obs: dict[str, int] = {k: 0 for k in PLANNED_OBS}
        self.base_writes = 0
        self.zero_polls: list[int] = []

    # ---- evidence helpers -------------------------------------------------------------
    def _mark(self, term: str) -> None:
        count = self.writes - self._term_start
        assert count > 0, f"fence term {term} did nothing"
        assert count == PLANNED_WRITES[term], (
            f"fence term {term} issued {count} writes, the plan has {PLANNED_WRITES[term]}"
        )
        self._stamps.append((term, count, int(get_sim_time("ns"))))
        self._term_start = self.writes

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    def _obs(self, family: str, text: str) -> None:
        cocotb.log.info("%s: %s", family, text)
        self.obs[family] += 1

    def _chk_obs(self, chk_id: str, family: str) -> None:
        assert self.obs[family] == PLANNED_OBS[family], (
            f"{family}: {self.obs[family]} lines, the plan has {PLANNED_OBS[family]}"
        )
        self._chk(
            chk_id, f"{self.obs[family]} {family} lines, one per planned case, never compared"
        )

    # ---- access helpers ---------------------------------------------------------------
    def _item(
        self,
        op: SmcSysAxiOp,
        label: str,
        addr: int,
        length: int,
        data: int = 0,
        wstrb: int | None = None,
        resp: int | None = None,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.wstrb = wstrb
        if resp is None:
            item.allow_error = True
        elif resp != RESP_OKAY:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = resp
        return item

    async def _acc(
        self,
        op: SmcSysAxiOp,
        label: str,
        addr: int,
        length: int,
        data: int = 0,
        wstrb: int | None = None,
        resp: int | None = None,
    ) -> SmcSysAxiItem:
        item = self._item(op, label, addr, length, data, wstrb, resp)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        strobe = "" if wstrb is None else f" wstrb=0x{wstrb:x}"
        self._last = f"{item.get_name()} 0x{addr:x}{strobe} resp={item.resp_code}"
        assert not item.timed_out, f"{item.get_name()} at 0x{addr:x}{strobe} timed out"
        assert item.resp_code is not None and item.resp_code != RESP_EXOKAY, (
            f"{item.get_name()} at 0x{addr:x}{strobe}: BRESP/RRESP {item.resp_code} is not a "
            f"legal AXI-Lite response"
        )
        if resp is not None:
            assert item.resp_code == resp, (
                f"{item.get_name()} at 0x{addr:x}{strobe} answered "
                f"{RESP_NAME[item.resp_code]}, expected {RESP_NAME[resp]}"
            )
        if op is SmcSysAxiOp.WRITE:
            self.writes += 1
        return item

    async def _wr(
        self,
        label: str,
        addr: int,
        data: int,
        length: int = 8,
        wstrb: int | None = None,
        resp: int | None = None,
    ) -> int:
        item = await self._acc(SmcSysAxiOp.WRITE, label, addr, length, data, wstrb, resp)
        return item.resp_code

    async def _rd(self, label: str, addr: int, length: int = 8, resp: int | None = None) -> int:
        return (await self._acc(SmcSysAxiOp.READ, label, addr, length, resp=resp)).rdata

    async def _rd_item(self, label: str, addr: int, length: int = 8) -> SmcSysAxiItem:
        return await self._acc(SmcSysAxiOp.READ, label, addr, length)

    def _narrow(self, reg: str, resp: int) -> None:
        self.narrow_resps.append((self.writes, resp))
        self.narrow_regs.add(reg)

    def _restore_word(self, name: str, pre: int, got: int, saved: int, mask: int | None) -> None:
        """Grade one full-width restore of `saved`.

        With `mask`, the strobed writes must have left the register differing from `saved` in
        those writable bits, and only then does the restore count for CHK-FULL-WIDTH-RESTORE.
        Without it the register already holds `saved`, so the restore cannot fail on a dropped
        write and is listed apart.
        """
        cocotb.log.info(
            "INFO-RESTORE-WORD: reg=%s pre=%s post=%s saved=%s counted=%s",
            name,
            _hx(pre),
            _hx(got),
            _hx(saved),
            "no" if mask is None else "yes",
        )
        assert got == saved, f"{name}: full-width restore of 0x{saved:x} reads 0x{got:x}"
        if mask is None:
            self.held.append(name)
            return
        assert (pre ^ saved) & mask, (
            f"{name}: reads 0x{pre:x} before the restore, equal to the saved 0x{saved:x} in the "
            f"writable bits 0x{mask:x}, so the strobed writes changed nothing"
        )
        self.restored += 1

    async def _restore_check(
        self, name: str, addr: int, saved: int, length: int, mask: int | None
    ) -> None:
        pre = await self._rd(f"{name}_RESTORE_PRE", addr, length)
        await self._wr(f"{name}_RESTORE", addr, saved, length)
        got = await self._rd(f"{name}_RESTORE_RB", addr, length)
        self._restore_word(name, pre, got, saved, mask)

    # ---- body ---------------------------------------------------------------------------
    async def body(self) -> None:
        await self._setup()
        await self._plain()
        await self._reset_unit()
        await self._base_config()
        await self._zero_strobe()
        await self._watchdog()
        await self._mutex()
        await self._mailbox()
        await self._zeroer()
        await self._side_effects()
        await self._locks()
        self._finish()

    async def _setup(self) -> None:
        # S1.
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_BOUND)
        fuse = dut.tb_fuse_sense_done.value
        assert fuse.is_resolvable and int(fuse) == 1, f"tb_fuse_sense_done is {fuse}"
        self._fuse_last = f"tb_fuse_sense_done={int(fuse)}"
        dut.tb_cfg_flr_pf_active.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self.writes += 6

        self.plain = (
            [_reg(f"smc_cpu_ctrl/RESET_VECTOR[{i}]") for i in range(4)]
            + [_reg(f"smc_cpu_ctrl/SCRATCH[{i}]") for i in range(4)]
            + [_reg("smc_cpu_ctrl/REFERENCE_COUNTER")]
            + [_reg(f"smc_cpu_ctrl/DUMMY_ROM_NULL[{i}]") for i in range(4)]
        )
        assert len(self.plain) == 13
        self.ss_cfg = _reg("smc_reset_unit/SS_CONFIG")
        self.ss_lock = _reg("smc_reset_unit/SS_CONFIG_LOCK")
        self.cold_n = _reg("smc_reset_unit/SS_COLD_RESET_N")
        self.cold_lock = _reg("smc_reset_unit/SS_COLD_RESET_LOCK")
        self.iso_req = _reg("smc_reset_unit/ISOLATE_REQ_REG")
        self.iso_pinen = _reg("smc_reset_unit/ISOLATE_REQ_PINEN_REG")
        self.iso_smc = _reg("smc_reset_unit/ISOLATE_REQ_SMC_REG")
        self.flr_reset_cnt = _reg("smc_reset_unit/ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")
        self.gbase = _reg("smc_base_config/GLOBAL_BASE")
        self.rsize = _reg("smc_base_config/REGION_SIZE")
        self.filter_start = _reg("smc_inbound_filter_ctrl_wrap/filter_ctrl[15]/START_ADDR")
        self.scratch0 = self.plain[4]
        self.reset_ctrl = _reg("smc_cpu_ctrl/RESET_CTRL")
        self.wdt_to_reset = _reg("smc_cpu_ctrl/WDT_TIMEOUT_RESET")
        self.sema0 = _reg("smc_cpu_ctrl/SEMA[0]")
        self.mutex = [_reg(f"smc_cpu_ctrl/MUTEX[{i}]") for i in range(4)]
        self.wdt = {
            n: _reg(f"smc_cluster_core3_wdt/{n}")
            for n in ("CTRL", "COUNT", "COUNT_HI", "SCALED_COUNT", "FEED", "KEY", "CMP")
        }
        assert self.ss_lock.addr == self.ss_cfg.addr + 4
        assert self.iso_pinen.addr == self.iso_req.addr + 4
        assert self.wdt["KEY"].addr == self.wdt["FEED"].addr + 4

        self.saved: dict[str, int] = {}
        for reg in (
            *self.plain,
            self.gbase,
            self.rsize,
            self.filter_start,
        ):
            self.saved[reg.path] = await self._rd(f"SAVE_{reg.symbol}", reg.addr, 8)
        for reg in (
            self.ss_cfg,
            self.ss_lock,
            self.cold_n,
            self.cold_lock,
            self.iso_req,
            self.iso_pinen,
            self.flr_reset_cnt,
            self.wdt_to_reset,
        ):
            self.saved[reg.path] = await self._rd(f"SAVE_{reg.symbol}", reg.addr, 4)
        self.saved[self.sema0.path] = await self._rd("SAVE_SEMA0", self.sema0.addr, 8)
        self.saved[self.reset_ctrl.path] = await self._rd(
            "SAVE_RESET_CTRL", self.reset_ctrl.addr, 8
        )
        for n in ("CTRL", "COUNT", "SCALED_COUNT", "CMP"):
            self.saved["wdt_" + n] = await self._rd(f"SAVE_WDT_{n}", self.wdt[n].addr, 4)
        cocotb.log.info(
            "S1 saved %d registers; patterns 0x0F 0xF0 0x01..0x80 0x00 (restore values read here)",
            len(self.saved),
        )
        self._mark("SETUP")

    def _pre(self, reg: RdlReg) -> int:
        return self.saved[reg.path]

    @staticmethod
    def _lanes(strobe: int) -> list[int]:
        return [b for b in range(1, 8) if strobe >> b & 1]

    async def _refcnt_poll(self, label: str, addr: int, wrote: int, lanes: list[int]) -> int:
        """Poll REFERENCE_COUNTER until every lane in `lanes` reads its byte of `wrote`.

        cpu_ctrl.rdl REFERENCE_COUNTER: write once, then poll until the readback reflects the
        written value before writing again. Lane 0 advances, so only lanes above it are polled;
        each of them was written with a byte different from its pre-write byte.
        """
        mask = sum(0xFF << (8 * b) for b in lanes)
        assert mask, f"{label}: no lane above lane 0 to poll"
        rb = 0
        for i in range(REFCNT_POLL_BOUND):
            rb = await self._rd(f"{label}_POLL", addr, 8)
            if rb & mask == wrote & mask:
                self._bounded.append(
                    (f"refcnt_{label}", f"{REFCNT_POLL_BOUND} polls", f"reflected after {i + 1}")
                )
                return rb
        raise AssertionError(
            f"{label}: REFERENCE_COUNTER lanes 0x{mask:x} never read 0x{wrote & mask:x} "
            f"within {REFCNT_POLL_BOUND} polls, last readback 0x{rb:x}"
        )

    async def _refcnt_write(self, name: str, addr: int, s: int) -> None:
        pre = await self._rd(f"{name}_W{s:02X}_PRE", addr, 8)
        data = PATTERN
        for b in self._lanes(s):
            # Half-word strobes complement the pre byte, single-byte strobes XOR it with the
            # pattern byte, so no lane ends the sweep back at its saved byte.
            flip = 0xFF if bin(s).count("1") > 1 else (PATTERN >> (8 * b)) & 0xFF
            byte = ((pre >> (8 * b)) & 0xFF) ^ flip
            data = (data & ~(0xFF << (8 * b))) | (byte << (8 * b))
        resp = await self._wr(f"{name}_W{s:02X}", addr, data, 8, s)
        rb = await self._rd(f"{name}_W{s:02X}_RB", addr, 8)
        if s:
            await self._refcnt_poll(f"{name}_W{s:02X}", addr, data, self._lanes(s))
        self._narrow(name, resp)
        self._obs(
            "OBS-PLAIN-STROBE",
            f"reg={name} wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
            f"wrote={_hx(data)} readback={_hx(rb)}",
        )

    async def _refcnt(self, reg: RdlReg) -> None:
        name = reg.path.split("/")[-1]
        cocotb.log.info(
            "INFO-CELL-NOT-DRIVABLE: REFERENCE_COUNTER WSTRB 0x01 (write-then-poll protocol has "
            "no observable lane; SF-012)"
        )
        for s in STROBES:
            if s and s not in REFCNT_NOT_DRIVEN:
                await self._refcnt_write(name, reg.addr, s)
        saved = self._pre(reg)
        pre = await self._rd(f"{name}_RESTORE_PRE", reg.addr, 8)
        upper = ALL64 & ~0xFF
        assert pre & upper != saved & upper, (
            f"{name}: lanes 1..7 read 0x{pre:x} before the restore, equal to the saved 0x{saved:x}"
        )
        await self._wr(f"{name}_RESTORE", reg.addr, saved, 8)
        await self._refcnt_poll(f"{name}_RESTORE", reg.addr, saved, list(range(1, 8)))
        await self._refcnt_write(name, reg.addr, 0x00)

    async def _plain(self) -> None:
        # S2.
        for reg in self.plain:
            if reg is self.plain[8]:
                await self._refcnt(reg)
                continue
            name = reg.path.split("/")[-1]
            for s in STROBES:
                resp = await self._wr(f"{name}_W{s:02X}", reg.addr, PATTERN, 8, s)
                rb = await self._rd(f"{name}_W{s:02X}_RB", reg.addr, 8)
                self._narrow(name, resp)
                self._obs(
                    "OBS-PLAIN-STROBE",
                    f"reg={name} wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                    f"wrote={_hx(PATTERN)} readback={_hx(rb)}",
                )
            await self._restore_check(name, reg.addr, self._pre(reg), 8, reg.rw_mask)
        self._mark("PLAIN")

    async def _reset_unit(self) -> None:
        # S3.
        pairs = (
            (self.ss_cfg, self.ss_lock, True),
            (self.iso_req, self.iso_pinen, False),
        )
        for lo, hi, locked in pairs:
            lo_s, hi_s = self._pre(lo), self._pre(hi)
            for s in (0x0F, 0xF0) + ((0xFF,) if locked else ()):
                if s == 0x0F:
                    data = ((0 if locked else hi_s) << 32) | PAT32
                elif s == 0xF0:
                    data = ((0 if locked else PAT32) << 32) | lo_s
                else:
                    data = PAT32
                resp = await self._wr(
                    f"{lo.symbol}_W{s:02X}", lo.addr, data, 8, None if s == 0xFF else s
                )
                self._narrow(lo.path.split("/")[-1], resp)
                lo_rb = await self._rd(f"{lo.symbol}_W{s:02X}_RB", lo.addr, 4)
                hi_rb = await self._rd(f"{hi.symbol}_W{s:02X}_RB", hi.addr, 4)
                for reg, wrote, rb in (
                    (lo, data & 0xFFFF_FFFF, lo_rb),
                    (hi, data >> 32, hi_rb),
                ):
                    self._obs(
                        "OBS-PLAIN-STROBE",
                        f"reg={reg.path.split('/')[-1]} wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                        f"wrote={_hx(wrote)} readback={_hx(rb)}",
                    )
            lo_pre = await self._rd(f"{lo.symbol}_RESTORE_PRE", lo.addr, 4)
            hi_pre = await self._rd(f"{hi.symbol}_RESTORE_PRE", hi.addr, 4)
            await self._wr(f"{lo.symbol}_RESTORE", lo.addr, (hi_s << 32) | lo_s, 8)
            lo_rb = await self._rd(f"{lo.symbol}_RESTORE_RB", lo.addr, 4)
            hi_rb = await self._rd(f"{hi.symbol}_RESTORE_RB", hi.addr, 4)
            self._restore_word(lo.path.split("/")[-1], lo_pre, lo_rb, lo_s, lo.rw_mask)
            if locked:
                # The lock lane is written 0 at every step, so only the configuration counts.
                assert hi_rb == hi_s, f"{hi.path} restore reads 0x{hi_rb:x}, saved 0x{hi_s:x}"
            else:
                self._restore_word(hi.path.split("/")[-1], hi_pre, hi_rb, hi_s, hi.rw_mask)
        self._mark("RESET_UNIT")

    async def _base_config(self) -> None:
        # S4.
        legal = 0

        def _legal(gb: int, rs: int, where: str) -> None:
            assert rs != 0 and (rs & (rs - 1)) == 0, (
                f"{where}: REGION_SIZE reads 0x{rs:x}, not a non-zero power of two"
            )
            assert gb % rs == 0, f"{where}: GLOBAL_BASE 0x{gb:x} is not aligned with 0x{rs:x}"

        for reg in (self.gbase, self.rsize):
            name = reg.path.split("/")[-1]
            cur = self._pre(reg)
            for s in BASE_STROBES:
                before = None
                if s == 0x00:
                    before = await self._rd(f"{name}_ZERO_BEFORE", reg.addr, 8)
                resp = await self._wr(f"{name}_W{s:02X}", reg.addr, cur, 8, s)
                self._narrow(name, resp)
                gb = await self._rd(f"{name}_W{s:02X}_GB", self.gbase.addr, 8)
                rs = await self._rd(f"{name}_W{s:02X}_RS", self.rsize.addr, 8)
                _legal(gb, rs, f"{name} wstrb 0x{s:02x}")
                legal += 1
                rb = gb if reg is self.gbase else rs
                if s == 0x00:
                    self._obs(
                        "OBS-ZERO-STROBE",
                        f"reg={name} bresp={RESP_NAME[resp]} before={_hx(before)} after={_hx(rb)}",
                    )
                self._obs(
                    "OBS-PLAIN-STROBE",
                    f"reg={name} wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                    f"wrote={_hx(cur)} readback={_hx(rb)}",
                )
            await self._restore_check(name, reg.addr, cur, 8, None)
        self.base_writes = legal
        self._chk(
            "CHK-BASE-CONFIG-LEGAL",
            f"{legal} writes, REGION_SIZE power of two and GLOBAL_BASE aligned after each",
        )
        self._mark("BASE_CONFIG")

    async def _zero_strobe(self) -> None:
        # S5.
        targets = (
            (self.scratch0, 8, 8),
            (self.ss_cfg, 4, 8),
            (self.filter_start, 8, 8),
        )
        for reg, rd_len, wr_len in targets:
            name = reg.path.split("/")[-1]
            before = await self._rd(f"{name}_ZERO_BEFORE", reg.addr, rd_len)
            resp = await self._wr(f"{name}_ZERO", reg.addr, ZERO_PATTERN, wr_len, 0x00)
            self._narrow(name, resp)
            after = await self._rd(f"{name}_ZERO_AFTER", reg.addr, rd_len)
            self._obs(
                "OBS-ZERO-STROBE",
                f"reg={name} bresp={RESP_NAME[resp]} before={_hx(before)} after={_hx(after)}",
            )
            if reg is self.ss_cfg:
                pre = await self._rd("SS_CONFIG_RESTORE_PRE", reg.addr, 4)
                await self._wr(
                    "SS_CONFIG_RESTORE",
                    reg.addr,
                    (self._pre(self.ss_lock) << 32) | self._pre(reg),
                    8,
                )
                got = await self._rd("SS_CONFIG_RESTORE_RB", reg.addr, 4)
                self._restore_word(name, pre, got, self._pre(reg), None)
            else:
                await self._restore_check(name, reg.addr, self._pre(reg), 8, None)
        m = len(self.narrow_regs)
        n = len(self.narrow_resps)
        assert n == PLANNED_NARROW, f"{n} narrow writes, the plan has {PLANNED_NARROW}"
        self._chk(
            "CHK-NARROW-WRITE-ACCEPTED",
            f"{n}/{PLANNED_NARROW} planned writes over {m} registers each with one legal B "
            f"response; the plan excludes the not-driven REFERENCE_COUNTER WSTRB 0x01",
        )
        assert self.restored == 15, (
            f"{self.restored} restores of a register its strobed writes changed, the plan has 15"
        )
        assert len(self.held) == 5, f"{len(self.held)} restores of a held value, the plan has 5"
        self._chk(
            "CHK-FULL-WIDTH-RESTORE",
            f"{self.restored} registers restored and read back equal, each read before its "
            f"restore differing from the saved value in its writable bits; {len(self.held)} "
            f"restores rewrite the value the register already holds and are not counted "
            f"({' '.join(self.held)})",
        )
        self._chk_obs("CHK-OBS-PLAIN-STROBE", "OBS-PLAIN-STROBE")
        self._chk_obs("CHK-OBS-ZERO-STROBE", "OBS-ZERO-STROBE")
        self._mark("ZERO_STROBE")

    # ---- watchdog -----------------------------------------------------------------------
    async def _wdt_unlock(self, tag: str) -> None:
        w = self.wdt
        await self._wr(f"WDT_KEY_{tag}", w["KEY"].addr, WDT_KEY, 4, 0xF, RESP_OKAY)
        key = await self._rd(f"WDT_KEY_{tag}_RB", w["KEY"].addr, 4)
        assert key == 1, f"KEY reads 0x{key:x} after the key write ({tag}), expected 1"

    async def _wdt_write(self, label: str, name: str, data: int, wstrb: int) -> None:
        await self._wr(f"WDT_{name}_{label}", self.wdt[name].addr, data, 4, wstrb, RESP_OKAY)

    async def _wdt_read(self, label: str, name: str) -> int:
        return await self._rd(f"WDT_{name}_{label}", self.wdt[name].addr, 4)

    async def _watchdog(self) -> None:
        # S6.
        ctrl0 = self.saved["wdt_CTRL"]
        cmp0 = self.saved["wdt_CMP"]
        assert ctrl0 & WDT_CTRL_AWAKE_BITS == 0, (
            f"CTRL 0x{ctrl0:x} counts (wdogenalways / wdogcoreawake set); the leaf needs a "
            f"static count"
        )
        # (S1) all-strobe unlock and COUNT write.
        await self._wdt_unlock("S1")
        await self._wdt_write("1234", "COUNT", 0x1234, 0xF)
        count = await self._wdt_read("S1_RB", "COUNT")
        key = await self._wdt_read("S1_KEY", "KEY")
        assert count == 0x1234, f"COUNT reads 0x{count:x} after the full-strobe write of 0x1234"
        assert key == 0, f"KEY reads 0x{key:x} after the effective COUNT write, expected 0"
        self._chk(
            "CHK-WDT-KEY-UNLOCK-COUNT",
            "KEY 1 after unlock; COUNT 0x1234; KEY 0 after COUNT write",
        )
        # (S2) partial COUNT writes.
        for s in (0x07, 0x03, 0x01):
            await self._wdt_unlock(f"S2_{s:02X}")
            await self._wdt_write(f"P{s:02X}", "COUNT", 0x5555_5555, s)
            count = await self._wdt_read(f"P{s:02X}_RB", "COUNT")
            key = await self._wdt_read(f"P{s:02X}_KEY", "KEY")
            assert count == 0x1234, f"COUNT reads 0x{count:x} after strobe 0x{s:02x}, kept 0x1234"
            assert key == 1, f"KEY reads 0x{key:x} after strobe 0x{s:02x}, expected 1 (unlocked)"
        self._chk(
            "CHK-WDT-PARTIAL-COUNT-IGNORED",
            "strobes 7/3/1: OKAY, COUNT 0x1234 kept, KEY 1 kept",
        )
        # (S3) CMP and SCALED_COUNT byte rules.
        await self._wdt_unlock("S3_CMP")
        await self._wdt_write("0ABC", "CMP", 0x0ABC, 0x03)
        cmp_v = await self._wdt_read("0ABC_RB", "CMP")
        key = await self._wdt_read("0ABC_KEY", "KEY")
        assert cmp_v == 0x0ABC, f"CMP reads 0x{cmp_v:x} after bytes 0 and 1 of 0x0ABC"
        assert key == 0, f"KEY reads 0x{key:x} after the effective CMP write, expected 0"
        for s in (0x01, 0x0C):
            await self._wdt_unlock(f"S3_CMP_{s:02X}")
            await self._wdt_write(f"0123_{s:02X}", "CMP", 0x0123, s)
            cmp_v = await self._wdt_read(f"0123_{s:02X}_RB", "CMP")
            key = await self._wdt_read(f"0123_{s:02X}_KEY", "KEY")
            assert cmp_v == 0x0ABC, f"CMP reads 0x{cmp_v:x} after strobe 0x{s:02x}, kept 0x0ABC"
            assert key == 1, f"KEY reads 0x{key:x} after CMP strobe 0x{s:02x}, expected 1"
        for s, locks in ((0x03, True), (0x01, False), (0x0C, False)):
            await self._wdt_unlock(f"S3_SC_{s:02X}")
            await self._wdt_write(f"S{s:02X}", "SCALED_COUNT", 0x0123, s)
            key = await self._wdt_read(f"S{s:02X}_KEY", "KEY")
            assert key == (0 if locks else 1), (
                f"KEY reads 0x{key:x} after SCALED_COUNT strobe 0x{s:02x}, "
                f"expected {0 if locks else 1}"
            )
        self._chk(
            "CHK-WDT-SCALED-CMP-BYTES",
            "CMP bytes0-1 effective 0x0ABC; byte0-only and bytes2-3 ignored; "
            "SCALED_COUNT lock only on bytes0-1",
        )
        # (S4) CTRL bytes.
        base_ctrl = ctrl0 & WDT_CTRL_MASK & ~0xF
        await self._wdt_unlock("S4_B0")
        await self._wdt_write("B0", "CTRL", 0x0000_0003, 0x01)
        ctrl = await self._wdt_read("B0_RB", "CTRL")
        assert ctrl & WDT_CTRL_MASK == base_ctrl | 0x3, (
            f"CTRL reads 0x{ctrl:x} after byte 0 of 0x3, expected wdogscale 3 and no other field"
        )
        await self._wdt_unlock("S4_B1")
        await self._wdt_write("B1", "CTRL", 0x0000_0300, 0x02)
        ctrl = await self._wdt_read("B1_RB", "CTRL")
        assert ctrl & WDT_CTRL_MASK == base_ctrl | 0x3 | 0x300, (
            f"CTRL reads 0x{ctrl:x} after byte 1 of 0x300, expected wdogrsten, wdogzerocmp set "
            f"and wdogscale still 3"
        )
        self._chk(
            "CHK-WDT-CTRL-BYTES",
            "byte0-only: wdogscale=3 only; byte1-only: wdogrsten/wdogzerocmp set, wdogscale 3",
        )
        # (S5) 64-bit FEED / KEY write.
        await self._wdt_unlock("S5")
        await self._wr("WDT_FEED_KEY_64", self.wdt["FEED"].addr, WDT_FEED, 8, 0xFF, RESP_OKAY)
        key = await self._wdt_read("S5_KEY", "KEY")
        assert key == 0, f"KEY reads 0x{key:x} after the 64-bit FEED/KEY write, expected 0"
        self._chk("CHK-WDT-FEED-KEY-64BIT", "64-bit write at 0x18: KEY reads 0 (locked)")
        # (S6) zero strobes and the lock.
        names = ("CTRL", "COUNT", "COUNT_HI", "SCALED_COUNT", "FEED", "KEY", "CMP")
        for n in names:
            await self._wdt_unlock(f"S6_{n}")
            before = {m: await self._wdt_read(f"Z_{n}_B_{m}", m) for m in names}
            await self._wdt_write("ZERO", n, 0x5555_5555, 0x00)
            after = {m: await self._wdt_read(f"Z_{n}_A_{m}", m) for m in names}
            assert after == before, (
                f"WSTRB 0 write to {n} changed the register set: before "
                f"{ {k: hex(v) for k, v in before.items()} } after "
                f"{ {k: hex(v) for k, v in after.items()} }"
            )
            assert after["KEY"] == 1, f"KEY reads 0x{after['KEY']:x} after the WSTRB 0 write to {n}"
        await self._wdt_unlock("S6_LOCK")
        await self._wdt_write("0042", "COUNT", 0x42, 0xF)
        key = await self._wdt_read("0042_KEY", "KEY")
        assert key == 0, f"KEY reads 0x{key:x} after the effective COUNT write, expected 0"
        await self._wdt_write("0099_LOCKED", "COUNT", 0x99, 0xF)
        count = await self._wdt_read("LOCKED_RB", "COUNT")
        assert count == 0x42, f"COUNT reads 0x{count:x} after a locked write of 0x99, kept 0x42"
        self._chk(
            "CHK-WDT-ZERO-STROBE-AND-LOCK",
            "7 registers WSTRB 0: OKAY, no change, KEY 1; effective write locks; locked write ignored",
        )
        # Restore CTRL, CMP and COUNT.
        for n, value in (("CTRL", ctrl0 & WDT_CTRL_MASK), ("CMP", cmp0), ("COUNT", 0)):
            await self._wdt_unlock(f"RESTORE_{n}")
            await self._wdt_write("RESTORE", n, value, 0xF)
        cmp_v = await self._wdt_read("RESTORE_CMP_RB", "CMP")
        count = await self._wdt_read("RESTORE_COUNT_RB", "COUNT")
        ctrl = await self._wdt_read("RESTORE_CTRL_RB", "CTRL")
        assert cmp_v == cmp0, f"CMP restore reads 0x{cmp_v:x}, saved 0x{cmp0:x}"
        assert count == 0, f"COUNT restore reads 0x{count:x}"
        cocotb.log.info("S6 restored CTRL=0x%x CMP=0x%x COUNT=0x%x", ctrl, cmp_v, count)
        self._mark("WATCHDOG")

    # ---- mutexes ------------------------------------------------------------------------
    async def _release_all(self, tag: str) -> None:
        for i, m in enumerate(self.mutex):
            await self._wr(f"MUTEX{i}_RELEASE_{tag}", m.addr, 0, 8)

    async def _mutex(self) -> None:
        # S7.
        m0 = self.mutex[0].addr
        await self._release_all("INIT")

        async def expect(label: str, addr: int, length: int, want: int, what: str) -> None:
            got = (await self._rd(label, addr, length)) & 1
            assert got == want, (
                f"{what}: read at 0x{addr:x} ({length} bytes) returns {got}, expected {want}"
            )

        # Lower-half reads acquire.
        for tag, off, length in (("R64", 0, 8), ("R32", 0, 4), ("RB", 0, 1)):
            await expect(f"MUTEX0_{tag}_FIRST", m0 + off, length, 1, f"MUTEX[0] {tag} first read")
            await expect(f"MUTEX0_{tag}_SECOND", m0, 8, 0, f"MUTEX[0] read after the {tag}")
            await self._wr(f"MUTEX0_{tag}_RELEASE", m0, 0, 8)
        self._chk("CHK-MUTEX-LOWER-READ-ACQUIRE", "64-bit/32-bit/byte at +0 -> 1; next read 0")
        # Upper-half reads acquire without returning 1.
        await expect("MUTEX0_R32_PLUS4", m0 + 4, 4, 0, "MUTEX[0] 32-bit read at +4")
        await expect("MUTEX0_AFTER_PLUS4", m0, 8, 0, "MUTEX[0] read after the +4 read")
        await self._wr("MUTEX0_PLUS4_RELEASE", m0, 0, 8)
        await expect("MUTEX0_AFTER_RELEASE", m0, 8, 1, "MUTEX[0] read after the full-write release")
        await self._wr("MUTEX0_PLUS4_RELEASE2", m0, 0, 8)
        await expect("MUTEX0_RB_PLUS3", m0 + 3, 1, 0, "MUTEX[0] byte read at +3")
        await expect("MUTEX0_AFTER_PLUS3", m0, 8, 0, "MUTEX[0] read after the +3 read")
        await self._wr("MUTEX0_PLUS3_RELEASE", m0, 0, 8)
        self._chk(
            "CHK-MUTEX-UPPER-READ-HELD",
            "+4 and byte +3 read 0 and acquire; held until full write; then read 1",
        )
        # Independence.
        await expect("MUTEX1_ACQUIRE", self.mutex[1].addr, 8, 1, "MUTEX[1] acquire")
        for i in (0, 2, 3):
            await expect(
                f"MUTEX{i}_INDEP", self.mutex[i].addr, 8, 1, f"MUTEX[{i}] with MUTEX[1] held"
            )
            await self._wr(f"MUTEX{i}_INDEP_RELEASE", self.mutex[i].addr, 0, 8)
        await self._wr("MUTEX1_INDEP_RELEASE", self.mutex[1].addr, 0, 8)
        self._chk(
            "CHK-MUTEX-RELEASE-AND-INDEPENDENCE",
            "full write releases; MUTEX[1] acquire leaves 0/2/3 free",
        )
        # Narrow releases are observed only.
        for s in (0x01, 0xF0, 0x00):
            await self._release_all(f"NARROW{s:02X}")
            held = (await self._rd(f"MUTEX0_NARROW{s:02X}_ACQ", m0, 8)) & 1
            resp = await self._wr(f"MUTEX0_NARROW{s:02X}", m0, 0, 8, s)
            nxt = (await self._rd(f"MUTEX0_NARROW{s:02X}_NEXT", m0, 8)) & 1
            self._obs(
                "OBS-MUTEX-NARROW-RELEASE",
                f"wstrb=0x{s:02x} bresp={RESP_NAME[resp]} next_read={nxt} (acquire read {held})",
            )
            await self._wr(f"MUTEX0_NARROW{s:02X}_RELEASE", m0, 0, 8)
        self._chk_obs("CHK-OBS-MUTEX-NARROW-RELEASE", "OBS-MUTEX-NARROW-RELEASE")
        self._mark("MUTEX")

    # ---- mailbox ------------------------------------------------------------------------
    async def _mailbox(self) -> None:
        # S8.
        wr = _reg("smc_mailbox/outbound_mailbox_0/WRITE_DATA")
        rd = _reg("smc_mailbox/outbound_mailbox_0/READ_DATA")
        st_out = _reg("smc_mailbox/outbound_mailbox_0/STATUS")
        st_in = _reg("smc_mailbox/inbound_mailbox_0/STATUS")
        last_reg = _reg("smc_mailbox/outbound_mailbox_0/CTRL")

        async def status() -> str:
            a = await self._rd("MBOX_STATUS_OUT", st_out.addr, 8)
            b = await self._rd("MBOX_STATUS_IN", st_in.addr, 8)
            return f"{a:x}/{b:x}"

        for name, s in (
            ("write64", None),
            ("write_half0F", 0x0F),
            ("write_byte01", 0x01),
            ("write_zero00", 0x00),
        ):
            before = await status()
            resp = await self._wr(f"MBOX_{name}", wr.addr, 0x1122_3344_5566_7788, 8, s)
            after = await status()
            self._obs(
                "OBS-MAILBOX-ACCESS",
                f"access={name} resp={RESP_NAME[resp]} data=none status_before={before} after={after}",
            )
        for name, addr, length in (
            ("read64", rd.addr, 8),
            ("read32_upper", rd.addr + 4, 4),
            ("read_byte0", rd.addr, 1),
        ):
            before = await status()
            item = await self._rd_item(f"MBOX_{name}", addr, length)
            after = await status()
            self._obs(
                "OBS-MAILBOX-ACCESS",
                f"access={name} resp={RESP_NAME[item.resp_code]} data={_hx(item.rdata)} "
                f"status_before={before} after={after}",
            )
        hole = last_reg.addr + 8
        base = LOCAL_BASE_RESET + generated_window("smc_mailbox")[0]
        past = base + generated_decoded_extent("smc_mailbox")
        assert base <= hole < past, f"hole 0x{hole:x} outside the mailbox window"
        hole_rd = await self._acc(SmcSysAxiOp.READ, "MBOX_HOLE_RD", hole, 4, resp=RESP_SLVERR)
        await self._acc(SmcSysAxiOp.WRITE, "MBOX_HOLE_WR", hole, 4, 0x1, resp=RESP_SLVERR)
        past_rd = await self._acc(SmcSysAxiOp.READ, "MBOX_PAST_RD", past, 4, resp=RESP_DECERR)
        await self._acc(SmcSysAxiOp.WRITE, "MBOX_PAST_WR", past, 4, 0x1, resp=RESP_DECERR)
        assert hole_rd.rdata == 0, f"mailbox hole read returns 0x{hole_rd.rdata:x}, expected 0x0"
        assert past_rd.rdata == DEADSPACE_RDATA, (
            f"past-extent read returns 0x{past_rd.rdata:x}, expected 0x{DEADSPACE_RDATA:x}"
        )
        self._chk(
            "CHK-MAILBOX-HOLE-SLVERR",
            "hole SLVERR 0x0 / SLVERR; past extent DECERR 0xBADCAB1E / DECERR",
        )
        self._chk_obs("CHK-OBS-MAILBOX-ACCESS", "OBS-MAILBOX-ACCESS")
        self._mark("MAILBOX")

    # ---- zeroer -------------------------------------------------------------------------
    async def _zeroer_poll(self, label: str) -> tuple[int, int]:
        """Poll CTRL_STATUS until STATUS reads 0; return (polls, first word)."""
        status = self.zr_status
        first = None
        for i in range(ZEROER_POLL_BOUND):
            word = await self._rd(f"{label}_POLL", status.addr, 8)
            if first is None:
                first = word
            if not word & ZEROER_STATUS:
                self.zero_polls.append(i + 1)
                self._bounded.append(
                    (
                        f"zeroer_status_{label}",
                        f"{ZEROER_POLL_BOUND} polls",
                        f"cleared after {i + 1}",
                    )
                )
                return i + 1, first
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: CTRL_STATUS bit 32 still set after {ZEROER_POLL_BOUND} polls, "
            f"last word 0x{word:x}"
        )

    async def _zeroer_prepare(self, label: str, dest: int, size: int) -> None:
        await self._wr(f"ZEROER_DEST_{label}", self.zr_dest.addr, dest, 8)
        await self._wr(f"ZEROER_SIZE_{label}", self.zr_size.addr, size, 8)

    async def _zeroer_fill(self, label: str) -> None:
        for k in range(ZEROER_BYTES // 8):
            await self._wr(f"ZEROER_FILL_{label}_{k}", self.zr_region + 8 * k, ALL64, 8)

    async def _zeroer_bytes(self, label: str) -> bytes:
        out = b""
        for k in range(ZEROER_BYTES // 8):
            word = await self._rd(f"ZEROER_READ_{label}_{k}", self.zr_region + 8 * k, 8)
            out += word.to_bytes(8, "little")
        return out

    async def _zeroer_shape(self, label: str, wstrb: int | None, data: int, stated: bool):
        await self._zeroer_prepare(label, self.zr_region, ZEROER_BYTES)
        await self._zeroer_fill(label)
        mon = _ZeroerMonitor()
        mon.start()
        try:
            resp = await self._wr(
                f"ZEROER_START_{label}",
                self.zr_status.addr,
                data,
                8,
                wstrb,
                RESP_OKAY if stated else None,
            )
            polls, first = await self._zeroer_poll(label)
            await self._rd(f"ZEROER_AFTER_{label}", self.zr_status.addr, 8)
        finally:
            mon.stop()
        content = await self._zeroer_bytes(label)
        rose = 1 if (first & ZEROER_STATUS or mon.busy_seen) else 0
        return resp, rose, content, mon.intp_rises

    async def _zeroer(self) -> None:
        # S9.
        self.zr_dest = _reg("zeroer_ctrl/DEST_ADDR")
        self.zr_size = _reg("zeroer_ctrl/SIZE")
        self.zr_status = _reg("zeroer_ctrl/CTRL_STATUS")
        self.zr_region = LOCAL_BASE_RESET + generated_window("spm_memory")[0] + ZEROER_DEST_OFFSET
        resp, rose, content, pulses = await self._zeroer_shape("FULL", None, 0, True)
        zeroed = sum(1 for b in content if b == 0)
        assert zeroed == ZEROER_BYTES, f"zeroer full start zeroed {zeroed}/{ZEROER_BYTES} bytes"
        self._obs(
            "OBS-ZEROER-NARROW",
            f"wstrb=0xff status_rose={rose} bytes_changed={sum(1 for b in content if b != 0xFF)} "
            f"pulse={1 if pulses else 0}",
        )
        self._chk(
            "CHK-ZEROER-FULL-START", f"start write 0; STATUS[32] unset; {zeroed}/64 bytes zeroed"
        )
        for label, s, data in (("LO0F", 0x0F, 0), ("HI_F0", 0xF0, 0), ("ZERO00", 0x00, 0)):
            resp, rose, content, pulses = await self._zeroer_shape(label, s, data, False)
            self._obs(
                "OBS-ZEROER-NARROW",
                f"wstrb=0x{s:02x} status_rose={rose} "
                f"bytes_changed={sum(1 for b in content if b != 0xFF)} pulse={1 if pulses else 0}",
            )
        resp, rose, content, pulses = await self._zeroer_shape("INT_EN", None, ZEROER_INT_EN, False)
        self._obs(
            "OBS-ZEROER-NARROW",
            f"wstrb=0xff+INT_EN status_rose={rose} "
            f"bytes_changed={sum(1 for b in content if b != 0xFF)} pulse={1 if pulses else 0}",
        )
        self._chk_obs("CHK-OBS-ZEROER-NARROW", "OBS-ZEROER-NARROW")
        assert generated_unit_at(UNBACKED_LOCAL - LOCAL_BASE_RESET) is None, (
            f"0x{UNBACKED_LOCAL:x} is mapped"
        )
        await self._zeroer_prepare("ERR", UNBACKED_LOCAL, 8)
        dest = await self._rd("ZEROER_DEST_ERR_RB", self.zr_dest.addr, 8)
        size = await self._rd("ZEROER_SIZE_ERR_RB", self.zr_size.addr, 8)
        assert (dest, size) == (UNBACKED_LOCAL, 8), (
            f"error destination: DEST_ADDR/SIZE read 0x{dest:x}/0x{size:x}, "
            f"programmed 0x{UNBACKED_LOCAL:x}/0x8"
        )
        idle = await self._rd("ZEROER_PRE_ERR", self.zr_status.addr, 8)
        assert not idle & ZEROER_STATUS, "error destination: STATUS[32] set before the start"
        # zeroer_ctrl.rdl CTRL_STATUS: a write with SIZE non-zero starts a clear, and STATUS
        # reads 1 while the zeroer is active or has pending work.
        mon = _ZeroerMonitor()
        mon.start()
        try:
            await self._wr("ZEROER_START_ERR", self.zr_status.addr, 0, 8)
            polls, first = await self._zeroer_poll("ERR")
        finally:
            mon.stop()
        assert first & ZEROER_STATUS or mon.busy_seen, (
            "error destination: neither STATUS[32] nor the zeroer busy probe rose after the "
            "start write, so no clear started"
        )
        await self._rd("ZEROER_ERR_LATER_ACCESS", self.zr_status.addr, 8)
        self._chk(
            "CHK-ZEROER-COMPLETION-NOT-SUCCESS",
            f"error destination: DEST_ADDR=0x{dest:x} SIZE={size} read back; busy rose "
            f"(first STATUS[32]={1 if first & ZEROER_STATUS else 0} probe={mon.busy_seen}); "
            f"STATUS[32] unset within bound ({polls} polls of {ZEROER_POLL_BOUND})",
        )
        self._mark("ZEROER")

    # ---- side-effect registers -----------------------------------------------------------
    async def _side_effects(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        smc_bit = 1
        sm = self.iso_smc.addr

        def cool_idle(where: str) -> None:
            v = dut.tb_rst_cool_from_flr.value
            assert v.is_resolvable and int(v) == 1, (
                f"tb_rst_cool_from_flr is {v} {where}: a timed cool reset started"
            )

        # (S1) ISOLATE_REQ_SMC_REG strobe rule with a zero hold count.
        await self._wr("FLR_RESET_COUNT_ZERO", self.flr_reset_cnt.addr, 0, 4)
        idle = await self._rd("ISO_SMC_IDLE", sm, 4)
        assert idle & smc_bit == 0, f"ISOLATE_REQ_SMC_REG reads 0x{idle:x} before the FLR edge"
        dut.tb_cfg_flr_pf_active.value = 1
        last = 0
        for _ in range(FLR_POLL_BOUND):
            last = await self._rd("ISO_SMC_FLR", sm, 4)
            if last & smc_bit:
                break
            await RisingEdge(clk)
        else:
            raise AssertionError(f"ISOLATE_REQ_SMC_REG=0x{last:x}, bit 0 never read 1")
        dut.tb_cfg_flr_pf_active.value = 0
        self._bounded.append(("flr_latch", f"{FLR_POLL_BOUND} polls", f"read 0x{last:x}"))
        cool_idle("after the FLR edge")
        keeps = ((0x0, 0x01), (0x1, 0x02), (0x1, 0x04), (0x1, 0x08), (0x1, 0x00))
        for data, s in keeps:
            await self._wr(f"ISO_SMC_D{data}_S{s:02X}", sm, data, 4, s)
            got = await self._rd(f"ISO_SMC_D{data}_S{s:02X}_RB", sm, 4)
            assert got & smc_bit == 1, (
                f"ISOLATE_REQ_SMC_REG reads 0x{got:x} after a write of {data} with wstrb "
                f"0x{s:02x}: only a 1 on a strobed byte 0 clears it"
            )
        await self._wr("ISO_SMC_CLEAR", sm, 1, 4, 0x01)
        got = await self._rd("ISO_SMC_CLEAR_RB", sm, 4)
        assert got & smc_bit == 0, (
            f"ISOLATE_REQ_SMC_REG reads 0x{got:x} after the byte-0 write of 1"
        )
        cool_idle("after the clearing write")
        await self._wr(
            "FLR_RESET_COUNT_RESTORE",
            self.flr_reset_cnt.addr,
            self.saved[self.flr_reset_cnt.path],
            4,
        )
        self._chk(
            "CHK-ISOLATE-SMC-W1C-STROBE",
            "set by FLR edge; write 0 / byte1-3 / WSTRB 0 keep 1; byte0 write of 1 clears",
        )

        # (S3) RESET_CTRL start bit.
        rc = self.reset_ctrl.addr
        start = 0x80 | 0x0F
        mon = _Core3Monitor()
        mon.start()
        try:
            cur = await self._rd("RESET_CTRL_CUR", rc, 8)
            data = (cur & ~0xFF) | start
            resp = await self._wr("RESET_CTRL_B0_START", rc, data, 8, 0x01)
            for _ in range(PULSE_BOUND):
                if mon.falls >= 1 and mon.rises >= 1:
                    break
                await RisingEdge(clk)
            else:
                raise AssertionError(
                    f"no core 3 reset pulse within {PULSE_BOUND} clk_smc_i edges of the byte-0 "
                    f"start write (falls {mon.falls}, rises {mon.rises})"
                )
            self._bounded.append(
                ("core3_pulse", f"{PULSE_BOUND} edges", f"falls={mon.falls} rises={mon.rises}")
            )
            await ClockCycles(clk, PROBE_EDGES)
            assert (mon.falls, mon.rises) == (1, 1), (
                f"core 3 reset probe fell {mon.falls} times and rose {mon.rises} times within "
                f"{PROBE_EDGES} edges of the byte-0 start pulse: exactly one pulse is expected"
            )
            self._bounded.append(("core3_single", f"{PROBE_EDGES} edges", "falls=1 rises=1"))
            rb = await self._rd("RESET_CTRL_B0_RB", rc, 8)
            assert rb & 0xF0 == 0, f"RESET_CTRL reads 0x{rb:x}: start bits must read 0"
            assert rb & 0x100, f"RESET_CTRL reads 0x{rb:x}: the uncore bit must read 1"
            self._obs(
                "OBS-SIDEEFFECT-NARROW",
                f"reg=RESET_CTRL wstrb=0x01 bresp={RESP_NAME[resp]} readback={_hx(rb)} pulse=1",
            )
            for tag, s, lane_value in (
                ("B1", 0x02, 0x01),
                ("B3", 0x08, None),
                ("ZERO", 0x00, None),
            ):
                cur = await self._rd(f"RESET_CTRL_{tag}_CUR", rc, 8)
                if tag == "B1":
                    data = (cur & ~0xFF00) | (lane_value << 8)
                else:
                    data = cur
                # The core 3 start bit rides in the unstrobed byte 0, so a DUT that ignores the
                # byte-0 strobe pulses core 3 and fails the no-pulse assert below.
                data |= 0x80
                falls0, rises0 = mon.falls, mon.rises
                resp = await self._wr(f"RESET_CTRL_{tag}", rc, data, 8, s)
                await ClockCycles(clk, PROBE_EDGES)
                rb = await self._rd(f"RESET_CTRL_{tag}_RB", rc, 8)
                assert rb & 0xF0 == 0, f"RESET_CTRL reads 0x{rb:x} after {tag}: start bits 0"
                assert rb & 0x100, f"RESET_CTRL reads 0x{rb:x} after {tag}: uncore bit 1"
                pulse = 1 if (mon.falls > falls0 or mon.rises > rises0) else 0
                assert pulse == 0, (
                    f"core 3 reset probe moved (falls {falls0}->{mon.falls}, rises "
                    f"{rises0}->{mon.rises}) within {PROBE_EDGES} edges of the RESET_CTRL {tag} "
                    f"write with wstrb 0x{s:02x}: only a strobed byte 0 may start a pulse"
                )
                self._obs(
                    "OBS-SIDEEFFECT-NARROW",
                    f"reg=RESET_CTRL wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                    f"readback={_hx(rb)} pulse={pulse} bit8={(rb >> 8) & 1} bit24={(rb >> 24) & 1}",
                )
            falls0, rises0 = mon.falls, mon.rises
            final = await self._rd("RESET_CTRL_FINAL", rc, 8)
            await ClockCycles(clk, PROBE_EDGES)
            assert final & 0xF0 == 0, f"RESET_CTRL reads 0x{final:x}: start bits must read 0"
            assert (mon.falls, mon.rises) == (falls0, rises0), (
                f"a second core 3 pulse appeared within {PROBE_EDGES} edges of the RESET_CTRL read"
            )
            self._bounded.append(("core3_quiet", f"{PROBE_EDGES} edges", f"falls={mon.falls}"))
            assert (mon.falls, mon.rises) == (1, 1), (
                f"core 3 reset probe fell {mon.falls} times and rose {mon.rises} times over the "
                f"RESET_CTRL section: exactly one pulse is expected"
            )
            cocotb.log.info(
                "RESET_CTRL core 3 probe over the section: falls=%d rises=%d (want 1, 1)",
                mon.falls,
                mon.rises,
            )
        finally:
            mon.stop()
        self._chk(
            "CHK-RESET-CTRL-START-BIT",
            "byte-0 start write -> exactly one pulse in 128 edges; B1/B3/WSTRB-0 writes with the "
            "start bit in the unstrobed byte 0 and the final read -> no pulse in 128 edges; one "
            "fall and one rise over the section; start bits read 0; uncore bit 1",
        )

        # (S4) WDT_TIMEOUT_RESET.
        wt = self.wdt_to_reset
        for s in (0x01, 0x02, 0x00):
            resp = await self._wr(f"WDT_TIMEOUT_RESET_S{s:02X}", wt.addr, 0x1, 4, s)
            rb = await self._rd(f"WDT_TIMEOUT_RESET_S{s:02X}_RB", wt.addr, 4)
            self._obs(
                "OBS-SIDEEFFECT-NARROW",
                f"reg=WDT_TIMEOUT_RESET wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                f"readback={_hx(rb)} pulse=0",
            )
        await self._wr("WDT_TIMEOUT_RESET_RESTORE", wt.addr, self.saved[wt.path], 4)

        # (S5) SEMA[0].
        sema = self.sema0.addr
        start_val = await self._rd("SEMA0_START", sema, 8)
        assert start_val & 0xFFFF == 0, f"SEMA[0] reads 0x{start_val:x}, documented reset 0x0"
        resp = await self._wr("SEMA0_P5", sema, 0x0005, 8)
        v5 = await self._rd("SEMA0_P5_RB", sema, 8)
        self._obs(
            "OBS-SIDEEFFECT-NARROW",
            f"reg=SEMA[0] wstrb=0xff bresp={RESP_NAME[resp]} readback={_hx(v5)} pulse=0",
        )
        resp = await self._wr("SEMA0_M2", sema, 0xFFFE, 8)
        v3 = await self._rd("SEMA0_M2_RB", sema, 8)
        self._obs(
            "OBS-SIDEEFFECT-NARROW",
            f"reg=SEMA[0] wstrb=0xff bresp={RESP_NAME[resp]} readback={_hx(v3)} pulse=0",
        )
        assert v5 & 0xFFFF == 5 and v3 & 0xFFFF == 3, (
            f"SEMA[0] reads 0x{v5:x} after +5 and 0x{v3:x} after -2, expected 5 then 3"
        )
        self._chk("CHK-SEMA-FULL-WRITE", "0 -> +5 reads 5 -> -2 reads 3")
        for label, data, s in (
            ("B0_03", 0x0003, 0x01),
            ("B1_0100", 0x0100, 0x02),
            ("ZERO_07", 0x0007, 0x00),
        ):
            resp = await self._wr(f"SEMA0_{label}", sema, data, 8, s)
            rb = await self._rd(f"SEMA0_{label}_RB", sema, 8)
            self._obs(
                "OBS-SIDEEFFECT-NARROW",
                f"reg=SEMA[0] wstrb=0x{s:02x} bresp={RESP_NAME[resp]} readback={_hx(rb)} pulse=0",
            )
        cur = (await self._rd("SEMA0_BEFORE_RESTORE", sema, 8)) & 0xFFFF
        await self._wr("SEMA0_RESTORE", sema, (0x10000 - cur) & 0xFFFF, 8)
        end = await self._rd("SEMA0_END", sema, 8)
        cocotb.log.info("S10 SEMA[0] restored from 0x%x to 0x%x", cur, end & 0xFFFF)
        self._mark("SIDE_EFFECT")

    # ---- lock registers ------------------------------------------------------------------
    async def _locks(self) -> None:
        # S11.
        async def lock_pair(lock: RdlReg, guarded: RdlReg, name: str) -> None:
            before = await self._rd(f"{name}_GUARDED_BEFORE", guarded.addr, 4)
            assert before & 1 == 0, f"{guarded.path} reads 0x{before:x} before the lock"
            resp = await self._wr(f"{name}_SET", lock.addr, 0x1, 4, 0x01)
            lk = await self._rd(f"{name}_SET_RB", lock.addr, 4)
            assert lk & 1 == 1, f"{lock.path} reads 0x{lk:x} after the byte-0 write of 1"
            await self._wr(f"{guarded.symbol}_BIT0", guarded.addr, before | 1, 4)
            after = await self._rd(f"{guarded.symbol}_BIT0_RB", guarded.addr, 4)
            assert after & 1 == 0, (
                f"{guarded.path} reads 0x{after:x}: bit 0 changed although {lock.path} bit 0 is set"
            )
            self._obs(
                "OBS-SIDEEFFECT-NARROW",
                f"reg={name} wstrb=0x01 bresp={RESP_NAME[resp]} readback={_hx(lk)} pulse=0",
            )

        await lock_pair(self.ss_lock, self.ss_cfg, "SS_CONFIG_LOCK")
        await lock_pair(self.cold_lock, self.cold_n, "SS_COLD_RESET_LOCK")
        self._chk(
            "CHK-LOCK-BIT0-MASKS-WRITES",
            "SS_CONFIG[0] and SS_COLD_RESET_N[0] stay 0 after their lock bit 0 is set",
        )
        cur_cfg = await self._rd("SS_CONFIG_BEFORE_BIT8", self.ss_cfg.addr, 4)
        for s in (0x01, 0x00):
            resp = await self._wr(f"SS_CONFIG_LOCK_0100_S{s:02X}", self.ss_lock.addr, 0x100, 4, s)
            rb = await self._rd(f"SS_CONFIG_LOCK_0100_S{s:02X}_RB", self.ss_lock.addr, 4)
            await self._wr(f"SS_CONFIG_BIT8_S{s:02X}", self.ss_cfg.addr, cur_cfg | 0x100, 4)
            cfg = await self._rd(f"SS_CONFIG_BIT8_S{s:02X}_RB", self.ss_cfg.addr, 4)
            self._obs(
                "OBS-SIDEEFFECT-NARROW",
                f"reg=SS_CONFIG_LOCK wstrb=0x{s:02x} bresp={RESP_NAME[resp]} "
                f"readback={_hx(rb)} pulse=0 ss_config_after_bit8_write={_hx(cfg)}",
            )
        self._chk_obs("CHK-OBS-SIDEEFFECT-NARROW", "OBS-SIDEEFFECT-NARROW")
        self._mark("LOCKS")

    def _finish(self) -> None:
        # S12.
        bound = self.cfg.axi_timeout_ns
        waits = [
            ("fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last),
            (
                "sep_in_axi_access",
                f"{bound}ns per access",
                f"{self.accesses} done, last {self._last}",
            ),
            *self._bounded,
        ]
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{self.accesses + len(self._bounded) + 1} bounded waits, "
            + " ".join(f"{n}=bound {b} last={s}" for n, b, s in waits)
            + "; expiry raises AssertionError, 0 expired",
        )
        assert tuple(t for t, _c, _s in self._stamps) == TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        self._chk(
            "CHK-NONVAC",
            " < ".join(TERMS)
            + "; terms "
            + ", ".join(f"{t}(writes={c}/{PLANNED_WRITES[t]})@{s}ns" for t, c, s in self._stamps)
            + "; PLAIN excludes the not-driven REFERENCE_COUNTER WSTRB 0x01"
            + f"; checker lines {','.join(self.chk_seen)}; SEP_IN accesses {self.accesses}",
        )
