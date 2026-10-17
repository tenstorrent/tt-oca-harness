# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP AP and STEE output remap regions 1 to 15 probed through the debug module's system bus.

``hw/ip/output_remap/regs/output_remap.rdl`` REGION_ATTRS: with ``valid`` set the ``offset``
field replaces the address bits above the region granule (SEP: 16 regions of 512 KiB, so 19 low
bits are kept); with ``valid`` clear the access passes through with its address unchanged.
``hw/sys/sep/doc/fabric.adoc`` "Fabric Topology": the AP and STEE regions pass their output remaps
before the outbound mux and the outbound filter. The AP and STEE windows each hold 16 regions;
region k of a window starts at the window base plus k times the region size.

The debug module's system bus (RISC-V Debug Specification 0.13, "System Bus Access") issues
single-beat accesses and reports a refused access in ``sbcs.sberror``. The bench checks every
write from the responder memory and the AW handshakes of the outbound interface; no system-bus
read is issued.

S1: bring up the debug module over the SEP STAP, program an outbound admit pair (``allow_ns`` 0
    and 1) over the whole address space, fill the responder with a sentinel and record the AW
    counter.
S2: for k = 1 to 15, program AP region k and then STEE region k with distinct offsets and valid,
    then write one doubleword in each window at region k, offset 0x40.
S3: region 0 of each table, never programmed, passes a write through at the unchanged address;
    AP region 7 and STEE region 7, with ``valid`` cleared and the offset kept, do the same.
S4: every bounded wait reports its bound, its measured use or that it is not measured, and its
    last state.
