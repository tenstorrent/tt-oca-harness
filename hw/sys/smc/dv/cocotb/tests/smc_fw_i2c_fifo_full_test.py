# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fill and reset of the four FIFOs of an I2C pair, the RX and ACQ legs by real transfers.

Firmware test: `fw/tests/i2c_fifo_full` is loaded into scratch by the firmware
loader and runs I2C_0 and I2C_1 against each other on the shared pad bus.
FMT and TX are filled by software stores to the depth the specification
gives (`fw/include/i2c_opentitan.h` transcribes the I2C IP parameter defaults
and the SMC override table) and reset; RX and ACQ are filled by a real 8-byte
read and a real 8-byte write
between I2C_0 and I2C_1, their levels proven non-zero before the reset and zero
after, with the driver's software-drain repair flag read back so a repaired
FIFO fails instead of passing. The cocotb smc_i2c_fifo_full_test covers the
CSR-level full/empty flags only.

Bench observation: the transfer has to cross the pads. A passive decoder on
tb_i2c0_scl/sda records every START, address byte, direction, acknowledge,
data byte and STOP, and after the PASS word the sequence requires
a read frame to 0x10 that returned at least 8 bytes and an acknowledged write
frame to 0x10 carrying at least 8 bytes.
The firmware's FIFO-level and byte-compare checks stay the firmware's; the
wire is what the bench vouches for.

Tokens: CHK-FW-I2C-FIFO-FULL-BOOT, CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_fifo_full.ecc.hex   (bare basename; staged by c_compile)
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


@pyuvm.test()
class smc_fw_i2c_fifo_full_test(smc_base_test):
    """Firmware fills FMT/TX by stores and RX/ACQ by transfers; the bench sees the transfers."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-FIFO-FULL-BOOT",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_pair_test_seq(
            "fw_i2c_fifo_full_seq",
            tag="I2C-FIFO-FULL",
            # PASS landed 1.70 ms after release in the reference run (~3400 polls at a
            # 5 ns clk_smc_i); 35_000 is ~10x that.
            poll_iterations=35_000,
            floors=(
                # RX leg: a real 8-byte read from the target fills the controller RX FIFO.
                WireFloor(TARGET_ADDR, read=True, min_frames=1, min_data_bytes=8),
                # ACQ leg: a real 8-byte write from the controller fills the target ACQ FIFO.
                WireFloor(TARGET_ADDR, read=False, min_frames=1, min_data_bytes=8),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.wire_ok, "the wire floors were not graded"
