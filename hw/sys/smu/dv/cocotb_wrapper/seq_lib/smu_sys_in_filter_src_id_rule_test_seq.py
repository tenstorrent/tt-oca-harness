# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN entry 0: source-ID match, group-ID no-effect and single-term flips, from the SMN port.

``hw/ip/axi_filter/doc/index.adoc`` "Match, Then Permit": an entry matches only when
``entry_enabled`` is 1, the address is in range, ``prot[1]`` equals ``allow_ns``, the source ID
equals ``src_id`` or ``src_id`` is 0, and ``allow_burst`` is 1 or ``AxLEN`` is 0; the matching
entry's ``read_allowed`` (AR) or ``write_allowed`` (AW) then decides. "Blocked Transactions": a
blocked transaction answers DECERR. "Address Range Granule" and the chapter's instance table: group
ID matching is disabled at build time, so ``group_id`` has no effect.

The leaf drives the source ID in AxUSER[3:0] of the external master and, in S6, a transaction
group_id in AxUSER[7:4]; every other AxUSER bit is zero. No document states which AxUSER bits
carry either value: the S2/S3 pair (5 admitted, 6 and 0 refused) is the witness that the entry
reads the source-ID lane, and the group_id lane rests on the leaf's choice alone.

S1: TAP reset, JTAG2AXI gate open, SMC aperture routed, entry 0 programmed over one page of
    SCRATCH_COLD with src_id 5 and read back.
S2: admitted control: AxUSER 5 writes and reads back two registers (OKAY).
S3: AxUSER 6 and 0 are refused (DECERR) on AR and AW at both registers; the refused writes leave
    the registers at the admitted values.
S4: on one entry the AW with AxUSER 5 is admitted while the AR with AxUSER 6 is refused, and the
    mirror pair.
S5: AxUSER 5 outside the entry's page is refused on AR and AW.
S6: entry group_id 1, 15 and 8 each admit a transaction whose group_id lane carries a different
    non-zero value; group_id 8 with the entry disabled and with the range moved off the page
    refuses.
S7: src_id 0 admits every AxUSER value 0..15 on AR and AW.
S8: entry_enabled, range, allow_ns, src_id and allow_burst each flipped alone refuse AR and AW; the
    restored term admits both.