"""

from __future__ import annotations

from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    POSTURE_SETTLE_POLLS,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import DMI_RETRIES, _indexed_addr
from seq_lib.smu_sep_out_filter_rule_matrix_test_seq import (
    ADMIT_ENTRY_HIGH,
    ADMIT_ENTRY_LOW,
    SIZE_DOUBLEWORD,
    _config,
    _OutboundTap,
    _pattern,
    _sentinel,
    smu_sep_out_filter_rule_matrix_test_seq,
)
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    _OUTPUT_REMAP_H,
    _SEP_ADDR_H,
    _SMC_ADDR_H,
    ADDR_MASK,
    AP_REGION_BASE,
    SMU_BASE,
    SMU_SIZE,
    STEE_REGION_BASE,
)

# hw/sys/sep/regs/gen/c/sep_addr.h: each output remap table has 16 regions and each window
# SEP_TOP_*_REGION_SIZE bytes, so one region spans the window size divided by the region count.
REGION_COUNT = c_header_u32(_SEP_ADDR_H, "SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_NUM")
WINDOW_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_AP_REGION_SIZE")
REGION_SIZE = WINDOW_SIZE // REGION_COUNT
SEP_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SIZE")
SMC_SIZE = c_header_u32(_SMC_ADDR_H, "SMC_TOP_SIZE")

# hw/ip/output_remap/regs/gen/c/output_remap.h REGION_ATTRS: valid bit and the 56-bit offset.
REMAP_VALID = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm"
)
REMAP_OFFSET_BM = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__OFFSET_bm"
)

# hw/ip/output_remap/regs/output_remap.rdl: offsets are region-granule aligned. The AP and STEE
# targets sit above 4 GiB, outside the SEP, SMC and SMU apertures and below 2^56, and differ per
# table and per region.
AP_TARGET_BASE = 0xA0_0000_0000
AP_TARGET_STRIDE = 0x20_0000
STEE_TARGET_BASE = 0x50_0000_0000
STEE_TARGET_STRIDE = 0x30_0000

# Word offset inside a region, below the 512 KiB granule that the remap keeps.
IN_REGION_OFFSET = 0x40
FIRST_REGION = 1
INVALID_REGION = 7
PASS_THROUGH_REGION = 0
VALID_WRITES = 2 * (REGION_COUNT - FIRST_REGION)
PASS_THROUGH_WRITES = 4
ACCESS_BUDGET = 74
TABLES = ("AP", "STEE")
STEPS = ("S1", "S2", "S3", "S4")
ACCESS_STEPS = STEPS[:-1]
_PATTERN_TAG = {"AP": 0x100, "STEE": 0x200}
_WINDOW = {"AP": AP_REGION_BASE, "STEE": STEE_REGION_BASE}
_TARGET = {"AP": (AP_TARGET_BASE, AP_TARGET_STRIDE), "STEE": (STEE_TARGET_BASE, STEE_TARGET_STRIDE)}
_CSR_SYMBOL = {
    "AP": "SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_BASE_ADDR",
    "STEE": "SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_BASE_ADDR",
}


def window_addr(table: str, region: int) -> int:
    return _WINDOW[table] + region * REGION_SIZE + IN_REGION_OFFSET


def offset_of(table: str, region: int) -> int:
    base, stride = _TARGET[table]
    return base + region * stride


def target_addr(table: str, region: int) -> int:
    return offset_of(table, region) + IN_REGION_OFFSET


def pattern_of(table: str, region: int) -> int:
    return _pattern(_PATTERN_TAG[table] + region, 8)


def _require_layout() -> None:
    targets = [offset_of(t, k) for t in TABLES for k in range(REGION_COUNT)]
    windows = [window_addr(t, k) for t in TABLES for k in range(REGION_COUNT)]
    sentinel = _sentinel(8)
    facts = (
        (REGION_SIZE == 1 << 19, "region granule"),
        (len(set(targets)) == len(targets), "distinct offsets"),
        (all(t % REGION_SIZE == 0 for t in targets), "granule-aligned offsets"),
        (all(t & ~REMAP_OFFSET_BM == 0 for t in targets), "offset field width"),
        (all(t >= 1 << 32 for t in targets), "targets above 4 GiB"),
        (all(not SMU_BASE <= t < SMU_BASE + SMU_SIZE for t in targets), "targets clear of the SMU"),
        (all(t >= SEP_SIZE for t in targets), "targets clear of the SEP"),
        (not set(targets) & set(windows), "targets apart from the windows"),
        (
            all(w % 8 == 0 for w in windows) and all(t % 8 == 0 for t in targets),
            "doubleword alignment",
        ),
        (
            len({pattern_of(t, k) for t in TABLES for k in range(REGION_COUNT)})
            == len(TABLES) * REGION_COUNT,
            "distinct patterns",
        ),
        (
            all(pattern_of(t, k) != sentinel for t in TABLES for k in range(REGION_COUNT)),
            "pattern against sentinel",
        ),
    )
    bad = [name for ok, name in facts if not ok]
    if bad:
        raise RuntimeError("SEP output remap region matrix layout: " + ", ".join(bad))


_require_layout()


class smu_sep_output_remap_region_matrix_test_seq(smu_sep_out_filter_rule_matrix_test_seq):
    """AP and STEE output remap regions programmed and probed over the debug module's bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.valid_done = 0
        self.valid_before_invalid: list[int] = []
        self.admit_before_valid = False

    async def _remap_csr(self, table: str, region: int, attrs: int) -> None:
        await self._bus_ok(_indexed_addr(_CSR_SYMBOL[table], region), SIZE_DOUBLEWORD, attrs)

    async def _write_window(self, table: str, region: int) -> tuple:
        """One doubleword write; returns (refused, AW addresses, AR addresses, held at window)."""
        addr = window_addr(table, region)
        mark = self.tap.mark()
        err, _ = await self._bus(addr, SIZE_DOUBLEWORD, pattern_of(table, region))
        if err == 0:
            await self._observe(mark, 1, 0)
        aw, ar = self.tap.since(mark)
        return err != 0, [a[0] for a in aw], [a[0] for a in ar], err

    def _held(self, addr: int) -> int:
        return self.mem.read_int(addr, 8)

    async def _s1(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        if not (self.s1_ok and self.s2_ok and self.s3_ok):
            raise AssertionError("debug module bring-up incomplete")
        self._site("posture_settle", POSTURE_SETTLE_POLLS, None, "not measured", "polls")
        self._site("dmi_retry", DMI_RETRIES, None, "not measured", "retries")
        smc_base = int(self.dut.smc_global_base_o.value)
        smc_span = (smc_base, smc_base + SMC_SIZE)
        targets = [offset_of(t, k) for t in TABLES for k in range(REGION_COUNT)]
        if any(smc_span[0] <= t < smc_span[1] for t in targets):
            raise AssertionError(f"a remap target lies in the SMC aperture {smc_span}")
        self.tap = _OutboundTap(self.dut)
        for entry, allow_ns in ((ADMIT_ENTRY_LOW, 0), (ADMIT_ENTRY_HIGH, 1)):
            await self._program(entry, 0, ADDR_MASK, _config(allow_ns))
        for table in TABLES:
            for k in range(REGION_COUNT):
                self.mem.write_int(target_addr(table, k), _sentinel(8), 8)
                self.mem.write_int(window_addr(table, k), _sentinel(8), 8)
        aw0, ar0 = self.tap.mark()
        self.admit_before_valid = self.accesses == 6
        self._log(
            f"OBSERVATION dmstatus_version={self.dmstatus & 0xF} smu_base=0x{SMU_BASE:x} "
            f"smc_aperture=0x{smc_span[0]:x}..0x{smc_span[1]:x} region_size=0x{REGION_SIZE:x} "
            f"responder counters at start aw={aw0} ar={ar0} budget={ACCESS_BUDGET}"
        )

    async def _s2(self, sb) -> None:
        legs: dict[str, dict[int, tuple]] = {t: {} for t in TABLES}
        cross: dict[int, tuple] = {}
        aw0, _ = self.tap.mark()
        for k in range(FIRST_REGION, REGION_COUNT):
            await self._remap_csr("AP", k, REMAP_VALID | offset_of("AP", k))
            await self._remap_csr("STEE", k, REMAP_VALID | offset_of("STEE", k))
            ap = await self._write_window("AP", k)
            stee_before = self._held(target_addr("STEE", k))
            stee = await self._write_window("STEE", k)
            ap_after = self._held(target_addr("AP", k))
            self.valid_done += 2
            legs["AP"][k] = ap
            legs["STEE"][k] = stee
            cross[k] = (stee_before, ap_after)
        aw_total = len(self.tap.aw) - aw0
        self._log(f"OBSERVATION sberror codes of the translated writes={sorted(self.error_codes)}")
        for table in TABLES:
            observed = {
                f"region {k}": (
                    legs[table][k][0],
                    legs[table][k][1],
                    legs[table][k][2],
                    self._held(target_addr(table, k)),
                    self._held(window_addr(table, k)),
                )
                for k in range(FIRST_REGION, REGION_COUNT)
            }
            expected = {
                f"region {k}": (
                    False,
                    [target_addr(table, k)],
                    [],
                    pattern_of(table, k),
                    _sentinel(8),
                )
                for k in range(FIRST_REGION, REGION_COUNT)
            }
            observed["AW handshakes of both tables"] = aw_total
            expected["AW handshakes of both tables"] = VALID_WRITES
            other = TABLES[1 - TABLES.index(table)]
            observed["other table's translated words after all writes"] = [
                self._held(target_addr(other, k)) == pattern_of(other, k)
                for k in range(FIRST_REGION, REGION_COUNT)
            ]
            expected["other table's translated words after all writes"] = [True] * (
                REGION_COUNT - FIRST_REGION
            )
            chk = f"CHK-SEPREMAP-{table}-REGIONS"
            self._log(
                f"{chk}: regions {FIRST_REGION}..{REGION_COUNT - 1} each land at their own offset "
                f"plus 0x{IN_REGION_OFFSET:x} observed={observed} expected={expected}"
            )
            sb.expect_eq(f"{chk} outcomes", observed, expected, evidence=chk)
        indep_observed = {
            f"region {k}": (
                legs["AP"][k][1] == [target_addr("AP", k)]
                and target_addr("STEE", k) not in legs["AP"][k][1],
                legs["STEE"][k][1] == [target_addr("STEE", k)]
                and target_addr("AP", k) not in legs["STEE"][k][1],
                cross[k][0],
                cross[k][1],
            )
            for k in range(FIRST_REGION, REGION_COUNT)
        }
        indep_expected = {
            f"region {k}": (True, True, _sentinel(8), pattern_of("AP", k))
            for k in range(FIRST_REGION, REGION_COUNT)
        }
        self._log(
            "CHK-SEPREMAP-TABLE-INDEP: with both tables programmed at the same region index and "
            "different offsets, each write lands at its own table's offset and the other table's "
            f"offset is untouched observed={indep_observed} expected={indep_expected}"
        )
        sb.expect_eq(
            "CHK-SEPREMAP-TABLE-INDEP outcomes",
            indep_observed,
            indep_expected,
            evidence="CHK-SEPREMAP-TABLE-INDEP",
        )

    async def _pass_through(self, table: str, region: int) -> tuple:
        addr = window_addr(table, region)
        self.mem.write_int(addr, _sentinel(8), 8)
        self.valid_before_invalid.append(self.valid_done)
        refused, aw, ar, err = await self._write_window(table, region)
        self._log(
            f"OBSERVATION {table} region {region} pass-through write 0x{addr:x}: "
            f"sberror={err} aw={[hex(a) for a in aw]}"
        )
        return refused, aw, ar, self._held(addr)

    async def _s3(self, sb) -> None:
        for table in TABLES:
            reset = await self._pass_through(table, PASS_THROUGH_REGION)
            await self._remap_csr(table, INVALID_REGION, offset_of(table, INVALID_REGION))
            cleared = await self._pass_through(table, INVALID_REGION)
            window_0 = window_addr(table, PASS_THROUGH_REGION)
            window_7 = window_addr(table, INVALID_REGION)
            observed = {
                "region 0 at reset": reset,
                f"region {INVALID_REGION} after valid cleared": cleared,
                "responder holds the unchanged-address words": (
                    self._held(window_0),
                    self._held(window_7),
                ),
                f"region {INVALID_REGION} valid leg of S2 (control)": self._held(
                    target_addr(table, INVALID_REGION)
                ),
            }
            expected = {
                "region 0 at reset": (
                    False,
                    [window_0],
                    [],
                    pattern_of(table, PASS_THROUGH_REGION),
                ),
                f"region {INVALID_REGION} after valid cleared": (
                    False,
                    [window_7],
                    [],
                    pattern_of(table, INVALID_REGION),
                ),
                "responder holds the unchanged-address words": (
                    pattern_of(table, PASS_THROUGH_REGION),
                    pattern_of(table, INVALID_REGION),
                ),
                f"region {INVALID_REGION} valid leg of S2 (control)": pattern_of(
                    table, INVALID_REGION
                ),
            }
            chk = f"CHK-SEPREMAP-{table}-INVALID"
            self._log(
                f"{chk}: the write at region 0 (never programmed) and at region {INVALID_REGION} "
                f"(valid cleared) land at their unchanged window addresses with sberror 0, against "
                f"the translated valid leg observed={observed} expected={expected}"
            )
            sb.expect_eq(f"{chk} outcomes", observed, expected, evidence=chk)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self._mark("S1", "SETUP: debug module, admit pair, responder sentinel, AW counter")
        try:
            await self._s1()
            await self._mark("S2", "regions 1 to 15 of the AP and STEE tables, interleaved")
            await self._s2(sb)
            await self._mark("S3", "region 0 and the invalidated region 7 pass through")
            await self._s3(sb)
            await self._mark("S4", "TIMEOUT: bounded waits and last state")
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
        before = self.valid_before_invalid
        self._log(
            f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; admit pair before the first "
            f"valid write={self.admit_before_valid}; valid writes {self.valid_done} of "
            f"{VALID_WRITES} done before each of the {len(before)} invalid-leg writes={before}; "
            f"system-bus accesses {self.accesses} of {ACCESS_BUDGET} ({counts})"
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence and access counts",
            (
                increasing,
                every_step,
                tally == self.accesses,
                self.accesses <= ACCESS_BUDGET,
                self.admit_before_valid,
                self.valid_done,
                before,
            ),
            (True, True, True, True, True, VALID_WRITES, [VALID_WRITES] * PASS_THROUGH_WRITES),
            evidence="CHK-NONVAC",
        )
