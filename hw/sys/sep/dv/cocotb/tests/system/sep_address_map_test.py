# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map register sweep test (PyUVM).

Intention: prove the CPU-LSU can decode sep_cpu_ctrl and one safe CSR in every
LSU-reachable CSR block (including ABR and the entropy pool), without owning
full CSR bit-bash or dead-space refuse.

Bring-up holds the CPU off. Expected offsets/resets/masks come from
env/sep_reg_meta.py and the ABR / pool seq constants — see sep_address_map_seq.
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
        self.logger.info(
            "CHK-RW-READBACK PASS: %d pure-RW CSR(s) write->masked readback->restore"
            "%s",
            seq.write_readback_checks,
            (f" ({len(seq.write_readback_storage_only)} of them storage-only -- RDL "
             f"`reserved` placeholders with no software-usable fields: "
             f"{', '.join(seq.write_readback_storage_only)})")
            if seq.write_readback_storage_only else "",
        )
        self.logger.info(
            "CHK-FABRIC-WALK PASS: %d LSU-reachable block CSR(s) decoded",
            seq.fabric_walk_checks,
        )
