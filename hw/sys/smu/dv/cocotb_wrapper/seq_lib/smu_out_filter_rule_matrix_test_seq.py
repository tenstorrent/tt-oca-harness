# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC outbound filter entries 0 and 1 against the two egress masters a bench can drive.

``hw/ip/axi_filter/doc/index.adoc`` "Match, Then Permit": an entry matches when it is enabled, the
address is in range after granule widening, ``prot[1]`` equals ``allow_ns``, the source ID equals
``src_id`` or ``src_id`` is 0, and ``allow_burst`` is 1 or the access is one beat; the lowest
matching entry's ``read_allowed`` (AR) or ``write_allowed`` (AW) then decides. "Blocked
Transactions": a blocked transaction answers DECERR. "Address Range Granule": ``allow_burst`` 1
makes the granule 4 KB and widens START_ADDR down and END_ADDR up to it.
``hw/sys/smc/doc/fabric.adoc`` "Outbound Filtering": an unmatched request passes.
``hw/sys/smc/doc/dma.adoc``: the iDMA's accesses pass through the SMC fabric filtering.

The JTAG2AXI bridge issues single-beat accesses and programs the iDMA; a passive tap of the
outbound boundary interface counts the AW, W, B, AR and R handshakes and the bench responder holds
the bytes. A refused bridge access reports DECERR through the bridge status; a refused iDMA copy
leaves the destination bytes and the AW and W counters unchanged.

S1: TAP reset, JTAG2AXI gate open, responder patterns PS at the source and D0 at the destination.
S2: every outbound entry at reset: an iDMA copy completes and replaces D0 with PS.
S3: entries 0 (allow_ns 0) and 1 (allow_ns 1) as deny entries over R, one enabled at a time; exactly
    one refuses the bridge write; the refusing allow_ns value is measured and logged only.
S4: the refusing entry denies the write to R and passes the write outside R; with read_allowed 1
    the read of R passes and with read_allowed 0 it is refused.
S5: the iDMA copy over the deny entry leaves D1 at the destination and the AW and W counters still.
S6: START and END inside one 4 KB granule refuse its first and last byte and pass the bytes below
    and above; END raised by one granule refuses the address equal to END.
S7: a narrow deny at entry 0 inside a broad permit at entry 1 refuses the narrow write; a narrow
    permit at entry 0 inside a broad deny at entry 1 passes it.
S8: entry 0 as the narrow deny with src_id 1 to 15 in turn; the refusing values are logged.
S9: every bounded wait reports its bound, the cycles or polls used and its last state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    OUTBOUND_FILTER_CONFIG_SYM,
    OUTBOUND_FILTER_END_SYM,
    OUTBOUND_FILTER_START_SYM,
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_indexed_addr,
)
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DONE_0,
    DMA_DST_LO,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_POLL_CYCLES,
    DMA_REPS_LO,
    DMA_SRC_LO,
    DMA_STATUS_0,
)
from seq_lib.smu_filter_helpers import FILTER_BURST_GRANULE_BITS
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

# hw/ip/axi_filter/regs/gen/c/filter_ctrl.h: FILTER_CONFIG field masks.
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")

# hw/ip/axi_filter/doc/index.adoc "Address Range Granule": allow_burst 1 makes the granule 4 KB.
GRANULE = 1 << FILTER_BURST_GRANULE_BITS
# hw/ip/axi_filter/regs/filter_ctrl.rdl src_id: 0 is the wildcard, 1 to 15 select one source ID.
WILDCARD_SRC_ID = 0
SWEEP_SRC_IDS = tuple(range(1, 16))
# hw/ip/axi_filter/doc/index.adoc "Match, Then Permit": an entry with allow_ns 0 matches prot[1] 0
# and an entry with allow_ns 1 matches prot[1] 1, so the two entries form a polarity pair.
POLARITY_PAIR = (0, 1)
OUTBOUND_ENTRIES = (0, 1)

