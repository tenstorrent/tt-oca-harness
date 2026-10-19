# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP outbound filter rule matrix probed through the SEP debug module's system bus.

``hw/ip/axi_filter/doc/index.adoc``: the SEP outbound instance has 32 entries, blocks unmatched
traffic and has no bypass. "Match, Then Permit": an entry matches when it is enabled, the address
is in its range, ``prot[1]`` equals ``allow_ns``, the source ID matches (``src_id`` 0 is the
wildcard) and ``allow_burst`` is 1 or the access is a single beat; the lowest-numbered matching
entry's ``read_allowed`` (AR) or ``write_allowed`` (AW) then decides. "Address Range Granule":
``allow_burst`` 1 gives a 4 KB granule, ``START_ADDR`` widens down and ``END_ADDR`` widens up to its
granule. ``hw/sys/sep/doc/fabric.adoc`` "Filtering and Protection": the outbound filter blocks
unmatched traffic and has no bypass, so SEP-scope debug being open does not open it; the DUT's
``lcc_dbg_disable_o`` sampled at 0 is the debug-open posture that the no-bypass compare carries.

The debug module's system bus (RISC-V Debug Specification 0.13, "System Bus Access") reports a
refused access in ``sbcs.sberror``; the code is measured and logged. The system bus issues
single-beat accesses, so ``allow_burst`` against ``AxLEN`` is not exercised. Which ``allow_ns``
value matches the system bus is measured and logged.

S1: bring up the debug module over the SEP STAP; the probe window sits in the SMU aperture.
S2: every outbound entry at reset refuses a write and a read; an admit-all pair at entries 30
    (``allow_ns`` 0) and 31 (``allow_ns`` 1) then lets both land in the responder memory.
S3: a deny pair at entries 0 and 1 over one 4 KB page: ``write_allowed`` 0 refuses the write and
    admits the read, ``read_allowed`` 0 admits the write and refuses the read, and a write
    outside the page is admitted.
S4: with one entry of the pair enabled at a time, exactly one of the two write probes is refused;
    the refusing entry alone stays enabled.
S5: ``START_ADDR`` 0x1001 and ``END_ADDR`` 0x1002 refuse 0x1000 and 0x1FFF and admit 0x0FFF and
    0x2000; ``END_ADDR`` 0x2000 refuses 0x2000 and admits 0x3000.
S6: each of entries 0, 15, 16 and 31 alone admits a probe; entry 0 as a narrow deny over entry 31
    as a broad permit refuses the narrow write; entry 15 as a narrow permit over entry 16 as a
    broad deny admits the narrow write.
S7: every bounded wait reports its bound, its measured use or that it is not measured, and its
    last state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_addr_map import (
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
)
from seq_lib.smu_axi_out_addr_len_size_test_seq import _OutboundTap
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMSTATUS_VERSION_SPEC_0_13,
    POSTURE_SETTLE_POLLS,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    DMI_RETRIES,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    _indexed_addr,
)
from seq_lib.smu_filter_helpers import FILTER_BURST_GRANULE_BITS
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    ADDR_MASK,
    SMU_BASE,
    SMU_SIZE,
    smu_sep_sba_fabric_sweep_test_seq,
)

# hw/ip/axi_filter/regs/gen/c/filter_ctrl.h: FILTER_CONFIG field masks.
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")

# hw/sys/sep/regs/gen/c/sep_addr.h SEP_TOP_OUTBOUND_FILTER_CTRL_*_BASE_ADDR(i): entry registers.
_START_SYMBOL = "SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_END_SYMBOL = "SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"
_CONFIG_SYMBOL = "SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"

# hw/ip/axi_filter/doc/index.adoc instance table: the SEP outbound instance has 32 entries.
ADMIT_ENTRY_LOW = 30
ADMIT_ENTRY_HIGH = 31
DENY_ENTRY_LOW = 0
DENY_ENTRY_HIGH = 1
INDEX_MID_LOW = 15
INDEX_MID_HIGH = 16
INDEX_FIRST = 0
INDEX_LAST = 31

