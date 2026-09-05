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

from sep_reg_meta import ENTROPY_SOURCE

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

PF_BIT = 16
ALERT_BIT = 10
ERR_BIT = 11
IRQ_AGG_IDX = 15  # PIC source 16
PF_MASK = 1 << PF_BIT
ALERT_MASK = 1 << ALERT_BIT
ERR_MASK = 1 << ERR_BIT
TRIP_WINDOW = 64
TRIP_THRESHOLD = 1

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
REPCNT_FAIL_MASK = ENTROPY_SOURCE.fields("ALERT_FAIL_COUNTS")["REPCNT_FAIL_COUNT"]["bm"]
REPCNT_FAIL_LSB = ENTROPY_SOURCE.fields("ALERT_FAIL_COUNTS")["REPCNT_FAIL_COUNT"]["bp"]
HEALTH_STATUS_MASK = ENTROPY_SOURCE.fields("HEALTH_TEST_STATUS")["HEALTH_STATUS"]["bm"]


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

    async def read_repcnt_fail_count(self) -> int:
        raw = await self._rd(ESRC_ALERT_FAIL_COUNTS)
        return (raw & REPCNT_FAIL_MASK) >> REPCNT_FAIL_LSB

    async def read_health_status(self) -> int:
        return (await self._rd(ESRC_HEALTH_TEST_STATUS)) & HEALTH_STATUS_MASK

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
