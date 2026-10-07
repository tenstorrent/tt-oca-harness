# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C CSR-decode and SCL/SDA pin-override depth test.

PROXY, not an error/FIFO-depth test. This module runs the same
``smc_i2c_master_target_test_seq`` body as ``smc_i2c_master_target_test``:
I2C0 host/target CSR decode plus LSIO SCL/SDA release and pull-low checks.

It measures no FIFO depth -- ``FIFO_STATUS`` is never read, and the only
``FIFO_CTRL`` accesses are ``RXRST | FMTRST`` resets -- and it injects no error:
``CONTROLLER_EVENTS`` is written W1C to clear and read only to decorate failure
messages, so no event bit is ever asserted. The residual gap -- FIFO-depth and
error-injection coverage -- is recorded under DOES NOT DEFEND in this
testcase's VPLAN entry.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_master_target_test_seq import smc_i2c_master_target_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_error_fifo_depth_test(smc_base_test):
    """Run I2C CSR decode plus SCL/SDA pin override depth checks."""

    required_evidence = (
        "CHK-I2C0-HOST-REPEATED-START",
        "CHK-I2C0-HOST-WRITE",
        "CHK-I2C0-OVRD-PAD",
        "CHK-I2C0-SMBUS-ARA",
        "CHK-I2C0-SMBUS-PEC",
        "CHK-I2C0-U4-2-SMBUS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_error_fifo_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the I2C STATUS/FIFO polls are timing-dependent.
            min_csr_accesses=45,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=True,
            details=(
                "PROXY for I2C error/FIFO-depth coverage: I2C0 CSR decode plus "
                "LSIO SCL/SDA release and pull-low behaviour checked. No FIFO "
                "depth measured (FIFO_STATUS never read) and no error injected "
                "(CONTROLLER_EVENTS only cleared and reported)"
            ),
        )