# hw/ip/axi_filter/doc/index.adoc "Address Range Granule": allow_burst 1 gives a 4 KB granule.
GRANULE = 1 << FILTER_BURST_GRANULE_BITS
# hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl SMU_GLOBAL_BASE_ADDR and SMU_REGION_SIZE
# reset values: a SEP address inside the aperture leaves on the outbound path.
PAGE_SET = SMU_BASE + 0x1000_0000
PAGE_SET_SPAN = 8 * GRANULE

# Word probes. Page n of the set is PAGE_SET + n * GRANULE.
DEFAULT_PROBE = PAGE_SET + 0x100
DENY_PAGE_LOW = PAGE_SET + 7 * GRANULE
DENY_PAGE_HIGH = PAGE_SET + 8 * GRANULE - 1
DENY_PROBE = DENY_PAGE_LOW + 0x100
POLARITY_PROBE = DENY_PAGE_LOW + 0x200
OUTSIDE_PROBE = PAGE_SET + 3 * GRANULE + 0x100
NARROW_PROBE_DENY_PAGE = DENY_PAGE_LOW + 0x300
NARROW_PROBE_GRANULE = PAGE_SET + GRANULE + 0x300
ELSEWHERE_PROBE = PAGE_SET + 5 * GRANULE + 0x100
MID_PAGE_LOW = PAGE_SET + 4 * GRANULE
MID_PAGE_HIGH = PAGE_SET + 5 * GRANULE - 1
MID_PROBE = MID_PAGE_LOW + 0x100
BROAD_ONLY_PROBE = PAGE_SET + 6 * GRANULE + 0x100
BROAD_LOW = PAGE_SET
BROAD_HIGH = PAGE_SET + PAGE_SET_SPAN - 1

# hw/ip/axi_filter/doc/index.adoc "Address Range Granule" example table (allow_burst 1): START
# 0x1001 and END 0x1002 admit 0x1000-0x1FFF, one 4 KB granule, the page set's page 1.
START_IN_GRANULE = PAGE_SET + GRANULE + 1
END_IN_GRANULE = PAGE_SET + GRANULE + 2
# The same section: a START and END in one granule are written back widened, so they read back as
# the granule's first and last address; the low word of each register holds the whole address.
GRANULE_FIRST = PAGE_SET + GRANULE
GRANULE_LAST = PAGE_SET + 2 * GRANULE - 1
GRANULE_BELOW = PAGE_SET + GRANULE - 1
GRANULE_ABOVE = PAGE_SET + 2 * GRANULE
# END raised to the first address of the next granule widens up to that granule's top.
END_RAISED = PAGE_SET + 2 * GRANULE
RAISED_NEXT = PAGE_SET + 3 * GRANULE

# Debug module registers: RISC-V Debug Specification 0.13, sbcs.sbaccess in bits [19:17].
SBACCESS_SHIFT = 17
SIZE_BYTE = 0
SIZE_WORD = 2
SIZE_DOUBLEWORD = 3

# hw/ip/axi_filter/doc/index.adoc "Blocked Transactions": a blocked transaction is answered with an
# error, which the debug module reports as a non-zero sbcs.sberror.
SENTINEL_BYTE = 0x5A
PATTERN_SEED = 0xC3A5_96E1_7B2D_4F08

ACCESS_BUDGET = 67
OBSERVE_BOUND_CYCLES = 4000
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
ACCESS_STEPS = STEPS[1:-1]
EXPECTED_WAIT_LABELS = ("dmi_retry", "posture_settle", "responder_observe", "sba_busy_poll")


def _sentinel(nbytes: int) -> int:
    return int.from_bytes(bytes([SENTINEL_BYTE]) * nbytes, "little")


def _pattern(tag: int, nbytes: int) -> int:
    word = (PATTERN_SEED ^ (tag * 0x0101_0101_0101_0101)) & ((1 << (8 * nbytes)) - 1)
    return word


