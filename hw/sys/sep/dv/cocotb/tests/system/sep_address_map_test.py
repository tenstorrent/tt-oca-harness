# SPDX-License-Identifier: Apache-2.0
"""SEP address-map register sweep test (PyUVM).

Builds the SEP env, brings up clocks/reset with the CPU held off, and runs a
field-aware register sweep of sep_cpu_ctrl over the CPU LSU bus: reset-value
read-checks across the map, plus write->readback of the pure-RW registers. The
scoreboard checks the AXI response on every access and the value on every read.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_address_map_seq import sep_address_map_seq


@pyuvm.test()
class sep_address_map_test(sep_base_test):
    """Register sweep of sep_cpu_ctrl over the CPU LSU bus."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_address_map_seq("addr_map_seq")
        await self.start_seq(seq)
        self.logger.info(
            "CHK-REFCNT-READ PASS: REFERENCE_COUNTER readable as 0x%08x_%08x",
            seq.ref_counter_high,
            seq.ref_counter_low,
        )
        self.logger.info(
            "CHK-BASEADDR-RW PASS: %d SEP base/size CSR(s) write->readback->restore",
            seq.base_addr_rw_checks,
        )