# Pages outside the SMC and SEP apertures and below 4 GiB (hw/sys/smu/doc/index.adoc "AXI
# Crossbar"). R is the 4 KB page of the iDMA destination.
SRC_PAGE = 0x0200_0000
PAGE_R = 0x0300_0000
# hw/sys/smc/doc/dma.adoc: the copy moves LENGTH bytes from SRC_ADDRESS to DST_ADDRESS.
COPY_LENGTH = 64
# Distinct non-zero 8-byte words repeated over the copy: source PS, initial destination D0 and the
# destination D1 written before the refused copy.
WORD_PS = 0x1111_2222_3333_4444
WORD_D0 = 0x9999_AAAA_BBBB_CCCC
WORD_D1 = 0x5555_6666_7777_8888
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc "JTAG2AXI single-operation fields": the size field
# requests 2**size bytes; 0 is one byte.
AXSIZE_BYTE = 0
FILL_BYTE = 0xA5
WRITE_BYTE = 0x3C
FILL_WORD = int.from_bytes(bytes([FILL_BYTE]) * 8, "little")
# dma_ctrl.rdl: DST_ADDRESS_HI, SRC_ADDRESS_HI, LENGTH_HI, both strides and NUM_REPETITIONS_HI reset
# to 0x0 and the strides apply only between rows, so a one-row copy below 4 GiB writes five
# registers.
DMA_REPETITIONS = 1

# Probe addresses. Inside R and clear of the destination bytes of the copy; outside R; elsewhere in
# the broad range of the priority legs.
PROBE_IN_R = PAGE_R + 0x100
PROBE_OUT_OF_R = PAGE_R + 2 * GRANULE + 0x100
PROBE_BROAD_ELSEWHERE = PAGE_R + 3 * GRANULE + 0x100
# hw/ip/axi_filter/doc/index.adoc granule widening table: START 0x1001 and END 0x1002 admit the one
# 4 KB granule 0x1000-0x1FFF; here that granule is R.
SPAN_START = PAGE_R + 1
SPAN_END = PAGE_R + 2
SPAN_END_RAISED = PAGE_R + GRANULE
BROAD_START = PAGE_R - 4 * GRANULE
BROAD_END = PAGE_R + 5 * GRANULE - 1

# Responder results of a refused and an admitted access: bridge status, the (AW, W, B, AR, R)
# handshake counts the access added, and the byte or word the responder returns or holds.
CHANNELS = ("aw", "w", "b", "ar", "r")
WRITE_REFUSED = (J2A_STATUS_DECERR, (0, 0, 0, 0, 0), FILL_BYTE)
WRITE_ADMITTED = (J2A_STATUS_SUCCESS, (1, 1, 1, 0, 0), WRITE_BYTE)
READ_ADMITTED = (J2A_STATUS_SUCCESS, (0, 0, 0, 1, 1), FILL_WORD)
READ_REFUSED = (J2A_STATUS_DECERR, (0, 0, 0, 0, 0), None)
MAX_REFUSING_SRC_IDS = 1

J2A_POLL_LIMIT = 128
J2A_ACCESS_BUDGET = 78
RESET_COPY_DONE_POLLS = 8
REFUSED_COPY_DONE_POLLS = 2
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
ACCESS_STEPS = STEPS[1:-1]