def _require_layout() -> None:
    probes = (
        DEFAULT_PROBE,
        DENY_PROBE,
        POLARITY_PROBE,
        OUTSIDE_PROBE,
        NARROW_PROBE_DENY_PAGE,
        NARROW_PROBE_GRANULE,
        ELSEWHERE_PROBE,
        MID_PROBE,
        BROAD_ONLY_PROBE,
    )
    facts = (
        (SMU_BASE <= PAGE_SET and PAGE_SET + PAGE_SET_SPAN <= SMU_BASE + SMU_SIZE, "window"),
        (PAGE_SET % PAGE_SET_SPAN == 0, "window alignment"),
        (all(p % 4 == 0 for p in probes), "word alignment"),
        (
            DENY_PAGE_LOW <= NARROW_PROBE_DENY_PAGE <= DENY_PAGE_HIGH,
            "narrow probe in the deny page",
        ),
        (
            GRANULE_FIRST <= NARROW_PROBE_GRANULE <= GRANULE_LAST
            and not DENY_PAGE_LOW <= GRANULE_FIRST <= DENY_PAGE_HIGH,
            "the S5 range differs from the deny page",
        ),
        (not DENY_PAGE_LOW <= ELSEWHERE_PROBE <= DENY_PAGE_HIGH, "elsewhere in the deny page"),
        (MID_PAGE_LOW <= MID_PROBE <= MID_PAGE_HIGH, "mid probe in the mid page"),
        (
            BROAD_LOW <= BROAD_ONLY_PROBE <= BROAD_HIGH
            and not MID_PAGE_LOW <= BROAD_ONLY_PROBE <= MID_PAGE_HIGH,
            "broad-only probe",
        ),
        (
            all(_pattern(tag, n) != _sentinel(n) for tag in range(64) for n in (1, 4)),
            "pattern against sentinel",
        ),
        (GRANULE_LAST < 1 << 32, "granule edges within the register's low word"),
        (GRANULE_BELOW < GRANULE_FIRST < GRANULE_LAST < GRANULE_ABOVE, "granule edges"),
    )
    bad = [name for ok, name in facts if not ok]
    if bad:
        raise RuntimeError("SEP outbound rule matrix layout: " + ", ".join(bad))


_require_layout()


def _config(
    allow_ns: int, *, read: int = 1, write: int = 1, enabled: int = 1, src_id: int = 0
) -> int:
    word = _F_BUS_WIDTH_64 | _F_ALLOW_BURST | filter_ctrl_field_encode("SRC_ID", src_id)
    for flag, mask in (
        (read, _F_READ),
        (write, _F_WRITE),
        (enabled, _F_ENTRY),
        (allow_ns, _F_ALLOW_NS),
    ):
        if flag:
            word |= mask
    return word


