# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared-VIP wire checks and frame ledger on the SEP SPI host pads.

``SepSpiWireMonitor.start`` attaches ``OcahSpiMonitor`` to the approved SPI
host pad ports of ``tb_top`` (``spi_cs_n_o``, ``spi_sck_o``, ``spi_mosi_o``,
``spi_miso_i``, and the lane and output-enable taps ``spi_sd_o``,
``spi_sd_oe_o``, ``spi_cs_oe_o``, ``spi_sck_oe_o``; docs/SEP_TB_ARCH.adoc)
in Mode 0 and starts it. A leaf that
programs another SPI mode calls ``set_mode(cpol, cpha)`` before the CONFIGOPTS
write, so the monitor grades every later frame in that mode.

``finish`` stops the monitor; ``stop()`` raises on any wire-check
violation (SCK off its CPOL level at a chip-select edge or while chip select is
high, a driven lane changing on a sample edge or before the next shift edge,
X/Z, a data lane output enable on while chip select is high or in a pattern
other than none, lane 0, lanes 1:0 or lanes 3:0, the chip-select or clock
output enable off while chip select is low; the rules of
doc/integrator/src/smu-sep.adoc, "SEP SPI Host Pin Assignment"). It
then fails a mode the leaf lists with no graded frame, and logs::

    CHK-SPI-WIRE PASS seed=<n> frames=<n> per_mode=<mode>:<frames>,...

With a flash model attached it also fails any frame the model refused for its
shape (``FRAME_SHAPE_REASONS``: a phase ended early or bits after the
command's last one) and grades ``CHK-SPI-LEDGER``: every frame the monitor saw
is a flash record, in order, with the same command byte and input bit count.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from typing import Any

from ocah_spi_vip import FRAME_SHAPE_REASONS, OcahSpiFlash, OcahSpiFlashChecker, OcahSpiMonitor

__all__ = ["SepSpiWireMonitor"]

# The ledger needs every frame of the leaf; firmware status polls can be many.
_HISTORY = 1_000_000


class SepSpiWireMonitor:
    """``OcahSpiMonitor`` on the SEP SPI host pads with a per-mode frame tally."""

    def __init__(self, dut: Any, *, name: str = "sep_spi_wire_mon") -> None:
        self.monitor = OcahSpiMonitor(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            sd_out=dut.spi_sd_o,
            sd_oe=dut.spi_sd_oe_o,
            cs_oe=dut.spi_cs_oe_o,
            sck_oe=dut.spi_sck_oe_o,
            name=name,
            max_history=_HISTORY,
        )
        self.tally: Counter = Counter()
        self.monitor.add_transaction_callback(
            lambda txn: self.tally.update([(txn["cpol"], txn["cpha"])])
        )

    async def start(self) -> SepSpiWireMonitor:
        await self.monitor.start()
        return self

    def set_mode(self, cpol: int, cpha: int) -> None:
        """SPI mode of every frame that starts after this call; call it before CONFIGOPTS."""
        self.monitor.set_mode(cpol, cpha)

    async def finish(
        self,
        logger: logging.Logger,
        *,
        seed: int,
        modes: Iterable[tuple[int, int]] = ((0, 0),),
        flash: OcahSpiFlash | None = None,
    ) -> None:
        """Stop the monitor and grade the wire checks, the modes, and the flash ledger."""
        await self.monitor.stop()
        per_mode = ",".join(f"{p}{h}:{n}" for (p, h), n in sorted(self.tally.items()))
        line = f"seed={seed} frames={sum(self.tally.values())} per_mode={per_mode or '-'}"
        graded = {mode for mode, count in self.tally.items() if count}
        ungraded = sorted({(p & 1, h & 1) for p, h in modes} - graded)
        if ungraded:
            raise AssertionError(
                f"CHK-SPI-WIRE FAIL {line} programmed_modes_without_frames={ungraded}"
            )
        logger.info("CHK-SPI-WIRE PASS %s wire_errors=0", line)
        if flash is None:
            return
        records = flash.get_transactions()
        refused = [
            (i, r["opcode"], r["reason"])
            for i, r in enumerate(records)
            if r["reason"] in FRAME_SHAPE_REASONS
        ]
        if refused:
            raise AssertionError(
                f"CHK-SPI-FRAME-SHAPE FAIL seed={seed} frames={len(records)} refused={refused[:5]}"
            )
        logger.info("CHK-SPI-FRAME-SHAPE PASS seed=%d frames=%d refused=0", seed, len(records))
        checker = OcahSpiFlashChecker(name="sep_spi_ledger", flash=flash, logger=logger)
        checker.check_ledger(self.monitor.get_transactions(), records, context=f"seed={seed}")
        checker.finalize()