class _EgressTap:
    """Counts the five channel handshakes and records every address handshake on smu_axi_out."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.count = dict.fromkeys(CHANNELS, 0)
        self.aw: list[tuple[int, int, int, int]] = []
        self.ar: list[tuple[int, int, int, int]] = []
        self.edges = 0
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    def _fire(self, ch: str) -> bool:
        return bool(self._int(f"{ch}valid")) and bool(self._int(f"{ch}ready"))

    def _fields(self, ch: str) -> tuple[int, int, int, int]:
        return tuple(self._int(f"{ch}{f}") for f in ("addr", "len", "size", "prot"))

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            self.edges += 1
            for ch in CHANNELS:
                if self._fire(ch):
                    self.count[ch] += 1
                    if ch == "aw":
                        self.aw.append(self._fields("aw"))
                    elif ch == "ar":
                        self.ar.append(self._fields("ar"))

    def snapshot(self) -> tuple[int, ...]:
        return tuple(self.count[ch] for ch in CHANNELS)

    def mark(self) -> tuple[int, int]:
        return len(self.aw), len(self.ar)

    def since(self, mark: tuple[int, int]) -> tuple[list[tuple], list[tuple]]:
        return self.aw[mark[0] :], self.ar[mark[1] :]

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


def _covered(handshakes: list[tuple], base: int) -> tuple[int, int]:
    """Bytes the handshakes cover inside the 4 KB page at base, and the handshakes outside it."""
    inside = sum((p[1] + 1) << p[2] for p in handshakes if base <= p[0] < base + GRANULE)
    outside = sum(1 for p in handshakes if not base <= p[0] < base + GRANULE)
    return inside, outside


def _config(
    *, allow_ns: int, read: int, write: int, enabled: int = 1, src_id: int = WILDCARD_SRC_ID
) -> int:
    word = _F_BUS_WIDTH_64 | _F_ALLOW_BURST
    for flag, mask in (
        (read, _F_READ),
        (write, _F_WRITE),
        (enabled, _F_ENTRY),
        (allow_ns, _F_ALLOW_NS),
    ):
        if flag:
            word |= mask
    return word | filter_ctrl_field_encode("SRC_ID", src_id)


def _words(word: int) -> bytes:
    return word.to_bytes(8, "little") * (COPY_LENGTH // 8)


class smu_out_filter_rule_matrix_test_seq:
    """Outbound filter entries 0 and 1 over JTAG2AXI writes and reads and one iDMA copy."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = self.dut.clk_smu_i
        self.jtag = None
        self.tap = None
        self.step = "S1"
        self.step_ts: dict[str, float] = {}
        self.step_access = dict.fromkeys(STEPS, 0)
        self.j2a = 0
        self.sites: dict[str, dict] = {}
        self.entry = {i: {"start": None, "end": None, "config": None} for i in OUTBOUND_ENTRIES}
        self.refuse_ns = -1
        self.s2: tuple = ()
        self.write_outside_r: tuple = ()

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _chk(self, sb, chk: str, name: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {name}", observed, expected, evidence=chk)

    def _site(
        self,
        name: str,
        bound: int,
        unit: str,
        used: int | None,
        last: str,
        *,
        expired: bool = False,
        expiry_is_outcome: bool = False,
    ) -> None:
        site = self.sites.setdefault(
            name,
            {
                "bound": bound,
                "unit": unit,
                "used": None,
                "count": 0,
                "expired": 0,
                "last": last,
                "outcome": expiry_is_outcome,
            },
        )
        site["count"] += 1
        site["expired"] += int(expired)
        site["last"] = last
        if used is not None:
            site["used"] = max(site["used"] or 0, used)

    # ------------------------------------------------------------------
    # JTAG2AXI accesses.
    # ------------------------------------------------------------------

    async def _j2a(self, write: bool, addr: int, data: int = 0, **kw) -> tuple[int, int]:
        kind = "WR" if write else "RD"
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag, addr, data, poll_limit=J2A_POLL_LIMIT, require_complete=True, **kw
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag, addr, poll_limit=J2A_POLL_LIMIT, require_complete=True, **kw
                )
        except TimeoutError as exc:
            self._site("j2a", J2A_POLL_LIMIT, "polls", None, f"EXPIRED {exc}", expired=True)
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:x}")
        self.j2a += 1
        self.step_access[self.step] += 1
        self._site("j2a", J2A_POLL_LIMIT, "polls", None, f"{kind} @0x{addr:x} status={status}")
        return status, int(raw)

    async def _j2a_ok(self, write: bool, addr: int, data: int = 0, **kw) -> int:
        status, raw = await self._j2a(write, addr, data, **kw)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A @0x{addr:x} status={status} want SUCCESS")
        return raw

    async def _wr32(self, addr: int, value: int) -> None:
        word = int(value) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a_ok(True, addr, packed, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _rd32(self, addr: int) -> int:
        raw = await self._j2a_ok(False, addr, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _program(
        self, idx: int, *, start: int | None = None, end: int | None = None, config=None
    ) -> None:
        """Write the entry registers whose programmed value differs from the one last written."""
        regs = (
            ("start", start, OUTBOUND_FILTER_START_SYM),
            ("end", end, OUTBOUND_FILTER_END_SYM),
            ("config", config, OUTBOUND_FILTER_CONFIG_SYM),
        )
        for reg, value, sym in regs:
            if value is None or self.entry[idx][reg] == value:
                continue
            await self._j2a_ok(True, smc_indexed_addr(sym, idx), value)
            self.entry[idx][reg] = value

    # ------------------------------------------------------------------
    # Bridge probes: status, handshake counts added and responder byte or word.
    # ------------------------------------------------------------------

    async def _probe_write(self, addr: int) -> tuple:
        mem = self.cfg.axi_out_mem
        mem.write(addr, bytes([FILL_BYTE]))
        before = self.tap.snapshot()
        lane = addr & 0x7
        status, _ = await self._j2a(
            True, addr, WRITE_BYTE << (8 * lane), wstrb=1 << lane, size=AXSIZE_BYTE
        )
        delta = tuple(a - b for a, b in zip(self.tap.snapshot(), before))
        return status, delta, mem.read_int(addr, 1)

    async def _probe_read(self, addr: int) -> tuple:
        self.cfg.axi_out_mem.write(addr, bytes([FILL_BYTE]) * 8)
        before = self.tap.snapshot()
        status, raw = await self._j2a(False, addr)
        delta = tuple(a - b for a, b in zip(self.tap.snapshot(), before))
        return status, delta, raw if status == J2A_STATUS_SUCCESS else None

    # ------------------------------------------------------------------
    # iDMA copy.
    # ------------------------------------------------------------------

    async def _launch_and_poll(self, site: str, bound: int, *, expiry_is_outcome: bool):
        """Submit the programmed copy and poll DONE; return (id, done, polls used, completed)."""
        start_id = await self._rd32(DMA_NEXT_ID_0)
        done, used = None, 0
        for used in range(1, bound + 1):
            await ClockCycles(self.clk, DMA_POLL_CYCLES)
            done = await self._rd32(DMA_DONE_0)
            if done == start_id:
                break
        completed = done == start_id
        last = f"id={start_id} done={done} polls={used}"
        self._site(
            site,
            bound,
            "polls",
            used,
            last if completed else f"EXPIRED {last}",
            expired=not completed,
            expiry_is_outcome=expiry_is_outcome,
        )
        return start_id, done, used, completed

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
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self.tap = _EgressTap(dut)
        mem = self.cfg.axi_out_mem
        mem.write(SRC_PAGE, _words(WORD_PS))
        mem.write(PAGE_R, _words(WORD_D0))
        self._log(
            f"CELL setup counters(aw,w,b,ar,r)={self.tap.snapshot()} src=0x{SRC_PAGE:x} "
            f"R=0x{PAGE_R:x} length={COPY_LENGTH}"
        )

    async def _s2(self, sb) -> None:
        mem = self.cfg.axi_out_mem
        for addr, value in (
            (DMA_CONFIG, DMA_CONFIG_ENABLE_ND),
            (DMA_DST_LO, PAGE_R),
            (DMA_SRC_LO, SRC_PAGE),
            (DMA_LEN_LO, COPY_LENGTH),
            (DMA_REPS_LO, DMA_REPETITIONS),
        ):
            await self._wr32(addr, value)
        before = mem.read(PAGE_R, COPY_LENGTH)
        mark, counts = self.tap.mark(), self.tap.snapshot()
        start_id, done, used, completed = await self._launch_and_poll(
            "dma_done_reset_copy", RESET_COPY_DONE_POLLS, expiry_is_outcome=False
        )
        if not completed:
            raise AssertionError(f"TIMEOUT dma_done_reset_copy id={start_id} done={done}")
        aw, ar = self.tap.since(mark)
        after = mem.read(PAGE_R, COPY_LENGTH)
        delta = tuple(a - b for a, b in zip(self.tap.snapshot(), counts))
        self._log(
            f"OBSERVATION reset-state copy counters(aw,w,b,ar,r)+={delta} "
            f"awprot={sorted({p[3] for p in aw})} arprot={sorted({p[3] for p in ar})} "
            "measured and logged only"
        )
        self.s2 = (
            done == start_id,
            before.hex(),
            after.hex(),
            _covered(ar, SRC_PAGE),
            _covered(aw, PAGE_R),
        )
        self._log(f"CELL reset-state copy id={start_id} done={done} polls={used}")

    async def _s3(self, sb) -> None:
        span = (PAGE_R, PAGE_R + GRANULE - 1)
        deny = {ns: _config(allow_ns=ns, read=1, write=0) for ns in POLARITY_PAIR}
        off = {ns: _config(allow_ns=ns, read=1, write=0, enabled=0) for ns in POLARITY_PAIR}
        await self._program(0, start=span[0], end=span[1], config=deny[0])
        await self._program(1, start=span[0], end=span[1])
        mark = self.tap.mark()
        probe0 = await self._probe_write(PROBE_IN_R)
        await self._program(1, config=deny[1])
        await self._program(0, config=off[0])
        probe1 = await self._probe_write(PROBE_IN_R)
        aw, _ = self.tap.since(mark)
        refusing = [
            ns for ns, probe in zip(POLARITY_PAIR, (probe0, probe1)) if probe == WRITE_REFUSED
        ]
        admitted = [
            ns for ns, probe in zip(POLARITY_PAIR, (probe0, probe1)) if probe == WRITE_ADMITTED
        ]
        self._log(
            f"OBSERVATION refusing allow_ns={refusing} admitted allow_ns={admitted} "
            f"admitted awprot={[p[3] for p in aw]} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-OUTRULE-PROT1-PAIR",
            "exactly one single-entry probe is refused",
            (len(refusing), len(admitted)),
            (1, 1),
            f"allow_ns 0 probe={probe0} allow_ns 1 probe={probe1} refusing allow_ns={refusing} "
            "(measured and logged only: which value)",
        )
        if len(refusing) != 1:
            raise AssertionError(f"polarity pair: refusing allow_ns values {refusing}")
        self.refuse_ns = refusing[0]
        if self.refuse_ns == 0:
            await self._program(0, config=deny[0])
            await self._program(1, config=off[1])

    def _deny(self, *, read: int, write: int, src_id: int = WILDCARD_SRC_ID) -> int:
        return _config(allow_ns=self.refuse_ns, read=read, write=write, src_id=src_id)

    async def _s4(self, sb) -> None:
        entry = self.refuse_ns
        refused_write = await self._probe_write(PROBE_IN_R)
        self.write_outside_r = await self._probe_write(PROBE_OUT_OF_R)
        mark = self.tap.mark()
        admitted_read = await self._probe_read(PROBE_IN_R)
        _, ar = self.tap.since(mark)
        await self._program(entry, config=self._deny(read=0, write=0))
        refused_read = await self._probe_read(PROBE_IN_R)
        self._log(f"OBSERVATION admitted read arprot={[p[3] for p in ar]} measured and logged only")
        self._chk(
            sb,
            "CHK-OUTRULE-WRITE-DENY",
            "the write to R is refused, the write outside R is not",
            (refused_write, self.write_outside_r),
            (WRITE_REFUSED, WRITE_ADMITTED),
            f"entry {entry} write_allowed 0 src_id {WILDCARD_SRC_ID}: write to R "
            f"{refused_write}, write outside R {self.write_outside_r}",
        )
        self._chk(
            sb,
            "CHK-OUTRULE-READ-CHANNEL",
            "the read follows read_allowed, not the write outcome",
            (refused_write[0], admitted_read, refused_read),
            (J2A_STATUS_DECERR, READ_ADMITTED, READ_REFUSED),
            f"write_allowed 0 read_allowed 1: write {refused_write[0]}, read {admitted_read}; "
            f"read_allowed 0: read {refused_read}; refusing entry src_id {WILDCARD_SRC_ID}",
        )
        done, before_hex, after_hex, ar_cover, aw_cover = self.s2
        self._chk(
            sb,
            "CHK-OUTRULE-PERMIT-DEFAULT",
            "the reset-state copy completes and the write outside R passes",
            (done, after_hex, ar_cover, aw_cover, self.write_outside_r),
            (True, _words(WORD_PS).hex(), (COPY_LENGTH, 0), (COPY_LENGTH, 0), WRITE_ADMITTED),
            f"reset-state copy done_equals_id={done} D before={before_hex} (the D0 the bench "
            f"placed, logged only) after={after_hex} "
            f"AR bytes at source and AR outside={ar_cover} AW bytes at R and AW outside="
            f"{aw_cover}; write outside R with a deny entry {self.write_outside_r}",
        )

    async def _s5(self, sb) -> None:
        mem = self.cfg.axi_out_mem
        mem.write(PAGE_R, _words(WORD_D1))
        mark, counts = self.tap.mark(), self.tap.snapshot()
        start_id, done, used, completed = await self._launch_and_poll(
            "dma_done_refused_copy", REFUSED_COPY_DONE_POLLS, expiry_is_outcome=True
        )
        status = await self._rd32(DMA_STATUS_0)
        aw, ar = self.tap.since(mark)
        delta = tuple(a - b for a, b in zip(self.tap.snapshot(), counts))
        after = mem.read(PAGE_R, COPY_LENGTH)
        self._log(
            f"OBSERVATION refused copy id={start_id} done={done} status=0x{status:x} polls={used} "
            f"completed={completed} counters(aw,w,b,ar,r)+={delta} "
            f"arprot={sorted({p[3] for p in ar})} measured and logged only"
        )
        source_reads = _covered(ar, SRC_PAGE)[0]
        self._chk(
            sb,
            "CHK-OUTRULE-DMA-DENY",
            "the refused copy leaves D1 and the AW and W counters",
            (self.s2[2] == _words(WORD_PS).hex(), after.hex(), delta[:2], source_reads > 0),
            (True, _words(WORD_D1).hex(), (0, 0), True),
            f"destination after={after.hex()} AW,W added={delta[:2]} AR bytes at the source="
            f"{source_reads} (the copy ran); iDMA status=0x{status:x} done={done} id={start_id} "
            "(measured and logged only)",
        )

    async def _granule_probes(self, probes) -> dict:
        observed = {}
        for label, addr in probes:
            observed[label] = await self._probe_write(addr)
        return observed

    async def _s6(self, sb) -> None:
        entry = self.refuse_ns
        await self._program(entry, start=SPAN_START, end=SPAN_END)
        first = (("first byte", PAGE_R), ("last byte", PAGE_R + GRANULE - 1))
        around = (("byte below", PAGE_R - 1), ("byte above", PAGE_R + GRANULE))
        observed = await self._granule_probes(first + around)
        await self._program(entry, end=SPAN_END_RAISED)
        end_probes = (("END byte", SPAN_END_RAISED), ("granule above END", PAGE_R + 2 * GRANULE))
        observed.update(await self._granule_probes(end_probes))
        want = {
            "first byte": WRITE_REFUSED,
            "last byte": WRITE_REFUSED,
            "byte below": WRITE_ADMITTED,
            "byte above": WRITE_ADMITTED,
            "END byte": WRITE_REFUSED,
            "granule above END": WRITE_ADMITTED,
        }
        self._chk(
            sb,
            "CHK-OUTRULE-GRANULE-END",
            "the granule edges and the inclusive END decide as the chapter states",
            observed,
            want,
            f"START 0x{SPAN_START:x} END 0x{SPAN_END:x} then END 0x{SPAN_END_RAISED:x}: "
            f"{ {k: v[0] for k, v in observed.items()} }",
        )

    async def _s7(self, sb) -> None:
        ns = self.refuse_ns
        permit = _config(allow_ns=ns, read=1, write=1)
        deny = self._deny(read=0, write=0)
        await self._program(0, start=SPAN_START, end=SPAN_END_RAISED, config=deny)
        await self._program(1, start=BROAD_START, end=BROAD_END, config=permit)
        narrow_deny = await self._probe_write(PROBE_IN_R)
        broad_pass = await self._probe_write(PROBE_BROAD_ELSEWHERE)
        await self._program(0, config=permit)
        await self._program(1, config=deny)
        narrow_permit = await self._probe_write(PROBE_IN_R)
        broad_deny = await self._probe_write(PROBE_BROAD_ELSEWHERE)
        self._chk(
            sb,
            "CHK-OUTRULE-PRIORITY",
            "the lower index decides on the narrow range",
            (narrow_deny, broad_pass, narrow_permit, broad_deny),
            (WRITE_REFUSED, WRITE_ADMITTED, WRITE_ADMITTED, WRITE_REFUSED),
            f"entry 0 narrow deny over entry 1 broad permit: narrow {narrow_deny[0]}, elsewhere "
            f"{broad_pass[0]}; entry 0 narrow permit over entry 1 broad deny: narrow "
            f"{narrow_permit[0]}, elsewhere {broad_deny[0]}",
        )

    async def _s8(self, sb) -> None:
        await self._program(1, config=_config(allow_ns=self.refuse_ns, read=0, write=0, enabled=0))
        observed = {}
        for src_id in SWEEP_SRC_IDS:
            await self._program(0, config=self._deny(read=0, write=0, src_id=src_id))
            observed[src_id] = await self._probe_write(PROBE_IN_R)
        refusing = [k for k, probe in observed.items() if probe == WRITE_REFUSED]
        consistent = all(p in (WRITE_REFUSED, WRITE_ADMITTED) for p in observed.values())
        self._log(f"OBSERVATION refusing src_id values={refusing} measured and logged only")
        self._chk(
            sb,
            "CHK-OUTRULE-SRCID-SWEEP",
            "at most one src_id value refuses",
            (list(observed), consistent, len(refusing) <= MAX_REFUSING_SRC_IDS),
            (list(SWEEP_SRC_IDS), True, True),
            f"src_id 1 to 15 probed, refusing count={len(refusing)} values={refusing} "
            "(measured and logged only: count and value; only at most one is compared)",
        )

    def _s9(self, sb) -> None:
        for name, site in self.sites.items():
            used = "not measured" if site["used"] is None else site["used"]
            state = "EXPIRED" if site["expired"] else "ok"
            note = " (an expiry is recorded as the measured outcome)" if site["outcome"] else ""
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} used: {used} "
                f"count={site['count']} {state}{note} last={site['last']}"
            )
        unexpected = [n for n, s in self.sites.items() if s["expired"] and not s["outcome"]]
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] for s in self.sites.values())
        self._chk(
            sb,
            "CHK-TIMEOUT-PATHS",
            "bounded waits",
            (unexpected, finite, has_last, sorted(self.sites)),
            ([], True, True, ["dma_done_refused_copy", "dma_done_reset_copy", "j2a"]),
            f"sites={len(self.sites)} unexpected expiries={len(unexpected)} "
            f"j2a_accesses={self.j2a} budget={J2A_ACCESS_BUDGET} j2a_poll_limit={J2A_POLL_LIMIT}",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(self.clk, 16)
        plan = (
            ("S1", "SETUP: TAP, JTAG2AXI gate, responder patterns, egress counters", self._s1),
            ("S2", "reset-state iDMA copy", self._s2),
            ("S3", "polarity pair of single-entry write probes", self._s3),
            ("S4", "write deny, write pass and the read channel", self._s4),
            ("S5", "iDMA copy over the deny entry", self._s5),
            ("S6", "granule edges and inclusive END", self._s6),
            ("S7", "entry priority", self._s7),
            ("S8", "src_id sweep 1 to 15", self._s8),
        )
        try:
            for step, text, body in plan:
                await self._mark(step, text)
                await body(sb)
            await self._mark("S9", "TIMEOUT: bounded waits and last state")
            self._s9(sb)
            await ClockCycles(self.clk, 2)
            self.step_ts["PASS"] = get_sim_time("ns")
            order = [*STEPS, "PASS"]
            stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
            counts = " ".join(f"{s}={self.step_access[s]}" for s in STEPS)
            increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
            every_step = all(self.step_access[s] > 0 for s in ACCESS_STEPS)
            self._log(
                f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; j2a accesses {counts}"
            )
            self._chk(
                sb,
                "CHK-NONVAC",
                "ordered fence",
                (increasing, every_step, self.tap.edges > 0),
                (True, True, True),
                f"stamps strictly increase to the pass point, S2..S8 each count an access, the "
                f"egress counters were sampled on {self.tap.edges} edges, total {self.j2a}",
            )
        finally:
            if self.tap is not None:
                self.tap.stop()