S9: read_allowed and write_allowed act on their own channel only.
S10: allow_ns against prot[1] on AR and AW; prot[2] and prot[0] change no outcome.
S11: every bounded wait reports its bound and last state.
"""

from __future__ import annotations

import math

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_filter_helpers import (
    FILTER_BURST_GRANULE_BITS,
    SMC_APERTURE_LOCAL_BASE,
    WDT_CTRL_ADDR,
    page_align_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

# hw/ip/axi_filter/regs/gen/c/filter_ctrl.h: FILTER_CONFIG field masks.
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
_F_SRC_ID = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm")
_F_GROUP_ID = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm")
_F_DATA_BUS_WIDTH = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
# Every FILTER_CONFIG field the leaf programs; LOCKED is left at 0 and not compared.
_CFG_CMP_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_ALLOW_NS
    | _F_ALLOW_BURST
    | _F_SRC_ID
    | _F_GROUP_ID
    | _F_DATA_BUS_WIDTH
)

# hw/ip/axi_filter/regs/gen/c/filter_ctrl.h SRC_ID_bw / GROUP_ID_bw: each field is 4 bits wide.
SRC_ID_VALUES = (_F_SRC_ID // (_F_SRC_ID & -_F_SRC_ID)) + 1
GROUP_ID_MAX = _F_GROUP_ID // (_F_GROUP_ID & -_F_GROUP_ID)
# hw/ip/axi_filter/regs/filter_ctrl.rdl src_id: 0 is the wildcard; the leaf's entry matches 5.
ENTRY_SRC_ID = 5
# A source ID the entry does not match, and the wildcard value (filter_ctrl.rdl src_id).
OTHER_SRC_ID = 6
WILDCARD_SRC_ID = 0
# hw/ip/axi_filter/doc/index.adoc "Match, Then Permit": group ID matching is disabled at build time.
# filter_ctrl.rdl group_id: a transaction group_id of 0 matches regardless of the field, so each
# entry value is probed with a non-zero transaction group_id that differs from it, which group
# matching, were it enabled, would refuse. The lane AxUSER[7:4] is the leaf's choice; no document
# states which AxUSER bits carry the group_id.
GROUP_ID_USER_SHIFT = 4
GROUP_LEGS = ((1, 4), (GROUP_ID_MAX, 2), (8, 11))
GROUP_ID_REFUSED_LEGS = 8
GROUP_ID_REFUSED_TX = 11

# hw/ip/axi_filter/doc/index.adoc "Match, Then Permit": prot[1] equals allow_ns.
PROT_SECURE = 0
PROT_BITS = tuple(range(8))
PROT1_BIT = 1

# hw/ip/axi_filter/doc/index.adoc "Match, Then Permit": a burst has AxLEN above 0 and matches an
# entry only with allow_burst 1. Four 4-byte beats make a 16-byte INCR burst, AxLEN 3.
BURST_BEATS = 4
BURST_BEAT_SIZE = 2
WORD_BYTES = 4

# hw/sys/smc/regs/blocks/scratch/scratch.rdl: SCRATCH registers are 32-bit, reset 0x0, stride 4.
PROBE_ADDR = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
PROBE_ADDR_2 = PROBE_ADDR + WORD_BYTES
PROBE_RESET_VALUE = 0x0
# Written values: non-zero, distinct from the reset value and from each other.
PATTERN_A = 0xA5C3_0F1E
PATTERN_A2 = 0x3C69_96D2
PATTERN_B = 0x5E7B_81A4
OUTSIDE_ADDR = WDT_CTRL_ADDR

# hw/ip/axi_filter/doc/index.adoc "Blocked Transactions": a blocked transaction answers DECERR.
OKAY = resp_name(RESP_OKAY)
DECERR = resp_name(RESP_DECERR)

J2A_POLL_LIMIT = 128
# Entry reprogramming (3 registers) plus readback, the aperture write and read, and the flips.
J2A_ACCESS_COUNT = 33
J2A_ACCESS_BUDGET = 34
APERTURE_J2A_ACCESSES = 2
IDLE_CYCLES = 4
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
ACCESS_STEPS = STEPS[:-1]
FLIP_NAMES = ("entry_enabled", "range", "allow_ns", "src_id", "allow_burst")
REFUSE_USERS = (OTHER_SRC_ID, WILDCARD_SRC_ID)


def _require_probe_map() -> None:
    page_lo, page_hi = page_align_window(PROBE_ADDR, PROBE_ADDR_2)
    region = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
    facts = (
        (page_lo <= PROBE_ADDR_2 <= page_hi, "the probe registers are not in one 4 KB page"),
        (not page_lo <= OUTSIDE_ADDR <= page_hi, "the outside register is in the probe page"),
        (
            SMC_APERTURE_LOCAL_BASE <= OUTSIDE_ADDR < SMC_APERTURE_LOCAL_BASE + region,
            "the outside register is not in the SMC aperture",
        ),
        (PROBE_ADDR % (BURST_BEATS * WORD_BYTES) == 0, "the probe is not burst aligned"),
        (SRC_ID_VALUES == 16 and GROUP_ID_MAX == 15, "unexpected source or group ID width"),
        (
            all(0 < tx <= GROUP_ID_MAX and tx != entry for entry, tx in GROUP_LEGS)
            and 0 < GROUP_ID_REFUSED_TX <= GROUP_ID_MAX
            and GROUP_ID_REFUSED_TX != GROUP_ID_REFUSED_LEGS,
            "a transaction group_id is zero or equals its entry field",
        ),
        (
            len({PATTERN_A, PATTERN_A2, PATTERN_B, PROBE_RESET_VALUE}) == 4
            and all(
                (PATTERN_A ^ tag) not in (PATTERN_B, PROBE_RESET_VALUE) for tag in range(0x100)
            ),
            "written values collide with each other or the reset value",
        ),
    )
    bad = [msg for ok, msg in facts if not ok]
    if bad:
        raise RuntimeError("src_id rule probe map: " + "; ".join(bad))


_require_probe_map()


def _config(
    *,
    src_id: int = ENTRY_SRC_ID,
    group_id: int = 0,
    allow_ns: int = 0,
    allow_burst: int = 1,
    read: int = 1,
    write: int = 1,
    enabled: int = 1,
) -> int:
    word = _F_BUS_WIDTH_64
    for flag, mask in (
        (read, _F_READ),
        (write, _F_WRITE),
        (enabled, _F_ENTRY),
        (allow_ns, _F_ALLOW_NS),
        (allow_burst, _F_ALLOW_BURST),
    ):
        if flag:
            word |= mask
    return (
        word
        | filter_ctrl_field_encode("SRC_ID", src_id)
        | filter_ctrl_field_encode("GROUP_ID", group_id)
    )


class smu_sys_in_filter_src_id_rule_test_seq:
    """SYS_IN entry 0 source-ID, group-ID and term-conjunction outcomes at the SMN port."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = cocotb.top.clk_smu_i
        self.jtag = None
        self.master = None
        self.step = ""
        self.step_ts: dict[str, float] = {}
        self.step_access = {step: {"j2a": 0, "ext": 0} for step in STEPS}
        self.sites: dict[str, dict] = {}
        self.entry = dict(
            src_id=ENTRY_SRC_ID,
            group_id=0,
            allow_ns=0,
            allow_burst=1,
            read=1,
            write=1,
            enabled=1,
        )
        self.page_lo, self.page_hi = page_align_window(PROBE_ADDR, PROBE_ADDR_2)
        self.off_lo = self.page_hi + 1
        self.off_hi = self.off_lo + (1 << FILTER_BURST_GRANULE_BITS) - 1
        self.bound_clk = math.ceil(AXI_TIMEOUT_NS / self.cfg.smu_clk_period_ns)
        self.admit_ok = False
        self.refusals_ok = False
        self.ctrl: dict[str, tuple] = {}
        self.value = PROBE_RESET_VALUE

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

    # ------------------------------------------------------------------
    # JTAG2AXI: entry programming.
    # ------------------------------------------------------------------

    async def _j2a(self, tag: str, write: bool, addr: int, value: int = 0) -> int:
        t0 = get_sim_time("ns")
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag, addr, value, poll_limit=J2A_POLL_LIMIT, require_complete=True
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag, addr, poll_limit=J2A_POLL_LIMIT, require_complete=True
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
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {tag} status={status} want {J2A_STATUS_SUCCESS}")
        return int(raw)

    async def _set_config(self, tag: str, **changes: int) -> int:
        self.entry.update(changes)
        word = _config(**self.entry)
        await self._j2a(tag, True, INBOUND0_FILTER_CONFIG, word)
        return word

    async def _set_range(self, tag: str, lo: int, hi: int) -> None:
        await self._j2a(f"{tag}_start", True, INBOUND0_START, lo)
        await self._j2a(f"{tag}_end", True, INBOUND0_END, hi)

    # ------------------------------------------------------------------
    # External SMN master: AxUSER carries the source ID.
    # ------------------------------------------------------------------

    async def _ext(
        self,
        write: bool,
        addr: int,
        *,
        user: int,
        prot: int = PROT_SECURE,
        value: int = 0,
        beats: int = 1,
    ) -> tuple[str, int]:
        """One AR or AW with ``user`` as AxUSER; returns (response name, first data word)."""
        name = f"ext_{'wr' if write else 'rd'}_{self.step}"
        t0 = get_sim_time("ns")
        kwargs = {"user": user, "prot": prot, "check_response": False}
        kwargs.update(timeout_ns=AXI_TIMEOUT_NS, allow_timeout=True)
        if beats > 1:
            kwargs["size"] = BURST_BEAT_SIZE
        nbytes = WORD_BYTES * beats
        if write:
            payload = int(value).to_bytes(WORD_BYTES, "little") * beats
            result = await self.master.write_bytes_result(addr, payload, **kwargs)
        else:
            result = await self.master.read_bytes_result(addr, nbytes, **kwargs)
        if result.timed_out:
            self._site(
                name, self.bound_clk, self.bound_clk + 1, f"EXPIRED addr=0x{addr:08x}", "clk"
            )
            raise AssertionError(
                f"TIMEOUT {name} addr=0x{addr:08x} user={user} bound={AXI_TIMEOUT_NS}ns"
            )
        used = math.ceil((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        resp = resp_name(result.resp)
        data = 0 if write else int(result.data) & 0xFFFF_FFFF
        self._site(name, self.bound_clk, used, f"resp={resp} addr=0x{addr:08x} user={user}", "clk")
        self.step_access[self.step]["ext"] += 1
        await ClockCycles(self.clk, IDLE_CYCLES)
        return resp, data

    async def _wr(self, addr: int, value: int, **kw) -> str:
        resp, _ = await self._ext(True, addr, value=value, **kw)
        return resp

    async def _rd(self, addr: int, **kw) -> tuple[str, int]:
        return await self._ext(False, addr, **kw)

    # ------------------------------------------------------------------
    # Steps.
    # ------------------------------------------------------------------

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
        gate_pin = dut.tb_smc_jtag2axi_security_disable
        if not gate_pin.value.is_resolvable or (int(gate_pin.value) & 1) != 0:
            raise AssertionError(f"SMC J2A gated after TCK sync: {gate_pin.value}")
        await program_smc_aperture_local_alias(self.jtag, scoreboard=sb)
        self.step_access[self.step]["j2a"] += APERTURE_J2A_ACCESSES
        self._site("j2a_aperture_alias", J2A_POLL_LIMIT, 0, "write and read completed", "polls")
        self.master = await make_smu_axi_master(dut, self.clk, smc_primary_reset(dut))
        await self._set_range("entry", self.page_lo, self.page_hi)
        word = _config(**self.entry)
        await self._j2a("entry_config", True, INBOUND0_FILTER_CONFIG, word)
        readback = await self._j2a("entry_config_rb", False, INBOUND0_FILTER_CONFIG)
        self._log(
            f"ENTRY0 page=[0x{self.page_lo:08x},0x{self.page_hi:08x}] config=0x{word:08x} "
            f"readback=0x{readback & 0xFFFF_FFFF:08x} mask=0x{_CFG_CMP_MASK:08x}"
        )
        sb.expect_eq(
            "SYS_IN entry 0 FILTER_CONFIG readback",
            readback & _CFG_CMP_MASK,
            word & _CFG_CMP_MASK,
        )

    async def _s2(self, sb) -> None:
        for tag, addr, value in (("w0", PROBE_ADDR, PATTERN_A), ("w1", PROBE_ADDR_2, PATTERN_A2)):
            aw = await self._wr(addr, value, user=ENTRY_SRC_ID)
            ar, data = await self._rd(addr, user=ENTRY_SRC_ID)
            self.ctrl[tag] = (aw, ar, data)
        want = {"w0": (OKAY, OKAY, PATTERN_A), "w1": (OKAY, OKAY, PATTERN_A2)}
        self._chk(
            sb,
            "CHK-SRCID-MATCH-ADMIT",
            "AxUSER 5 write then read at two registers",
            self.ctrl,
            want,
            "AW then AR with AxUSER 5 answer OKAY and the read returns the written pattern",
        )
        self.admit_ok = self.ctrl == want

    async def _s3(self, sb) -> None:
        refused = {}
        for user in REFUSE_USERS:
            for idx, addr in enumerate((PROBE_ADDR, PROBE_ADDR_2)):
                refused[f"AW user={user} reg={idx}"] = await self._wr(addr, PATTERN_B, user=user)
                refused[f"AR user={user} reg={idx}"] = (await self._rd(addr, user=user))[0]
        want_refused = {key: DECERR for key in refused}
        self._chk(
            sb,
            "CHK-SRCID-MISMATCH-REFUSE",
            "AxUSER 6 and 0 refused, control admitted",
            (refused, self.admit_ok),
            (want_refused, True),
            "AxUSER 6 and 0 on AR and AW at two registers (eight cells) answer DECERR after the "
            "AxUSER 5 control answered OKAY",
        )
        self.refusals_ok = refused == want_refused
        after = []
        for addr in (PROBE_ADDR, PROBE_ADDR_2):
            after.append(await self._rd(addr, user=ENTRY_SRC_ID))
        self._chk(
            sb,
            "CHK-SRCID-REFUSED-NO-EFFECT",
            "refused writes leave the admitted values",
            (self.ctrl["w0"][2:], self.ctrl["w1"][2:], after),
            ((PATTERN_A,), (PATTERN_A2,), [(OKAY, PATTERN_A), (OKAY, PATTERN_A2)]),
            f"the AxUSER 5 reads after the refused pattern 0x{PATTERN_B:08x} writes return the "
            "admitted patterns, which an admitted write put there first",
        )
        self.value = PATTERN_A

    async def _s4(self, sb) -> None:
        cells = {}
        value = PATTERN_A ^ 0x01
        cells["AW user=5"] = await self._wr(PROBE_ADDR, value, user=ENTRY_SRC_ID)
        cells["AR user=6"] = (await self._rd(PROBE_ADDR, user=OTHER_SRC_ID))[0]
        cells["AR user=5"] = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID)
        cells["AW user=6"] = await self._wr(PROBE_ADDR, PATTERN_B, user=OTHER_SRC_ID)
        cells["AR user=5 after"] = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID)
        want = {
            "AW user=5": OKAY,
            "AR user=6": DECERR,
            "AR user=5": (OKAY, value),
            "AW user=6": DECERR,
            "AR user=5 after": (OKAY, value),
        }
        self._chk(
            sb,
            "CHK-SRCID-CHANNEL-SPLIT",
            "per-channel source ID on one entry",
            cells,
            want,
            "AW with AxUSER 5 answers OKAY while AR with AxUSER 6 answers DECERR on one entry, and "
            "the mirror pair does the same",
        )
        self.value = value

    async def _s5(self, sb) -> None:
        cells = {
            "AR outside": (await self._rd(OUTSIDE_ADDR, user=ENTRY_SRC_ID))[0],
            "AW outside": await self._wr(OUTSIDE_ADDR, PATTERN_B, user=ENTRY_SRC_ID),
        }
        self._chk(
            sb,
            "CHK-SRCID-BLOCK-OUTSIDE",
            "register outside the entry range refused, in-range control admitted",
            (cells, self.admit_ok),
            ({"AR outside": DECERR, "AW outside": DECERR}, True),
            f"AR and AW with AxUSER 5 at 0x{OUTSIDE_ADDR:08x}, outside page "
            f"[0x{self.page_lo:08x},0x{self.page_hi:08x}], answer DECERR; the in-range AR and AW "
            "answered OKAY",
        )

    async def _group_probe(self, tag: int, tx_group: int) -> tuple:
        value = PATTERN_A ^ tag
        user = ENTRY_SRC_ID | (tx_group << GROUP_ID_USER_SHIFT)
        aw = await self._wr(PROBE_ADDR, value, user=user)
        ar, data = await self._rd(PROBE_ADDR, user=user)
        self.value = value
        return aw, ar, data == value

    async def _refused_probe(self, tx_group: int) -> tuple:
        user = ENTRY_SRC_ID | (tx_group << GROUP_ID_USER_SHIFT)
        aw = await self._wr(PROBE_ADDR, PATTERN_B, user=user)
        ar, _ = await self._rd(PROBE_ADDR, user=user)
        return aw, ar

    async def _s6(self, sb) -> None:
        cells = {}
        want = {}
        for tag, (group, tx_group) in enumerate(GROUP_LEGS, start=0x10):
            await self._set_config(f"group_{group}", group_id=group)
            key = f"group_id={group} tx_group_id={tx_group}"
            cells[key] = await self._group_probe(tag, tx_group)
            want[key] = (OKAY, OKAY, True)
        await self._set_config("group_disabled", group_id=GROUP_ID_REFUSED_LEGS, enabled=0)
        cells["group_id=8 entry_enabled=0"] = await self._refused_probe(GROUP_ID_REFUSED_TX)
        want["group_id=8 entry_enabled=0"] = (DECERR, DECERR)
        await self._set_config("group_enabled", enabled=1)
        await self._set_range("group_moved", self.off_lo, self.off_hi)
        cells["group_id=8 range moved"] = await self._refused_probe(GROUP_ID_REFUSED_TX)
        want["group_id=8 range moved"] = (DECERR, DECERR)
        legs = ", ".join(f"{g}/{t}" for g, t in GROUP_LEGS)
        self._chk(
            sb,
            "CHK-SRCID-GROUPID-NOEFFECT",
            "a transaction group_id that differs from the entry field is still admitted",
            cells,
            want,
            f"entry group_id against transaction group_id {legs} in AxUSER[7:4] with AxUSER[3:0] "
            "5 answer OKAY on AR and AW and read back the written pattern; group_id 8 with the "
            f"entry disabled and with the range moved off the page refuse transaction group_id "
            f"{GROUP_ID_REFUSED_TX} on AR and AW",
        )

    async def _s7(self, sb) -> None:
        await self._set_range("restore_page", self.page_lo, self.page_hi)
        await self._set_config("wildcard", group_id=0, src_id=WILDCARD_SRC_ID)
        cells = {}
        for user in range(SRC_ID_VALUES):
            value = PATTERN_A ^ (0x20 + user)
            aw = await self._wr(PROBE_ADDR, value, user=user)
            ar, data = await self._rd(PROBE_ADDR, user=user)
            cells[f"user={user}"] = (aw, ar, data == value)
        self.value = PATTERN_A ^ (0x20 + SRC_ID_VALUES - 1)
        want = {f"user={u}": (OKAY, OKAY, True) for u in range(SRC_ID_VALUES)}
        self._chk(
            sb,
            "CHK-SRCID-WILDCARD",
            "src_id 0 admits every AxUSER value",
            (cells, self.refusals_ok),
            (want, True),
            "src_id 0 answers OKAY on AR and AW for AxUSER 0..15, after AxUSER 6 and 0 answered "
            "DECERR under src_id 5",
        )
        await self._set_config("src_id_restore", src_id=ENTRY_SRC_ID)

    async def _flip(self, name: str, flip, restore, *, beats: int = 1, tag: int) -> dict:
        await flip()
        ar_flip = (await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID, beats=beats))[0]
        aw_flip = await self._wr(PROBE_ADDR, PATTERN_B, user=ENTRY_SRC_ID, beats=beats)
        await restore()
        ar_back, data_back = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID, beats=beats)
        value = PATTERN_A ^ tag
        aw_back = await self._wr(PROBE_ADDR, value, user=ENTRY_SRC_ID, beats=beats)
        ar_new, data_new = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID, beats=beats)
        prior = self.value
        self.value = value
        cell = {
            "flip": (ar_flip, aw_flip),
            "restore": (ar_back, aw_back, ar_new),
            "kept": data_back == prior,
            "written": data_new == value,
        }
        self._log(f"CHK-SRCID-CONJ-FLIP: flip={name} {cell}")
        return cell

    async def _s8(self, sb) -> None:
        async def cfg(**kw):
            await self._set_config(f"flip_{next(iter(kw))}", **kw)

        flips = {}
        steps = (
            ("entry_enabled", lambda: cfg(enabled=0), lambda: cfg(enabled=1), 1),
            (
                "range",
                lambda: self._set_range("flip_range", self.off_lo, self.off_hi),
                lambda: self._set_range("restore_range", self.page_lo, self.page_hi),
                1,
            ),
            ("allow_ns", lambda: cfg(allow_ns=1), lambda: cfg(allow_ns=0), 1),
            ("src_id", lambda: cfg(src_id=OTHER_SRC_ID), lambda: cfg(src_id=ENTRY_SRC_ID), 1),
            (
                "allow_burst",
                lambda: cfg(allow_burst=0),
                lambda: cfg(allow_burst=1),
                BURST_BEATS,
            ),
        )
        for tag, (name, flip, restore, beats) in enumerate(steps, start=0x30):
            flips[name] = await self._flip(name, flip, restore, beats=beats, tag=tag)
        cell_want = {
            "flip": (DECERR, DECERR),
            "restore": (OKAY, OKAY, OKAY),
            "kept": True,
            "written": True,
        }
        self._chk(
            sb,
            "CHK-SRCID-CONJ-FLIP",
            "single-term flips refuse and restores admit",
            flips,
            {name: cell_want for name in FLIP_NAMES},
            "entry_enabled, range, allow_ns against prot[1] 0, src_id 6 against AxUSER 5 and "
            "allow_burst 0 against AxLEN 3 each answer DECERR on AR and AW when flipped alone and "
            "OKAY on both once restored (five flips, ten refusals, ten restores)",
        )

    async def _s9(self, sb) -> None:
        cells = {}
        await self._set_config("read_off", read=0, write=1)
        cells["read_allowed=0 AR"] = (await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID))[0]
        value = PATTERN_A ^ 0x40
        cells["read_allowed=0 AW"] = await self._wr(PROBE_ADDR, value, user=ENTRY_SRC_ID)
        await self._set_config("write_off", read=1, write=0)
        cells["write_allowed=0 AW"] = await self._wr(PROBE_ADDR, PATTERN_B, user=ENTRY_SRC_ID)
        cells["write_allowed=0 AR"] = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID)
        want = {
            "read_allowed=0 AR": DECERR,
            "read_allowed=0 AW": OKAY,
            "write_allowed=0 AW": DECERR,
            "write_allowed=0 AR": (OKAY, value),
        }
        self._chk(
            sb,
            "CHK-SRCID-PERM-CHANNEL",
            "permission bits act on their own channel",
            cells,
            want,
            "read_allowed 0 refuses AR and admits AW; write_allowed 0 refuses AW, the register "
            "keeps its value, and admits AR",
        )
        self.value = value

    async def _s10(self, sb) -> None:
        await self._set_config("perm_restore", read=1, write=1)
        cells = {}
        for allow_ns in (0, 1):
            if allow_ns:
                await self._set_config("allow_ns_on", allow_ns=1)
            for prot in PROT_BITS:
                value = PATTERN_A ^ (0x50 + 8 * allow_ns + prot)
                aw = await self._wr(PROBE_ADDR, value, user=ENTRY_SRC_ID, prot=prot)
                ar, data = await self._rd(PROBE_ADDR, user=ENTRY_SRC_ID, prot=prot)
                admitted = ((prot >> PROT1_BIT) & 1) == allow_ns
                cells[f"allow_ns={allow_ns} prot={prot}"] = (
                    aw,
                    ar,
                    (data == value) if ar == OKAY else None,
                    admitted,
                )
        want = {}
        for allow_ns in (0, 1):
            for prot in PROT_BITS:
                admitted = ((prot >> PROT1_BIT) & 1) == allow_ns
                want[f"allow_ns={allow_ns} prot={prot}"] = (
                    (OKAY, OKAY, True, True) if admitted else (DECERR, DECERR, None, False)
                )
        self._chk(
            sb,
            "CHK-SRCID-ALLOWNS-MATRIX",
            "allow_ns against prot[1], prot[2] and prot[0] free",
            cells,
            want,
            "allow_ns 0 admits prot[1] 0 and refuses prot[1] 1, allow_ns 1 admits prot[1] 1 and "
            "refuses prot[1] 0, on AR and AW, for every prot[2] and prot[0] value",
        )

    def _s11(self, sb) -> None:
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
            f"j2a_poll_limit={J2A_POLL_LIMIT}; j2a_accesses against the budget {J2A_ACCESS_BUDGET}",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        plan = (
            ("S1", "SETUP: TAP, aperture, entry 0 over one page with src_id 5, readback", self._s1),
            ("S2", "admitted control: AxUSER 5 write and read", self._s2),
            ("S3", "AxUSER 6 and 0 refused, refused writes without effect", self._s3),
            ("S4", "per-channel source ID", self._s4),
            ("S5", "register outside the entry range", self._s5),
            ("S6", "group_id 1, 15, 8 and the refused group_id 8 legs", self._s6),
            ("S7", "src_id 0 wildcard over AxUSER 0..15", self._s7),
            ("S8", "single-term flips and restores", self._s8),
            ("S9", "read_allowed and write_allowed per channel", self._s9),
            ("S10", "allow_ns against prot[1]", self._s10),
        )
        for step, text, body in plan:
            await self._mark(step, text)
            await body(sb)
        await self._mark("S11", "TIMEOUT: bounded waits and last state")
        self._s11(sb)
        await ClockCycles(self.clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        counts = " ".join(
            f"{s}:j2a={self.step_access[s]['j2a']},ext={self.step_access[s]['ext']}" for s in STEPS
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
            "step stamps strictly increase to the pass point and every step S1..S10 counted at "
            "least one access",
        )
