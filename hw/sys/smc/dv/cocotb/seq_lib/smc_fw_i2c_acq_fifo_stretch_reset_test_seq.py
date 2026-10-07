# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""i2c_acq_fifo_stretch_reset with the bench sampling the target's SCL driver.

`fw/tests/i2c_acq_fifo_stretch_reset` runs I2C_1 as controller into I2C_0 as
target, offers a 70-byte write the target cannot absorb without service, waits
for STATUS.ACQFULL, resets the ACQ FIFO to release the stretch, recovers the
abandoned write and then receives and compares a 4-byte write. The stretch
itself is a duration on SCL that no register reports, so the image parks twice
-- SCRATCH_1 = 0x31 while the FIFO is full, 0x32 after the ACQ reset and the
recovery -- and waits for SCRATCH_4 = 0xC10A each time.

The watcher answers both. At 0x31 it samples tb_i2c0_scl_dut_low, the
open-drain pull of I2C_0 alone, across a window of ~20 SCL periods. A target
never drives SCL except to stretch, and the FSM enters STRETCH_ACQ_FULL at the
ACK phase of the byte in flight when STATUS.ACQFULL asserts, so the window may
open on that byte's last clocks; what is required is that the pull is asserted
for a contiguous span far longer than any clock-low phase and is still asserted,
with SCL low, over the whole final quarter of the window: the target, not the
controller, is holding the clock. At 0x32 it requires the same pull absent
throughout -- the controller may still be clocking the line while it finishes
the recovery of the abandoned write, so the resolved SCL is reported, not
required idle -- and reads the ACQ levels the firmware published in
SCRATCH_5/6: non-zero before the reset, zero after. Only then is the
acknowledge written, so the firmware cannot run past either window.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_fw_i2c_pair_test_seq import smc_fw_i2c_pair_test_seq
from .smc_fw_image_boot_seq import scratch_addr
from .smc_fw_scratch_marker_watch import MarkerStep, smc_fw_scratch_marker_watch

# SCR_STRETCH_OBS / SCR_RELEASE_OBS / SCR_TB_ACK in the image.
STRETCH_MARKER = 0x31
RELEASE_MARKER = 0x32
TB_ACK = 0xC10A
TARGET_ADDR = 0x10
# The verify write the image sends after the recovery, as its driver puts it on
# the wire: a length header, then the bytes the image compares on receipt.
VERIFY_WRITE_BYTES = (0xA5, 0x5A, 0xC3, 0x3C)
VERIFY_WRITE_FRAME = (len(VERIFY_WRITE_BYTES), *VERIFY_WRITE_BYTES)

# Standard mode off the periph clock is ~10 us per SCL period; the window
# spans ~20 periods. The firmware publishes the controller's programmed
# TIMING0.TLOW in SCRATCH_6 at the stretch marker, and a contiguous target pull
# has to outlast STRETCH_TLOW_MULTIPLE of those clock-low phases, so it cannot
# be a running clock. A pull covering the whole final quarter (~50 us) cannot be
# the tail of the byte that was in flight when the marker was published. The
# window is in time, not clk_smc_i cycles, so it holds at every sys-clock period.
WINDOW_NS = 200_000
SAMPLE_EVERY_NS = 250
STRETCH_TLOW_MULTIPLE = 4
TAIL_FRACTION = 4


