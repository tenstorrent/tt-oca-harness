# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC persistent-failure alert delivery driver.

Directed. A short health-test window plus stuck forced noise trips
``ALERT_THRESHOLD`` so ``MAIN_SM_STATUS.ALERT`` and
``INTR_STATUS.PERSISTENT_FAILURE`` assert and reach PIC source 16.
Health-test *quality* is out of scope.

The same trip is used to read the alert bookkeeping the RDL defines:
``ALERT_SUMMARY_FAIL_COUNTS.ANY_FAIL_COUNT`` is denominated in failing
*windows* rather than failure events, ``ALERT_FAIL_COUNTS`` attributes the
failure to a per-test lane, and ``HEALTH_TEST_STATUS.HEALTH_STATUS`` latches
which tests failed. ``INTR_TEST`` drives each interrupt source independently of
any real failure, which is what makes the aggregate slot provable per source.
"""

from __future__ import annotations

from sep_reg_meta import ENTROPY_SOURCE, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    DECOR_CTRL_DIV8,
    ESRC_ALERT_FAIL_COUNTS,
    ESRC_ALERT_SUMMARY_FAIL_COUNTS,
    ESRC_ALERT_THRESHOLD,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_STATUS,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_INTR_TEST,
    ESRC_MAIN_SM_STATUS,
    ESRC_RING_OSC_ENABLE,
    RING_OSC_ALL_ON,
)

# Field masks come from the generated entropy_source export, like the addresses
# and encodings in this file; a field that moves in the RDL moves these with it.
PF_MASK = ENTROPY_SOURCE.fields("INTR_STATUS")["PERSISTENT_FAILURE"]["bm"]
ALERT_MASK = ENTROPY_SOURCE.fields("MAIN_SM_STATUS")["ALERT"]["bm"]
ERR_MASK = ENTROPY_SOURCE.fields("MAIN_SM_STATUS")["ERR"]["bm"]
PF_BIT = PF_MASK.bit_length() - 1
ALERT_BIT = ALERT_MASK.bit_length() - 1
ERR_BIT = ERR_MASK.bit_length() - 1
# Aggregator slot, not an RDL CSR field: no symbol exists for it.
IRQ_AGG_IDX = 15  # PIC source 16
TRIP_WINDOW = 64
# Three failing windows, not one. At a threshold of one the alert comparator
# (entropy_source.sv: alert_thresh_fail = ANY_FAIL_COUNT >= THRESHOLD) already
# implies ANY_FAIL_COUNT >= 1, so the counter check could not fail on its own,
# and no denomination -- windows, per-test pulses, or per-lane events -- is
# distinguishable at a count of one.
TRIP_THRESHOLD = 3
# Windows keep accumulating between the trip and the poll that observes it, so
# the upper bound carries slack. It stays far below the per-test pulse rate the
# same run produces, which is what rejects a counter denominated in events.
ANY_FAIL_SLACK = 8

# entropy_source.rdl INTR_TEST: every source the register defines, each a
# write-one-to-pulse singlepulse field. Taken from the generated export so a
# source added or dropped in the RDL changes the sweep rather than passing
# silently.
INTR_SOURCES = tuple(
    sorted(
        ((name, meta["bm"]) for name, meta in ENTROPY_SOURCE.fields("INTR_TEST").items()),
        key=lambda item: item[1],
    )
)
# entropy_source.rdl defines eight INTR_TEST sources. The literal is the contract
# with the RDL: if a source is added or dropped there, this raises at import
# rather than letting the sweep silently cover a different set.
assert len(INTR_SOURCES) == 8, (
    f"entropy_source.rdl INTR_TEST defines {len(INTR_SOURCES)} sources, expected 8: "
    f"{[n for n, _ in INTR_SOURCES]}"
)
ANY_FAIL_MASK = ENTROPY_SOURCE.fields("ALERT_SUMMARY_FAIL_COUNTS")["ANY_FAIL_COUNT"]["bm"]
HEALTH_STATUS_MASK = ENTROPY_SOURCE.fields("HEALTH_TEST_STATUS")["HEALTH_STATUS"]["bm"]

# entropy_source.rdl HEALTH_TEST_STATUS: "repetition [0], APT high or low [3],
# Markov high [4], and Markov low [5]". The generator-status registers carry the
# same allocation. Bits 1:2 and 6:7 are reserved and must never latch.
HEALTH_LANE_MASK = (1 << 0) | (1 << 3) | (1 << 4) | (1 << 5)
HEALTH_RSVD_MASK = HEALTH_STATUS_MASK & ~HEALTH_LANE_MASK

# The five per-lane fail counters. Each pair counts one pulse twice: a 32-bit
# total cleared by health_test_clr, and a 4-bit alert counter cleared by
# alert_cntrs_clr (entropy_source.sv u_entropy_src_cntr_reg_* instances). Two
# different widths and two different clears off one event, so comparing them is
# a DUT-to-DUT contract rather than a restatement.
FAIL_LANES = ("REPCNT", "APT_HI", "APT_LO", "MARKOV_HI", "MARKOV_LO")
TOTAL_FAILS_ADDR = {lane: sym(f"ENTROPY_SOURCE_{lane}_TOTAL_FAILS_REG_ADDR") for lane in FAIL_LANES}
ALERT_FAIL_FIELD = {lane: f"{lane}_FAIL_COUNT" for lane in FAIL_LANES}

# entropy_source.rdl instantiates one health-status register per generator.
GENERATOR_HEALTH_ADDR = tuple(
    sym(f"ENTROPY_SOURCE_GENERATOR_{n}_HEALTH_STATUS_REG_ADDR") for n in range(12)
)
assert len(GENERATOR_HEALTH_ADDR) == 12


class SepEsrcAlert(SepAxiRegDriver):
    """CPU-LSU driver for the persistent-failure trip and W1C path."""

    _DRIVER_TAG = "ESRC"

    async def read_intr(self) -> int:
        return await self._rd(ESRC_INTR_STATUS)

    async def read_main_sm(self) -> int:
        return await self._rd(ESRC_MAIN_SM_STATUS)

    async def enable_persistent_irq(self) -> None:
        await self._wr(ESRC_INTR_ENABLE, PF_MASK)

    async def arm_failing_windows(self) -> None:
        await self._wr(ESRC_ALERT_THRESHOLD, TRIP_THRESHOLD)
        await self._wr(ESRC_HEALTH_TEST_WINDOW_SIZE, TRIP_WINDOW)
        await self._wr(
            ESRC_HEALTH_TEST_CTRL,
            ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0x7, REPETITION_LIMIT=5),
        )
        await self._wr(ESRC_DECORRELATOR_CTRL, DECOR_CTRL_DIV8)
        await self._wr(ESRC_RING_OSC_ENABLE, RING_OSC_ALL_ON)

    async def leave_alert_hang(self) -> None:
        await self._wr(
            ESRC_CTRL,
            ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0),
        )

    async def w1c_alert(self) -> None:
        await self._wr(ESRC_INTR_STATUS, PF_MASK)
        await self._wr(ESRC_MAIN_SM_STATUS, ALERT_MASK)

    async def read_any_fail_count(self) -> int:
        return (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & ANY_FAIL_MASK

    async def read_health_status(self) -> int:
        return (await self._rd(ESRC_HEALTH_TEST_STATUS)) & HEALTH_STATUS_MASK

    async def read_total_fails(self) -> dict[str, int]:
        """The five 32-bit per-lane totals, counted since MODULE_ENABLE rose."""
        return {lane: await self._rd(addr) for lane, addr in TOTAL_FAILS_ADDR.items()}

    async def read_alert_fail_counts(self) -> dict[str, int]:
        """The five 4-bit per-lane alert counters, from one ALERT_FAIL_COUNTS read."""
        raw = await self._rd(ESRC_ALERT_FAIL_COUNTS)
        out = {}
        for lane, field in ALERT_FAIL_FIELD.items():
            meta = ENTROPY_SOURCE.fields("ALERT_FAIL_COUNTS")[field]
            out[lane] = (raw & meta["bm"]) >> meta["bp"]
        return out

    async def read_generator_health(self) -> list[int]:
        """The twelve per-generator latched health-status bytes."""
        return [(await self._rd(addr)) & 0xFF for addr in GENERATOR_HEALTH_ADDR]

    async def disable_health_tests(self) -> None:
        """Clear HEALTH_TEST_CTRL.ENABLE so no test can re-latch HEALTH_STATUS.

        The per-test fail signals are cleared by ENABLE, not by MODULE_ENABLE, and
        HEALTH_TEST_STATUS.next is driven from them every cycle, so a W1C while a
        test is still failing is undone in the same window.
        """
        await self._wr(
            ESRC_HEALTH_TEST_CTRL,
            ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0),
        )

    async def w1c_health_status(self, value: int) -> None:
        await self._wr(ESRC_HEALTH_TEST_STATUS, value)

    async def enable_all_irq(self) -> None:
        """Enable every INTR_TEST-drivable source so each can reach the aggregate."""
        await self._wr(ESRC_INTR_ENABLE, sum(bm for _, bm in INTR_SOURCES))

    async def pulse_intr_test(self, mask: int) -> None:
        await self._wr(ESRC_INTR_TEST, mask)

    async def w1c_intr_status(self, mask: int) -> None:
        await self._wr(ESRC_INTR_STATUS, mask)
