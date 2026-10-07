# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C target bring-up (SMC_I2C_005) from the CPU, with the bench as external host.

Firmware test: `fw/tests/i2c_target_sanity` (DV-TESTCASE-CONTRACT SMC_I2C_005,
ENV c-fw) is loaded into scratch by the firmware loader. I2C_0 is the
controller and I2C_1 the target on the shared pad bus: ADDR0 match, dual
address, ACQ write, TX read and TX stretch control are CPU-driven and graded
by the firmware from both instances' CSRs. Step S6 then releases I2C_0 and
waits for an external host to end a read with STOP and no NACK, which the
OpenTitan controller cannot do.

Bench observation: a SCRATCH_1 watcher plays that host with SmcI2cMasterVip
when the image publishes 0xEBEDEBE3 -- it reads one byte, which must be the
first of the target's preloaded TX bytes (0x77), clocked out by the DUT, and
STOPs inside that byte's acknowledge clock -- and the wire decoder on
tb_i2c0_scl/sda must have seen frames to both target addresses 0x10 and 0x20.
The firmware grades INTR_STATE.UNEXP_STOP on the same event.

Tokens: CHK-FW-I2C-TARGET-SANITY-BOOT, CHK-FW-I2C-TARGET-VIP-READ,
CHK-FW-I2C-WIRE-TRAFFIC.

Requires the staged image, a held boot and the shared pad bus:
  +smc_scratch_ram_hex=i2c_target_sanity.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
  +smc_i2c_shared_bus
Must not use +skip_fuse_sense: a run with the fuse sense skipped is not
evidence for the fuse-derived boot path.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_i2c_target_sanity_test_seq import smc_fw_i2c_target_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_i2c_target_sanity_test(smc_base_test):
    """Firmware target bring-up; the bench hosts the illegal STOP and decodes the wire."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I2C-TARGET-SANITY-BOOT",
        "CHK-FW-I2C-TARGET-VIP-READ",
        "CHK-FW-I2C-WIRE-TRAFFIC",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_fw_i2c_target_sanity_test_seq("fw_i2c_target_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.vip_read_ok, "the bench host read was not graded"
        assert seq.wire_ok, "the wire floors were not graded"