class smc_fw_i2c_acq_fifo_stretch_reset_test_seq(smc_fw_i2c_pair_test_seq):
    """Boot the ACQ-stretch image and observe the two SCL windows it holds open."""

    tag = "I2C-ACQ-STRETCH"
    # PASS lands 7.6 ms after release at the 10 ns clk_smc_i the testlist runs
    # this leaf at (~7,600 polls): the ~62-byte fill to ACQFULL, two bench
    # windows, the recovery and the 4-byte write. 100_000 is ~13x that.
    poll_iterations = 100_000
    # The wire is graded in after_pass against the verify frame itself.
    floors = ()

    def __init__(self, name: str = "smc_fw_i2c_acq_fifo_stretch_reset_test_seq") -> None:
        super().__init__(name)
        self.watch: smc_fw_scratch_marker_watch | None = None
        self._watch_task = None
        self.stretch_ok = False
        self.release_ok = False

    async def before_boot(self) -> None:
        await super().before_boot()
        self.watch = smc_fw_scratch_marker_watch(
            "fw_i2c_acq_stretch_watch",
            [
                MarkerStep(STRETCH_MARKER, self._observe_stretch, ack=TB_ACK),
                MarkerStep(RELEASE_MARKER, self._observe_release, ack=TB_ACK),
            ],
        )
        self.watch.cfg = self.cfg
        self.watch.env = self.env
        self._watch_task = cocotb.start_soon(self.watch.start(self.sequencer))

    async def _sample_target_scl(self) -> tuple[list[int], list[int]]:
        """Sample (I2C_0 pulling SCL low, resolved SCL) every SAMPLE_EVERY_NS."""
        dut = cocotb.top
        pulled: list[int] = []
        scl: list[int] = []
        sample_cycles = max(1, round(SAMPLE_EVERY_NS / self.cfg.smc_clk_period_ns))
        for _ in range(WINDOW_NS // SAMPLE_EVERY_NS):
            await ClockCycles(dut.clk_smc_i, sample_cycles)
            pulled.append(int(dut.tb_i2c0_scl_dut_low.value))
            scl.append(int(dut.tb_i2c0_scl.value))
        return pulled, scl

    @staticmethod
    def _longest_run(samples: list[int]) -> int:
        best = run = 0
        for s in samples:
            run = run + 1 if s else 0
            best = max(best, run)
        return best

    async def _observe_stretch(self) -> None:
        acq_level = await self.csr_read("ACQ_STRETCH_LEVEL", scratch_addr(5))
        tlow = await self.csr_read("CONTROLLER_TLOW", scratch_addr(6))
        assert tlow > 0, f"firmware published TIMING0.TLOW {tlow} at the stretch marker"
        min_stretch_ns = STRETCH_TLOW_MULTIPLE * tlow * self.cfg.periph_clk_period_ns
        pulled, scl = await self._sample_target_scl()
        n = len(pulled)
        tail = n // TAIL_FRACTION
        sample_ns = SAMPLE_EVERY_NS
        longest_ns = self._longest_run(pulled) * sample_ns
        tail_pulled = sum(pulled[-tail:])
        tail_high = sum(scl[-tail:])
        assert longest_ns >= min_stretch_ns and tail_pulled == tail and tail_high == 0, (
            f"during the ACQ-full window I2C_0's longest continuous SCL pull was "
            f"{longest_ns} ns (need >= {min_stretch_ns:g}, {STRETCH_TLOW_MULTIPLE} x TLOW "
            f"{tlow} periph cycles); over the final {tail} samples it pulled in "
            f"{tail_pulled} and SCL was high in {tail_high}: the target is not holding the "
            f"clock"
        )
        assert acq_level > 0, f"firmware published ACQ level {acq_level} at the stretch marker"
        self.stretch_ok = True
        cocotb.log.info(
            "CHK-FW-I2C-ACQ-STRETCH-SCL: tb_i2c0_scl_dut_low asserted in %d/%d samples over %d "
            "ns, longest continuous pull %d ns (>= %g, %d x the published TIMING0.TLOW of %d "
            "periph cycles), asserted with SCL low through the final %d samples; firmware "
            "ACQ level %d: the target holds SCL",
            sum(pulled),
            n,
            WINDOW_NS,
            longest_ns,
            min_stretch_ns,
            STRETCH_TLOW_MULTIPLE,
            tlow,
            tail,
            acq_level,
        )

    async def _observe_release(self) -> None:
        before = await self.csr_read("ACQ_LEVEL_BEFORE_RESET", scratch_addr(5))
        after = await self.csr_read("ACQ_LEVEL_AFTER_RESET", scratch_addr(6))
        pulled_s, scl_s = await self._sample_target_scl()
        samples, pulled, high = len(pulled_s), sum(pulled_s), sum(scl_s)
        assert pulled == 0, (
            f"after the ACQ reset I2C_0 still pulled SCL low in {pulled}/{samples} samples "
            f"(SCL high in {high}): the stretch did not release"
        )
        assert before > 0 and after == 0, (
            f"firmware published ACQ level before/after reset = {before}/{after}; "
            f"expected non-zero then zero"
        )
        self.release_ok = True
        cocotb.log.info(
            "CHK-FW-I2C-ACQ-RELEASE-SCL: tb_i2c0_scl_dut_low released in %d/%d samples over %d "
            "ns (resolved SCL high in %d, the controller's own clocking); ACQ level "
            "%d -> %d across the reset",
            samples - pulled,
            samples,
            WINDOW_NS,
            high,
            before,
            after,
        )

    async def after_pass(self) -> None:
        assert self.watch is not None and self._watch_task is not None
        self.watch.stop = True
        await self._watch_task
        assert self.watch.handled == [STRETCH_MARKER, RELEASE_MARKER], (
            f"bench windows handled={self.watch.handled}; expected both "
            f"0x{STRETCH_MARKER:x} and 0x{RELEASE_MARKER:x}"
        )
        await super().after_pass()
        assert self.wire is not None
        writes = [f for f in self.wire.frames_to(TARGET_ADDR, read=False) if f.addr_acked]
        assert writes, (
            f"no acknowledged write frame to 0x{TARGET_ADDR:02x} decoded on tb_i2c0_scl/sda; "
            f"{self.wire.summary()}"
        )
        last = writes[-1]
        payload = tuple(b for b, _ in last.data)
        assert payload == VERIFY_WRITE_FRAME and all(a for _, a in last.data), (
            f"the last acknowledged write frame to 0x{TARGET_ADDR:02x} carried {last}; the "
            f"verify write after the recovery is "
            f"{' '.join(f'{b:02x}' for b in VERIFY_WRITE_FRAME)}, every byte acknowledged"
        )
        cocotb.log.info(
            "CHK-FW-I2C-WIRE-TRAFFIC: the last of %d acknowledged write frames to 0x%02x "
            "decoded on tb_i2c0_scl/sda is the verify write, %s, every byte acknowledged by "
            "the target",
            len(writes),
            TARGET_ADDR,
            " ".join(f"{b:02x}" for b in payload),
        )
