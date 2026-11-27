# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI Run-Test/Idle cycles across TCK and system clock ratios.

Each pass retimes the system clock into one band of TCK-to-system-clock
ratio, taken in a seeded order: near 1, 1.25 to 3, 3 to 12, and above 12
with the system clock at 10 ns or slower. The system clock stays faster than
TCK, and a band the run's TCK period cannot reach is skipped. On each bridge,
in a seeded order, the pass then probes a DMI operation at every distance
from the shortest the TAP allows to DTP_DMI_SETTLE_TCK + 2, in a seeded
order. A distance counts TCK cycles from the one that leaves the operation's
Update-DR. A read of sbaddress0 is probed by the capture of the next DMI
scan, chained from Update-DR at two cycles and from Run-Test/Idle beyond. A
write of sbaddress0 is probed by the update of a scan that shifts no bit,
two cycles after that scan's capture, and the status it left is read after
the bench's idle cycles. A probe within DTP_DMI_BUSY_TCK cycles reads busy and
one DTP_DMI_SETTLE_TCK cycles or more after reads 0; between the two the
bridge model accepts either. Each probe ends with an op-3 scan that leaves
status 0 and the written value in the DMI register, so the next scan's
capture shows the read data. Each bridge then makes a bus write and a bus
read at the pass's ratio, and the pass restores the drawn system clock
period with every bridge idle.
"""

from __future__ import annotations

import random
from itertools import zip_longest

from env.dtp_types import (
    DMI_LEN,
    DTP_DMI_BUSY_TCK,
    DTP_DMI_SETTLE_TCK,
    DTP_EXPECTED_DTMCS,
    JTAG2AXI_TARGETS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
    unpack_dtmcs,
)
from ocah_lib import OcahKnobs, OcahRng

from .dtp_jtag2axi_base_test_seq import RAW_SCAN_IDLE_TCK, dtp_jtag2axi_base_test_seq

IDLE_CHECK_ID = "CHK-J2A-IDLE"
IDLE_NEGATIVE_KNOB = "DTP_J2A_IDLE_NEGATIVE"
# Shortest probe distances: a scan chained from Update-DR captures two TCK cycles after it,
# and a scan that shifts no bit updates two cycles after its capture.
CAPTURE_MIN_TCK = 2
UPDATE_MIN_TCK = 4
PROBE_MAX_TCK = DTP_DMI_SETTLE_TCK + 2
SYS_CLK_MIN_NS = 10
# System clock cycles between a retime and the next scan.
RETIME_SETTLE_CYCLES = 16
BAND_NAMES = ("near 1", "1.25 to 3", "3 to 12", "above 12")

_OK = DtpDmiStatus.SUCCESS
_BUSY = DtpDmiStatus.BUSY
_SBADDRESS0 = int(DtpDmReg.SBADDRESS0)


def band_periods(band: int, tck_ns: int) -> tuple[int, int]:
    """The lowest and highest even system clock periods that put the TCK-to-system-clock
    ratio in ``band``; the lowest is above the highest when the TCK period cannot reach it."""
    edges = (
        tck_ns,
        2 * -(-4 * tck_ns // 10),
        2 * -(-tck_ns // 6),
        2 * -(-tck_ns // 24),
        SYS_CLK_MIN_NS,
    )
    return max(edges[band + 1], SYS_CLK_MIN_NS), edges[band] - 2


def band_order(seed: int) -> list[int]:
    """The bands in the order the run's seed gives them, the same in both realizations."""
    index = OcahRng.salted_seed(seed, "clock_ratio_bands") % 24
    bands = list(range(len(BAND_NAMES)))
    order = []
    for radix in (6, 2, 1, 1):
        order.append(bands.pop(index // radix))
        index %= radix
    return order


class dtp_jtag2axi_clock_ratio_test_seq(dtp_jtag2axi_base_test_seq):
    """DMI reads and writes probed at every distance up to past the settle bound, on each
    bridge, at a system clock retimed into the pass's ratio band."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_clock_ratio_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        # The address and data the bridge's DMI register holds, with status 0.
        self._dmi_value = 0

    async def body(self) -> None:
        self.log_banner("JTAG2AXI Run-Test/Idle cycles across clock ratios")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("clock_ratio")
        drawn = self.cfg.sys_clk_period_ns
        band, period = self.pass_period(rng)
        self.log.info(
            "Ratio band %s: TCK %d ns, system clock %d ns retimed to %d ns",
            BAND_NAMES[band],
            self.cfg.jtag_period_ns,
            drawn,
            period,
        )
        await self.retime(period)
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            ctx = f"{target}.ratio_{band}"
            await self.sweep(target, rng, ctx)
            for read in (False, True):
                await self.port_access(target, rng, read=read, check_id=IDLE_CHECK_ID, ctx=ctx)
        await self.retime(drawn)

    def pass_period(self, rng: random.Random) -> tuple[int, int]:
        """The pass's band, from the run's seeded order of the bands its TCK period reaches,
        and a seeded even system clock period inside it."""
        tck_ns = self.cfg.jtag_period_ns
        order = band_order(self.scenario_seed - self.loop_index)
        reachable = [b for b in order if band_periods(b, tck_ns)[0] <= band_periods(b, tck_ns)[1]]
        band = reachable[self.loop_index % len(reachable)]
        low, high = band_periods(band, tck_ns)
        return band, 2 * rng.randint(low // 2, high // 2)

    async def retime(self, period_ns: int) -> None:
        """Give the system clock ``period_ns``; every bridge is idle."""
        await self.cfg.tb_if.retime_clk(period_ns)
        self.cfg.sys_clk_period_ns = period_ns
        await self.wait_sys_cycles(RETIME_SETTLE_CYCLES)

    async def sweep(self, target: str, rng: random.Random, ctx: str) -> None:
        """Probe a write and a read at every distance, each kind in its own seeded order;
        ``CHK-J2A-IDLE`` judges the probes at and beyond the two bounds."""
        await self.activate_dm(target)
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbaccess=self.target_cfg(target).data_size),
            context=f"{ctx}.sbcs",
        )
        self._dmi_value = self.random_sbaddress0(target, rng)
        await self.dmi_write(target, DtpDmReg.SBADDRESS0, self._dmi_value, context=f"{ctx}.setup")
        await self.select_dmi(target)
        reads = list(range(CAPTURE_MIN_TCK, PROBE_MAX_TCK + 1))
        writes = list(range(UPDATE_MIN_TCK, PROBE_MAX_TCK + 1))
        rng.shuffle(reads)
        rng.shuffle(writes)
        outcomes: dict[str, dict[int, DtpDmiStatus]] = {"read": {}, "write": {}}
        for read, write in zip_longest(reads, writes):
            if write is not None:
                value = self.random_sbaddress0(target, rng)
                status = await self.write_probe(target, value, write, ctx=f"{ctx}.write@{write}")
                outcomes["write"][write] = status
            if read is not None:
                status = await self.read_probe(target, read, rng, ctx=f"{ctx}.read@{read}")
                outcomes["read"][read] = status
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.NOP,
            status=_OK,
            expect=(_SBADDRESS0, self._dmi_value),
            context=f"{ctx}.last",
        )
        self.check_bounds(target, outcomes, ctx)

    async def write_probe(
        self, target: str, value: int, distance: int, *, ctx: str
    ) -> DtpDmiStatus:
        """Write ``value`` to sbaddress0 and update a scan that shifts no bit ``distance`` TCK
        cycles later; the status that update left."""
        chain = distance == UPDATE_MIN_TCK
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            value,
            DtpDmiOp.WRITE,
            status=_OK,
            chain=chain,
            expect=(_SBADDRESS0, self._dmi_value),
            context=ctx,
        )
        if not chain:
            await self.run_test_idle(distance - UPDATE_MIN_TCK - 1)
            await self.tms_step(1)
        await self.dmi_zero_shift()
        await self.run_test_idle()
        self._dmi_value = value
        return await self.clear_scan(target, busy_data=value, ctx=f"{ctx}.status")

    async def read_probe(
        self, target: str, distance: int, rng: random.Random, *, ctx: str
    ) -> DtpDmiStatus:
        """Read sbaddress0 and capture the next DMI scan ``distance`` TCK cycles later; the
        status that capture shows."""
        op_data = self.random_distinct_word(rng, target, self._dmi_value) & 0xFFFF_FFFF
        chain = distance == CAPTURE_MIN_TCK
        await self.dmi_raw(
            target,
            _SBADDRESS0,
            op_data,
            DtpDmiOp.READ,
            status=_OK,
            chain=chain,
            expect=(_SBADDRESS0, self._dmi_value),
            context=ctx,
        )
        if not chain:
            await self.run_test_idle(distance - CAPTURE_MIN_TCK - 1)
        return await self.clear_scan(target, busy_data=op_data, ctx=f"{ctx}.capture")

    async def clear_scan(self, target: str, *, busy_data: int, ctx: str) -> DtpDmiStatus:
        """A DMI scan whose update is op 3 of sbaddress0 and the written value, which leaves
        status 0 and that address and data whichever status it captured. Returns the captured
        status, judging the captured data: ``busy_data`` with busy, the written value
        otherwise."""
        item = await self.shift_dr(pack_dmi(_SBADDRESS0, self._dmi_value, DtpDmiOp.CLEAR), DMI_LEN)
        address, data, status = unpack_dmi(item.result)
        expected = busy_data if status == _BUSY else self._dmi_value
        self.check_dtm_capture(
            target,
            pack_dmi(address, data, 0) >> 2,
            pack_dmi(_SBADDRESS0, expected, 0) >> 2,
            context=f"{ctx} status={status}",
        )
        return DtpDmiStatus(status)

    def check_bounds(
        self, target: str, outcomes: dict[str, dict[int, DtpDmiStatus]], ctx: str
    ) -> None:
        """``CHK-J2A-IDLE``: every probe within DTP_DMI_BUSY_TCK reads busy and every probe
        DTP_DMI_SETTLE_TCK or more after reads 0, a bound the bench's idle cycles exceed.

        ``DTP_J2A_IDLE_NEGATIVE=1`` expects 0 from the shortest probe, so the run must fail.
        """
        negative = OcahKnobs.is_set(IDLE_NEGATIVE_KNOB)
        evidence = self.target_evidence(target)
        self.check_equal(
            evidence,
            IDLE_CHECK_ID,
            DTP_DMI_SETTLE_TCK < RAW_SCAN_IDLE_TCK,
            True,
            context=f"{ctx} settle={DTP_DMI_SETTLE_TCK} below idle={RAW_SCAN_IDLE_TCK} TCK",
        )
        shortest = {"read": CAPTURE_MIN_TCK, "write": UPDATE_MIN_TCK}
        for kind, statuses in outcomes.items():
            for distance in sorted(statuses):
                if DTP_DMI_BUSY_TCK < distance < DTP_DMI_SETTLE_TCK:
                    continue
                expected = _BUSY if distance <= DTP_DMI_BUSY_TCK else _OK
                if negative and distance == shortest[kind]:
                    expected = _OK
                self.check_equal(
                    evidence,
                    IDLE_CHECK_ID,
                    int(statuses[distance]),
                    int(expected),
                    context=f"{ctx} target={target} {kind} probed {distance} TCK after update",
                )
        complete = {
            kind: min((d for d, s in statuses.items() if s == _OK), default=None)
            for kind, statuses in outcomes.items()
        }
        self.log_summary(
            f"{target} Run-Test/Idle at TCK {self.cfg.jtag_period_ns} ns, "
            f"system clock {self.cfg.sys_clk_period_ns} ns",
            read_complete_from_rti=None
            if complete["read"] is None
            else complete["read"] - CAPTURE_MIN_TCK,
            write_complete_from_rti=None
            if complete["write"] is None
            else complete["write"] - UPDATE_MIN_TCK,
            dtmcs_idle=unpack_dtmcs(DTP_EXPECTED_DTMCS)["idle"],
            read_busy=sorted(d for d, s in outcomes["read"].items() if s == _BUSY),
            write_busy=sorted(d for d, s in outcomes["write"].items() if s == _BUSY),
        )
