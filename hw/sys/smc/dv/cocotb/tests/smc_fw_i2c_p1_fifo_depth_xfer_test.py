# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A full-FIFO-depth 64-byte I2C transfer with the controller pushing while the target drains.

Firmware test: `fw/tests/i2c_p1_fifo_depth_xfer` is loaded into scratch by the firmware
loader and runs I2C_0 and I2C_1 against each other on the shared pad bus.
The image moves a 64-byte payload -- the FIFO depth -- one byte per controller
write while the target drains its ACQ FIFO concurrently, then compares the
length and every byte, classifying entries by ACQ signal so a NACKed byte
cannot pass as payload.

Bench observation: the transfer has to cross the pads. A passive decoder on
tb_i2c0_scl/sda records every START, address byte, direction, acknowledge,
data byte and STOP, and after the PASS word the sequence requires
acknowledged write frames to 0x10 carrying at least 64 data bytes in total.
The firmware's FIFO-level and byte-compare checks stay the firmware's; the
wire is what the bench vouches for.

Tokens: CHK-FW-I2C-FIFO-DEPTH-BOOT, CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_p1_fifo_depth_xfer.ecc.hex   (bare basename; staged by c_compile)
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
class smc_fw_i2c_p1_fifo_depth_xfer_test(smc_base_test):
    """Firmware moves 64 bytes with overlapped push and drain; the bench counts them on the wire."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-FIFO-DEPTH-BOOT",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_pair_test_seq(
            "fw_i2c_p1_fifo_depth_xfer_seq",
            tag="I2C-FIFO-DEPTH",
            # PASS landed 10.2 ms after release at a 5 ns clk_smc_i and 12.7 ms at a
            # 4 ns one (~20,400 and ~31,700 polls): 64 single-byte transactions at
            # standard-mode speed. 150_000 is ~5x the slower figure.
            poll_iterations=150_000,
            floors=(WireFloor(TARGET_ADDR, read=False, min_frames=1, min_data_bytes=64),),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.wire_ok, "the wire floors were not graded"
