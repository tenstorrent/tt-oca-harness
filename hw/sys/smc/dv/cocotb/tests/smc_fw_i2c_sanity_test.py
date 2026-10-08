# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C controller bring-up (SMC_I2C_001) from the CPU: timing, FIFO reset, write+STOP, halt.

Firmware test: `fw/tests/i2c_sanity` is loaded into scratch by the firmware
loader and runs I2C_0 and I2C_1 against each other on the shared pad bus.
DV-TESTCASE-CONTRACT SMC_I2C_001, ENV c-fw: TIMING0-4 read back field by field,
FMT reset on a fifo observed non-empty, a 3-byte write with STOP whose bytes the
target ACQ FIFO returns, the CMD_COMPLETE lifecycle read through the PLIC
pending bit, and CONTROLLER_HALT provoked by a NACK at an unanswered address.

Bench observation: the transfer has to cross the pads. A passive decoder on
tb_i2c0_scl/sda records every START, address byte, direction, acknowledge,
data byte and STOP, and after the PASS word the sequence requires
an acknowledged write frame to 0x10 carrying at least the 3 data bytes, and an
address frame to 0x55 that no target acknowledged.
The firmware's FIFO-level and byte-compare checks stay the firmware's; the
wire is what the bench vouches for.

Tokens: CHK-FW-I2C-SANITY-BOOT, CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_sanity.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
  +smc_i2c_shared_bus
Must not use +skip_fuse_sense: a run with the fuse sense skipped is not
evidence for the fuse-derived boot path.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_i2c_pair_test_seq import WireFloor, smc_fw_i2c_pair_test_seq
from smc_base_test import smc_base_test

TARGET_ADDR = 0x10
# UNUSED_ADDR in the image: matched by no target, so the address phase is NACKed.
UNUSED_ADDR = 0x55


@pyuvm.test()
class smc_fw_i2c_sanity_test(smc_base_test):
    """Firmware controller bring-up; the bench decodes the ACKed write and the NACKed probe."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-SANITY-BOOT",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_pair_test_seq(
            "fw_i2c_sanity_seq",
            tag="I2C-SANITY",
            # PASS landed 0.80 ms after release in the reference run (~1600 polls at a
            # 5 ns clk_smc_i); 16_000 is ~10x that.
            poll_iterations=16_000,
            floors=(
                WireFloor(TARGET_ADDR, read=False, min_frames=1, min_data_bytes=3),
                # S6 provokes CONTROLLER_HALT against an address no target
                # answers, so its address byte must be NACKed on the wire.
                WireFloor(UNUSED_ADDR, read=None, min_frames=1, addr_acked=False),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.wire_ok, "the wire floors were not graded"
