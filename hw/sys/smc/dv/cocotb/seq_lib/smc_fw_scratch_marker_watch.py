# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Second sequence that answers a firmware image's SCRATCH_1 handshake.

Some images park at a marker: they publish a word in CPU_CTRL SCRATCH_1 and
spin until the bench has done something (sampled a pin, driven the bus) and,
for the `tb_sync` images, acknowledged through SCRATCH_4. The boot contract's
`arm_value` hook watches SCRATCH_0 only and fires once, so these images need a
watcher of their own on SCRATCH_1.

This is a separate sequence started on the same SEP_IN sequencer as the boot
sequence; the sequencer arbitrates the two streams of CSR items, so the
verdict poll and the marker poll interleave without either seeing the other's
data. Handlers run inline: the firmware holds its state until the acknowledge
(or, for images without one, until the bench stimulus produces the effect it
is waiting for), so the observation window is as long as the handler takes.

Steps are expected in order. A marker that never appears leaves `handled`
short, and the firmware fails closed on its own bound, so the owner asserts
`handled` against the full marker list after the verdict rather than timing
the watcher itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_image_boot_seq import scratch_addr

# scratch[1] carries the marker and scratch[4] the acknowledge: the "Scratch
# register allocation" note in fw/include/smc_test.h and tb_sync() in
# fw/tests/i2c_acq_fifo_stretch_reset.
MARKER_SCRATCH = 1
ACK_SCRATCH = 4


@dataclass(frozen=True)
class MarkerStep:
    marker: int
    handler: Callable[[], Awaitable[None]]
    ack: int | None = None


class smc_fw_scratch_marker_watch(SmcCsrSeq):
    """Poll SCRATCH_1 for each marker in turn, run its handler, acknowledge."""

    def __init__(self, name: str, steps: list[MarkerStep], *, period_cycles: int = 2000) -> None:
        super().__init__(name)
        self.steps = list(steps)
        self.period_cycles = period_cycles
        self.handled: list[int] = []
        self.stop = False
        self.failure: Exception | None = None

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        marker_reg = scratch_addr(MARKER_SCRATCH)
        ack_reg = scratch_addr(ACK_SCRATCH)
        try:
            for step in self.steps:
                while not self.stop:
                    await ClockCycles(clk, self.period_cycles)
                    word = await self.csr_read("FW_MARKER_POLL", marker_reg)
                    if word != step.marker:
                        continue
                    cocotb.log.info(
                        "firmware marker 0x%08x in SCRATCH_%d; running the bench side",
                        word,
                        MARKER_SCRATCH,
                    )
                    await step.handler()
                    if step.ack is not None:
                        await self.csr_write("FW_MARKER_ACK", ack_reg, step.ack)
                    self.handled.append(step.marker)
                    break
                if self.stop:
                    return
        except Exception as exc:
            self.failure = exc
            raise