class smu_sep_out_filter_rule_matrix_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """SEP outbound filter entries programmed and probed over the debug module's system bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.clk = cocotb.top.clk_smu_i
        self.tap: _OutboundTap | None = None
        self.step = "S1"
        self.step_ts: dict[str, float] = {}
        self.step_access = {step: 0 for step in STEPS}
        self.accesses = 0
        self.sites: dict[str, dict] = {}
        self.error_codes: list[int] = []
        self.allow_ns = 0
        self.default_write: tuple = ()
        self.default_read: tuple = ()

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, name: str, bound: int, used: int | None, last: str, unit: str) -> None:
        site = self.sites.setdefault(
            name, {"bound": bound, "used": None, "last": last, "unit": unit, "count": 0}
        )
        site["count"] += 1
        site["last"] = last
        if used is not None:
            site["used"] = max(site["used"] or 0, used)

    def _chk(self, sb, chk: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} outcomes", observed, expected, evidence=chk)

    async def _bus(self, addr: int, size: int, data: int | None = None) -> tuple[int, int]:
        """One system-bus access of 2**size bytes; returns (sberror, read data).

        The sbcs write that starts the access also clears sberror, and every access of the
        leaf goes through this method, so ``accesses`` is the number of system-bus accesses.
        """
        self.accesses += 1
        self.step_access[self.step] += 1
        jtag = self.jtag
        sbcs = (size << SBACCESS_SHIFT) | SBCS_SBERROR_W1C
        if data is None:
            sbcs |= SBCS_SBREADONADDR
        await self._post(jtag, SBCS_ADDR, sbcs)
        if data is not None and size == SIZE_DOUBLEWORD:
            await self._post(jtag, SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF)
        await self._post(jtag, SBADDRESS0_ADDR, addr)
        if data is not None:
            await self._post(jtag, SBDATA0_ADDR, data & 0xFFFF_FFFF)
        status = 0
        for used in range(1, SBA_POLLS + 1):
            status = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not status & SBCS_SBBUSY:
                break
        else:
            self._site(
                "sba_busy_poll", SBA_POLLS, SBA_POLLS + 1, f"EXPIRED sbcs=0x{status:08x}", "polls"
            )
            raise AssertionError(
                f"system-bus access 0x{addr:08x}: sbbusy never cleared in {SBA_POLLS} polls, "
                f"last sbcs=0x{status:08x}"
            )
        self._site("sba_busy_poll", SBA_POLLS, used, f"sbcs=0x{status:08x}", "polls")
        if status & SBCS_SBBUSYERROR:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbbusyerror")
        if (status >> SBACCESS_SHIFT) & 0x7 != size:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbcs=0x{status:08x} lost")
        err = (status >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err:
            self.error_codes.append(err)
            return err, 0
        if data is not None:
            return 0, 0
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)
        return 0, value & ((1 << (8 << size)) - 1)

    async def _observe(self, mark: tuple[int, int], want_aw: int, want_ar: int) -> None:
        """Wait, bounded, until the responder tap shows the handshakes an admitted access made."""
        last = "no sample"
        for used in range(OBSERVE_BOUND_CYCLES + 1):
            aw, ar = self.tap.since(mark)
            last = f"aw={len(aw)} ar={len(ar)}"
            if len(aw) >= want_aw and len(ar) >= want_ar:
                self._site("responder_observe", OBSERVE_BOUND_CYCLES, used, last, "clk_smu cycles")
                return
            await ClockCycles(self.clk, 1)
        self._site(
            "responder_observe",
            OBSERVE_BOUND_CYCLES,
            OBSERVE_BOUND_CYCLES + 1,
            f"EXPIRED {last}",
            "clk_smu cycles",
        )
        raise AssertionError(
            f"responder observation expired after {OBSERVE_BOUND_CYCLES} cycles, last {last}"
        )

    async def _write_probe(self, addr: int, size: int, tag: int) -> tuple:
        """Write one pattern; returns (sberror non-zero, AW addresses, AR addresses, bytes held)."""
        nbytes = 1 << size
        self.mem.write_int(addr, _sentinel(nbytes), nbytes)
        mark = self.tap.mark()
        err, _ = await self._bus(addr, size, _pattern(tag, nbytes))
        if err == 0:
            await self._observe(mark, 1, 0)
        aw, ar = self.tap.since(mark)
        held = self.mem.read_int(addr, nbytes)
        return err != 0, [a[0] for a in aw], [a[0] for a in ar], held

    async def _read_probe(self, addr: int, size: int, tag: int) -> tuple:
        """Read a word the bench placed; the result is (sberror non-zero, AW, AR, data)."""
        nbytes = 1 << size
        self.mem.write_int(addr, _pattern(tag, nbytes), nbytes)
        mark = self.tap.mark()
        err, data = await self._bus(addr, size)
        if err == 0:
            await self._observe(mark, 0, 1)
        aw, ar = self.tap.since(mark)
        return err != 0, [a[0] for a in aw], [a[0] for a in ar], data

    @staticmethod
    def _write_outcome(refused: bool, addr: int, size: int, tag: int) -> tuple:
        nbytes = 1 << size
        if refused:
            return True, [], [], _sentinel(nbytes)
        return False, [addr], [], _pattern(tag, nbytes)

    @staticmethod
    def _read_outcome(refused: bool, addr: int, size: int, tag: int) -> tuple:
        if refused:
            return True, [], [], 0
        return False, [], [addr], _pattern(tag, 1 << size)

    async def _bus_ok(self, addr: int, size: int, data: int | None = None) -> int:
        """A system-bus access that must complete with sberror 0; returns the read data."""
        err, value = await self._bus(addr, size, data)
        if err:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sberror={err}")
        return value

    async def _program(self, entry: int, low: int, high: int, config: int) -> None:
        await self._start(entry, low)
        await self._end(entry, high)
        await self._config(entry, config)

    async def _config(self, entry: int, config: int) -> None:
        await self._bus_ok(_indexed_addr(_CONFIG_SYMBOL, entry), SIZE_WORD, config)

    async def _start(self, entry: int, low: int) -> None:
        await self._bus_ok(_indexed_addr(_START_SYMBOL, entry), SIZE_DOUBLEWORD, low)

    async def _end(self, entry: int, high: int) -> None:
        await self._bus_ok(_indexed_addr(_END_SYMBOL, entry), SIZE_DOUBLEWORD, high)

    async def _s1(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        if not (self.s1_ok and self.s2_ok and self.s3_ok):
            raise AssertionError("debug module bring-up incomplete")
        self._site("posture_settle", POSTURE_SETTLE_POLLS, None, "not measured", "polls")
        self._site("dmi_retry", DMI_RETRIES, None, "not measured", "retries")
        version = self.dmstatus & 0xF
        self._log(
            f"OBSERVATION window=0x{PAGE_SET:x}..0x{PAGE_SET + PAGE_SET_SPAN - 1:x} "
            f"smu_base=0x{SMU_BASE:x} dmstatus_version={version} "
            f"budget={ACCESS_BUDGET}"
        )
        self.tap = _OutboundTap(self.dut)
        aw0, ar0 = self.tap.mark()
        self._log(f"OBSERVATION responder counters at start aw={aw0} ar={ar0}")

    async def _s2(self, sb) -> None:
        refused_w = await self._write_probe(DEFAULT_PROBE, SIZE_WORD, 1)
        refused_r = await self._read_probe(DEFAULT_PROBE, SIZE_WORD, 2)
        self.default_write, self.default_read = refused_w, refused_r
        await self._program(ADMIT_ENTRY_LOW, 0, ADDR_MASK, _config(0))
        await self._program(ADMIT_ENTRY_HIGH, 0, ADDR_MASK, _config(1))
        admitted_w = await self._write_probe(DEFAULT_PROBE, SIZE_WORD, 3)
        admitted_r = await self._read_probe(DEFAULT_PROBE, SIZE_WORD, 3)
        codes = sorted(set(self.error_codes))
        self._log(f"OBSERVATION sberror code of the refused unmatched accesses={codes}")
        self._chk(
            sb,
            "CHK-SEPOUT-BLOCK-DEFAULT",
            {
                "write, every entry at reset": refused_w,
                "read, every entry at reset": refused_r,
                "write, admit pair": admitted_w,
                "read, admit pair": admitted_r,
            },
            {
                "write, every entry at reset": self._write_outcome(True, DEFAULT_PROBE, 2, 1),
                "read, every entry at reset": self._read_outcome(True, DEFAULT_PROBE, 2, 2),
                "write, admit pair": self._write_outcome(False, DEFAULT_PROBE, 2, 3),
                "read, admit pair": self._read_outcome(False, DEFAULT_PROBE, 2, 3),
            },
            "unmatched write and read refused with no AW or AR at the responder and the byte "
            "unchanged; after the admit pair the write lands and the read returns the word",
        )
        dbg_disable = sample(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        self._chk(
            sb,
            "CHK-SEPOUT-DEBUG-OPEN-NOBYPASS",
            (self.dmstatus & 0xF, dbg_disable, refused_w[0], refused_r[0], admitted_w[0]),
            (DMSTATUS_VERSION_SPEC_0_13, 0, True, True, False),
            f"the debug module answers with lcc_dbg_disable_o=0x{dbg_disable:04x} (every debug "
            "path open) and a system-bus write lands after the admit pair, while the unmatched "
            "write and read were refused",
        )

    async def _s3(self, sb) -> None:
        for entry in (DENY_ENTRY_LOW, DENY_ENTRY_HIGH):
            await self._program(
                entry, DENY_PAGE_LOW, DENY_PAGE_HIGH, _config(entry, read=0, write=1)
            )
        write_ok = await self._write_probe(DENY_PROBE, SIZE_WORD, 10)
        read_refused = await self._read_probe(DENY_PROBE, SIZE_WORD, 11)
        for entry in (DENY_ENTRY_LOW, DENY_ENTRY_HIGH):
            await self._config(entry, _config(entry, read=1, write=0))
        write_refused = await self._write_probe(DENY_PROBE, SIZE_WORD, 12)
        read_ok = await self._read_probe(DENY_PROBE, SIZE_WORD, 13)
        outside = await self._write_probe(OUTSIDE_PROBE, SIZE_WORD, 14)
        self._chk(
            sb,
            "CHK-SEPOUT-PERM-CHANNEL",
            {
                "read_allowed 0 write_allowed 1: write": write_ok,
                "read_allowed 0 write_allowed 1: read": read_refused,
                "read_allowed 1 write_allowed 0: write": write_refused,
                "read_allowed 1 write_allowed 0: read": read_ok,
                "write outside the page": outside,
            },
            {
                "read_allowed 0 write_allowed 1: write": self._write_outcome(
                    False, DENY_PROBE, 2, 10
                ),
                "read_allowed 0 write_allowed 1: read": self._read_outcome(True, DENY_PROBE, 2, 11),
                "read_allowed 1 write_allowed 0: write": self._write_outcome(
                    True, DENY_PROBE, 2, 12
                ),
                "read_allowed 1 write_allowed 0: read": self._read_outcome(
                    False, DENY_PROBE, 2, 13
                ),
                "write outside the page": self._write_outcome(False, OUTSIDE_PROBE, 2, 14),
            },
            "each permission bit acts on its own channel only: the refused write leaves no AW "
            "and the byte unchanged, and the write outside the page is admitted",
        )

    async def _s4(self, sb) -> None:
        deny = {entry: _config(entry, read=1, write=0) for entry in (0, 1)}
        off = {entry: _config(entry, read=1, write=0, enabled=0) for entry in (0, 1)}
        await self._config(DENY_ENTRY_LOW, off[0])
        probe_high = await self._write_probe(POLARITY_PROBE, SIZE_WORD, 20)
        await self._config(DENY_ENTRY_LOW, deny[0])
        await self._config(DENY_ENTRY_HIGH, off[1])
        probe_low = await self._write_probe(POLARITY_PROBE, SIZE_WORD, 21)
        refused = {1: probe_high[0], 0: probe_low[0]}
        consistent = (
            probe_high == self._write_outcome(probe_high[0], POLARITY_PROBE, 2, 20),
            probe_low == self._write_outcome(probe_low[0], POLARITY_PROBE, 2, 21),
        )
        self.allow_ns = 1 if refused[1] else 0
        self._log(
            f"OBSERVATION allow_ns of the refusing entry={self.allow_ns} "
            f"single-entry probe allow_ns0_refused={refused[0]} allow_ns1_refused={refused[1]}"
        )
        if self.allow_ns == 1:
            await self._config(DENY_ENTRY_HIGH, deny[1])
            await self._config(DENY_ENTRY_LOW, off[0])
        self._chk(
            sb,
            "CHK-SEPOUT-PROT1-PAIR",
            (sum(refused.values()), consistent),
            (1, (True, True)),
            "of the single-entry write probes (allow_ns 0 and allow_ns 1) exactly one is refused "
            "with the responder consistent with the answer; the refusing value is measured and "
            "logged only",
        )

    async def _s5(self, sb) -> None:
        entry = self.allow_ns
        await self._start(entry, START_IN_GRANULE)
        await self._end(entry, END_IN_GRANULE)
        start_back = await self._bus_ok(_indexed_addr(_START_SYMBOL, entry), SIZE_WORD)
        end_back = await self._bus_ok(_indexed_addr(_END_SYMBOL, entry), SIZE_WORD)
        legs = (
            ("0x1000 first byte", GRANULE_FIRST, True, 30),
            ("0x1FFF last byte", GRANULE_LAST, True, 31),
            ("0x0FFF below", GRANULE_BELOW, False, 32),
            ("0x2000 above", GRANULE_ABOVE, False, 33),
        )
        observed = {"START_ADDR readback": start_back, "END_ADDR readback": end_back}
        expected = {"START_ADDR readback": GRANULE_FIRST, "END_ADDR readback": GRANULE_LAST}
        for name, addr, refused, tag in legs:
            observed[name] = await self._write_probe(addr, SIZE_BYTE, tag)
            expected[name] = self._write_outcome(refused, addr, 0, tag)
        await self._end(entry, END_RAISED)
        for name, addr, refused, tag in (
            ("END 0x2000: 0x2000 equal to END", END_RAISED, True, 34),
            ("END 0x2000: 0x3000 next granule", RAISED_NEXT, False, 35),
        ):
            observed[name] = await self._write_probe(addr, SIZE_BYTE, tag)
            expected[name] = self._write_outcome(refused, addr, 0, tag)
        self._chk(
            sb,
            "CHK-SEPOUT-GRANULE-END",
            observed,
            expected,
            "START 0x1001 and END 0x1002 in one granule read back widened to 0x1000 and 0x1FFF, "
            "refuse 0x1000 and 0x1FFF and admit 0x0FFF and 0x2000; "
            "END 0x2000 refuses 0x2000 and admits 0x3000",
        )

    async def _s6(self, sb) -> None:
        allow_ns = self.allow_ns
        # Entry 0 holds the deny page when entry 1 refuses and the widened granule when entry 0
        # does.
        narrow_addr = NARROW_PROBE_DENY_PAGE if allow_ns else NARROW_PROBE_GRANULE
        permit = _config(allow_ns)
        deny = _config(allow_ns, read=1, write=0)
        observed_index: dict[str, tuple] = {}
        expected_index: dict[str, tuple] = {}

        def admitted(label: str, got: tuple, addr: int, tag: int) -> None:
            observed_index[label] = got
            expected_index[label] = self._write_outcome(False, addr, 2, tag)

        observed_index["every entry at reset"] = self.default_write
        expected_index["every entry at reset"] = self._write_outcome(True, DEFAULT_PROBE, 2, 1)
        await self._config(self.allow_ns, _config(allow_ns, enabled=0))
        await self._config(ADMIT_ENTRY_LOW, _config(0, enabled=0))
        await self._config(ADMIT_ENTRY_HIGH, _config(1, enabled=0))
        disabled = await self._write_probe(narrow_addr, SIZE_WORD, 40)
        observed_index["every entry disabled"] = disabled
        expected_index["every entry disabled"] = self._write_outcome(True, narrow_addr, 2, 40)
        await self._config(INDEX_FIRST, permit)
        admitted(
            "entry 0 alone",
            await self._write_probe(narrow_addr, SIZE_WORD, 41),
            narrow_addr,
            41,
        )

        await self._config(INDEX_FIRST, deny)
        await self._config(INDEX_LAST, permit)
        narrow = await self._write_probe(narrow_addr, SIZE_WORD, 42)
        elsewhere = await self._write_probe(ELSEWHERE_PROBE, SIZE_WORD, 43)

        await self._config(INDEX_FIRST, _config(allow_ns, enabled=0))
        admitted(
            "entry 31 alone",
            await self._write_probe(narrow_addr, SIZE_WORD, 44),
            narrow_addr,
            44,
        )
        await self._config(INDEX_LAST, _config(allow_ns, enabled=0))
        await self._program(INDEX_MID_LOW, MID_PAGE_LOW, MID_PAGE_HIGH, permit)
        admitted(
            "entry 15 alone",
            await self._write_probe(MID_PROBE, SIZE_WORD, 45),
            MID_PROBE,
            45,
        )
        await self._config(INDEX_MID_LOW, _config(allow_ns, enabled=0))
        await self._program(INDEX_MID_HIGH, BROAD_LOW, BROAD_HIGH, permit)
        admitted(
            "entry 16 alone",
            await self._write_probe(MID_PROBE, SIZE_WORD, 46),
            MID_PROBE,
            46,
        )
        self._chk(
            sb,
            "CHK-SEPOUT-INDEX-ALONE",
            observed_index,
            expected_index,
            "with every other entry disabled each of entries 0, 15, 16 and 31 admits a probe "
            "after the unmatched refusals held with no entry enabled",
        )

        await self._config(INDEX_MID_HIGH, deny)
        await self._config(INDEX_MID_LOW, permit)
        mid_narrow = await self._write_probe(MID_PROBE, SIZE_WORD, 47)
        broad_only = await self._write_probe(BROAD_ONLY_PROBE, SIZE_WORD, 48)
        self._chk(
            sb,
            "CHK-SEPOUT-PRIORITY",
            {
                "entry 0 deny over entry 31 permit: narrow write": narrow,
                "entry 0 deny over entry 31 permit: write elsewhere": elsewhere,
                "entry 15 permit over entry 16 deny: narrow write": mid_narrow,
                "entry 15 permit over entry 16 deny: elsewhere in the broad range": broad_only,
            },
            {
                "entry 0 deny over entry 31 permit: narrow write": self._write_outcome(
                    True, narrow_addr, 2, 42
                ),
                "entry 0 deny over entry 31 permit: write elsewhere": self._write_outcome(
                    False, ELSEWHERE_PROBE, 2, 43
                ),
                "entry 15 permit over entry 16 deny: narrow write": self._write_outcome(
                    False, MID_PROBE, 2, 47
                ),
                "entry 15 permit over entry 16 deny: elsewhere in the broad range": (
                    self._write_outcome(True, BROAD_ONLY_PROBE, 2, 48)
                ),
            },
            "the lower index decides: the narrow deny at entry 0 refuses over the broad permit at "
            "entry 31, and the narrow permit at entry 15 admits over the broad deny at entry 16",
        )

    def _s7(self, sb) -> None:
        expired = [
            n for n, s in self.sites.items() if s["used"] is not None and s["used"] > s["bound"]
        ]
        for name, site in sorted(self.sites.items()):
            used = "used: not measured" if site["used"] is None else f"max_used={site['used']}"
            state = "EXPIRED" if name in expired else "ok"
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} {used} "
                f"count={site['count']} {state} last={site['last']}"
            )
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] for s in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={len(expired)} "
            f"labels={sorted(self.sites)}"
        )
        sb.expect_eq("expired bounded waits", expired, [], evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait labels, each exactly once",
            sorted(self.sites),
            sorted(EXPECTED_WAIT_LABELS),
            evidence="CHK-TIMEOUT-PATHS",
        )
        sb.expect_eq(
            "every bounded wait has a finite bound and a last state",
            (finite, has_last),
            (True, True),
            evidence="CHK-TIMEOUT-PATHS",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self._mark("S1", "SETUP: debug module, probe window, responder counters")
        try:
            await self._s1()
            await self._mark("S2", "block by default, then the admit pair")
            await self._s2(sb)
            await self._mark("S3", "permission per channel on a deny pair")
            await self._s3(sb)
            await self._mark("S4", "prot[1] polarity, single-entry probes")
            await self._s4(sb)
            await self._mark("S5", "granule and inclusive end")
            await self._s5(sb)
            await self._mark("S6", "index alone and priority")
            await self._s6(sb)
            await self._mark("S7", "TIMEOUT: bounded waits and last state")
            self._s7(sb)
        finally:
            if self.tap is not None:
                self.tap.stop()
        await ClockCycles(self.clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        counts = " ".join(f"{s}:{self.step_access[s]}" for s in STEPS)
        increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
        every_step = all(self.step_access[s] > 0 for s in ACCESS_STEPS)
        tally = sum(self.step_access.values())
        self._log(
            f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; system-bus accesses "
            f"{self.accesses} of {ACCESS_BUDGET} ({counts})"
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence and access counts",
            (increasing, every_step, tally == self.accesses, self.accesses <= ACCESS_BUDGET),
            (True, True, True, True),
            evidence="CHK-NONVAC",
        )
