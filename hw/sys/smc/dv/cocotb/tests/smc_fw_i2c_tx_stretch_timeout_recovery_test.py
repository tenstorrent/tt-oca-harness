# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Controller recovery after a target TX stretch timeout, then a clean 16-byte write.

Firmware test: `fw/tests/i2c_tx_stretch_timeout_recovery` is loaded into scratch by the firmware
loader and runs I2C_0 and I2C_1 against each other on the shared pad bus.
I2C_1 (controller) reads from I2C_0 (target) while the target TX FIFO is empty,
so the target stretches SCL until the controller stretch timeout fires; firmware
then disables the target to release SCL, disables the controller to exercise
the automatic STOP recovery, reinitialises both, and checks a 16-byte write.

Bench observation: the transfer has to cross the pads. A passive decoder on
tb_i2c0_scl/sda records every START, address byte, direction, acknowledge,
data byte and STOP, and after the PASS word the sequence requires
an acknowledged read frame to 0x10 (the stretched read) and an acknowledged
write frame to 0x10 carrying at least the 16 recovery bytes.
The firmware's FIFO-level and byte-compare checks stay the firmware's; the
wire is what the bench vouches for.

Tokens: CHK-FW-I2C-TX-STRETCH-TIMEOUT-BOOT, CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_tx_stretch_timeout_recovery.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
  +smc_i2c_shared_bus
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_i2c_pair_test_seq import WireFloor, smc_fw_i2c_pair_test_seq
from smc_base_test import smc_base_test

TARGET_ADDR = 0x10


@pyuvm.test()
class smc_fw_i2c_tx_stretch_timeout_recovery_test(smc_base_test):
    """Firmware times out a stretched read and recovers; the bench sees both transfers."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-TX-STRETCH-TIMEOUT-BOOT",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_pair_test_seq(
            "fw_i2c_tx_stretch_timeout_recovery_seq",
            tag="I2C-TX-STRETCH-TIMEOUT",
            # PASS landed 2.47 ms after release in the reference run (~4900 polls at a
            # 5 ns clk_smc_i); 50_000 is ~10x that.
            poll_iterations=50_000,
            floors=(
                # The read the empty target TX FIFO stretches until the controller times out.
                WireFloor(TARGET_ADDR, read=True, min_frames=1),
                # The 16-byte write after both sides were reinitialised.
                WireFloor(TARGET_ADDR, read=False, min_frames=1, min_data_bytes=16),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.wire_ok, "the wire floors were not graded"
