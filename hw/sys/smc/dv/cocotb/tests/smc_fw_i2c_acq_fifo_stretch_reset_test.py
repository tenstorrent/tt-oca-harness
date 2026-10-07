# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C target ACQ FIFO auto-stretch and its release by ACQ reset, seen on SCL.

Firmware test: `fw/tests/i2c_acq_fifo_stretch_reset` is loaded into scratch by
the firmware loader. I2C_1 (controller) offers a 70-byte write to I2C_0
(target) that firmware does not service, so the target reaches STATUS.ACQFULL
and stretches SCL; firmware resets the ACQ FIFO, recovers the abandoned write,
and then receives and compares a 4-byte write. The FIFO levels and the
compare are the firmware's.

Bench observation: the stretch is a duration on SCL that no register reports.
The image parks at two markers and waits for a SCRATCH_4 acknowledge each time;
the bench samples the target's own open-drain pull (tb_i2c0_scl_dut_low) across
a window of ~20 SCL periods at each -- held for a contiguous span longer than
any clock-low phase and through the window's final quarter while ACQ is full,
absent throughout after the reset (the resolved SCL is reported, not required
idle, since the controller may still be clocking) -- and reads the ACQ levels
the image published (non-zero, then zero). The stretch has to outlast four of
the controller's programmed clock-low phases, from the TIMING0.TLOW the image
publishes. The last acknowledged write frame the wire decoder saw to the target
has to be the verify write, byte for byte.

Tokens: CHK-FW-I2C-ACQ-STRETCH-BOOT, CHK-FW-I2C-ACQ-STRETCH-SCL,
CHK-FW-I2C-ACQ-RELEASE-SCL, CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_acq_fifo_stretch_reset.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
  +smc_i2c_shared_bus
Must not use +skip_fuse_sense: a run with the fuse sense skipped is not
evidence for the fuse-derived boot path.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_i2c_acq_fifo_stretch_reset_test_seq import (
    smc_fw_i2c_acq_fifo_stretch_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_i2c_acq_fifo_stretch_reset_test(smc_base_test):
    """Firmware fills ACQ to the stretch; the bench watches SCL held and released."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-ACQ-RELEASE-SCL",
        "CHK-FW-I2C-ACQ-STRETCH-BOOT",
        "CHK-FW-I2C-ACQ-STRETCH-SCL",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 4

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_acq_fifo_stretch_reset_test_seq("fw_i2c_acq_fifo_stretch_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.stretch_ok and seq.release_ok, (
            f"SCL windows not both observed: stretch={seq.stretch_ok} release={seq.release_ok}"
        )
        assert seq.wire_ok, "the wire was not graded"
