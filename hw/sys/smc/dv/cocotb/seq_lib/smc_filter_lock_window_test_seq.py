# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes queued right behind the write that locks a filter must be refused.

`filter_ctrl.rdl` makes `FILTER_CONFIG.locked` (bit 63) `woset`: "Lock filter
configurations. Write once register". Once it is set, `smc_internal_regs.sv`
steers every write to that filter's registers to an error slave, so a later
write must be answered with an error and change nothing.

The sequence locks outbound filter 15 with a write of its reset word plus
`locked`, and queues two more writes to `FILTER_CONFIG` directly behind it in
the same outstanding group, carrying `src_id` 5 and 6. Both must be refused,
and `FILTER_CONFIG` must read the reset word plus `locked` afterwards. Filter 15
has `entry_enabled` clear throughout, so no traffic is filtered by it.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
LOCKED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__LOCKED_bm")
SRC_ID_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp")
ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
FILTER = smc_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_NUM") - 1
FILTER_CONFIG = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", FILTER)
BEHIND_SRC_IDS = (5, 6)


def _write(tag: str, data: int) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"wr_{tag}")
    item.op = SmcSysAxiOp.WRITE
    item.addr = FILTER_CONFIG
    item.length = 8
    item.wdata = data
    item.allow_error = True
    return item


class smc_filter_lock_window_test_seq(SmcCsrSeq):
    """Lock a filter with writes queued behind the locking write."""

    def __init__(self, name: str = "smc_filter_lock_window_test_seq") -> None:
        super().__init__(name)
        self.responses: list[int | None] = []
        self.after: int | None = None

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        base = await self.csr_read("FILTER_CONFIG_RESET", FILTER_CONFIG, length=8)
        assert not base & (LOCKED | ENTRY_ENABLED), f"filter {FILTER} not idle: 0x{base:x}"

        lock = _write("LOCK", base | LOCKED)
        behind = [_write(f"BEHIND_SRC{src}", base | (src << SRC_ID_BP)) for src in BEHIND_SRC_IDS]
        group = SmcSysAxiGroupItem("lock_window", [lock, *behind])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 1 + len(behind)
        self.responses = [item.resp_code for item in (lock, *behind)]
        assert lock.resp_code == 0, f"the locking write answered resp={lock.resp_code}"

        self.after = await self.csr_read("FILTER_CONFIG_AFTER", FILTER_CONFIG, length=8)
        landed = [
            src
            for src, item in zip(BEHIND_SRC_IDS, behind)
            if item.resp_code == 0 or (self.after >> SRC_ID_BP) & 0xF == src
        ]
        assert not landed, (
            f"writes queued behind the locking write landed on locked filter {FILTER} "
            f"(src_id {landed}; responses {self.responses}, FILTER_CONFIG 0x{self.after:x}); "
            f"locked is woset and every later write must be refused"
        )
        cocotb.log.info(
            "CHK-FILTER-LOCK-WINDOW: filter %d locked, the %d writes queued behind the lock "
            "were refused (responses %s) and FILTER_CONFIG reads 0x%x",
            FILTER,
            len(behind),
            self.responses,
            self.after,
        )
