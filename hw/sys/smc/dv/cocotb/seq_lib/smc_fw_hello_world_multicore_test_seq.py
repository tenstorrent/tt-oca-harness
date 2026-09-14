# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Four harts run hello_world_multicore; the bench reads the harts' own markers.

`fw/tests/hello_world_multicore` has hart 0 wait until the other three have
each added to a shared atomic counter, then post PASS under a lock; every
secondary hart first writes its hart id into SCRATCH[hartid]. hello_world
proves only hart 0's store (crt0 synchronises the harts before main, but a hart
that stalls after the barrier would not stop hello_world's hart 0). Here the
verdict depends on harts 1..3 releasing hart 0, and the bench then reads
SCRATCH_2 and SCRATCH_3 -- words hart 0 never writes -- expecting the hart ids
2 and 3.

SCRATCH_1 is not asserted: hart 0 rewrites it in its wait loop while hart 1 is
storing to it, so its final value is a race the image does not define. SCRATCH_2
is cleared before release because it doubles as the console/error word and
could hold a residue from an earlier test; SCRATCH_3 is the seed word, which the
boot contract overwrites before release with this run's RANDOM_SEED, so a 3 read
back afterwards can only have come from hart 3. A run whose seed is itself 3
could not tell the two apart, so the sequence refuses it before release.
"""

from __future__ import annotations

import os

import cocotb

from .smc_fw_image_boot_seq import scratch_addr, smc_fw_image_boot_seq

# other_main(): write_scratch(hartid, hartid) on harts 1..3; 2 and 3 are the
# two hart 0 leaves alone.
HART_MARKERS = {2: 2, 3: 3}


class smc_fw_hello_world_multicore_test_seq(smc_fw_image_boot_seq):
    """Boot the four-hart image, then read the hart markers back."""

    tag = "MULTICORE"
    # PASS landed 22 us after release in the reference run, i.e. ~43 polls at a
    # 5 ns clk_smc_i; 500 leaves >10x headroom for the lock init and the three
    # atomic check-ins across the cluster boundary.
    poll_iterations = 500

    def __init__(self, name: str = "smc_fw_hello_world_multicore_test_seq") -> None:
        super().__init__(name)
        self.hart_markers: dict[int, int] = {}
        self.hart_markers_ok = False

    async def before_boot(self) -> None:
        # The same value check_cpu_firmware_boot_contract publishes in SCRATCH_3.
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0) & 0xFFFF_FFFF
        assert seed != HART_MARKERS[3], (
            f"RANDOM_SEED={seed} equals hart 3's marker: the seed word published in "
            f"SCRATCH_3 before release would be indistinguishable from hart 3's write"
        )
        await self.csr_write("MULTICORE_SCRATCH2_CLEAR", scratch_addr(2), 0)
        await self.csr_read("MULTICORE_SCRATCH2_CLEAR_RB", scratch_addr(2), expected=0)

    async def after_pass(self) -> None:
        status = await self.csr_read("MULTICORE_SCRATCH1", scratch_addr(1))
        for hart, expected in HART_MARKERS.items():
            got = await self.csr_read(f"MULTICORE_HART{hart}_MARKER", scratch_addr(hart))
            self.hart_markers[hart] = got
            assert got == expected, (
                f"SCRATCH_{hart} = 0x{got:08x}, expected hart {hart}'s marker "
                f"{expected}: hart 0 posted PASS but hart {hart} did not run other_main()"
            )
        self.hart_markers_ok = True
        cocotb.log.info(
            "CHK-FW-MULTICORE-HART-MARKERS: SCRATCH_2=%d SCRATCH_3=%d (hart ids written by "
            "harts 2 and 3 themselves; SCRATCH_1=0x%08x is the racy hart-0/1 word, logged only)",
            self.hart_markers[2],
            self.hart_markers[3],
            status,
        )
