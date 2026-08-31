# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC persistent-failure alert delivery driver.

Directed. A short health-test window plus stuck forced noise trips
``ALERT_THRESHOLD`` so ``MAIN_SM_STATUS.ALERT`` and
``INTR_STATUS.PERSISTENT_FAILURE`` assert and reach PIC source 16.
Health-test *quality* is out of scope.
"""

from __future__ import annotations

from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    DECOR_CTRL_DIV8,
    ESRC_ALERT_THRESHOLD,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_MAIN_SM_STATUS,
    ESRC_RING_OSC_ENABLE,
    RING_OSC_ALL_ON,
)

PF_BIT = 16
ALERT_BIT = 10
IRQ_AGG_IDX = 15  # PIC source 16
PF_MASK = 1 << PF_BIT
ALERT_MASK = 1 << ALERT_BIT
TRIP_WINDOW = 64
TRIP_THRESHOLD = 1


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
