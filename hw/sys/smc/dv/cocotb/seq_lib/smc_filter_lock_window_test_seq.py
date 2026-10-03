# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes queued right behind the write that locks a filter must be refused.

`filter_ctrl.rdl` makes `FILTER_CONFIG.locked` (bit 63) `woset`: "Lock filter
configurations. Write once register". Once it is set, `smc_internal_regs.sv`
steers every write to that filter's registers to an error slave, so a later
write must be answered with an error and change nothing.

The sequence locks filter 15 of each bank with a write of its reset word plus
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
BEHIND_SRC_IDS = (5, 6)
_BANKS = (
    (
        "outbound",
        "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_NUM",
        "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR",
    ),
    (
        "inbound",
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_NUM",
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR",
    ),
)


def _write(tag: str, addr: int, data: int) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"wr_{tag}")
    item.op = SmcSysAxiOp.WRITE
    item.addr = addr
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

    async def _lock_one(self, bank: str, num_sym: str, base_sym: str) -> None:
        filt = smc_addr(num_sym) - 1
        addr = smc_indexed_addr(base_sym, filt)
        base = await self.csr_read(f"{bank}_FILTER_CONFIG_RESET", addr, length=8)
        assert not base & (LOCKED | ENTRY_ENABLED), f"{bank} filter {filt} not idle: 0x{base:x}"

        lock = _write(f"{bank}_LOCK", addr, base | LOCKED)
        behind = [
            _write(f"{bank}_BEHIND_SRC{src}", addr, base | (src << SRC_ID_BP))
            for src in BEHIND_SRC_IDS
        ]
        group = SmcSysAxiGroupItem(f"{bank}_lock_window", [lock, *behind])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 1 + len(behind)
        self.responses = [item.resp_code for item in (lock, *behind)]
        assert lock.resp_code == 0, f"the {bank} locking write answered resp={lock.resp_code}"

        self.after = await self.csr_read(f"{bank}_FILTER_CONFIG_AFTER", addr, length=8)
        landed = [
            src
            for src, item in zip(BEHIND_SRC_IDS, behind)
            if item.resp_code == 0 or (self.after >> SRC_ID_BP) & 0xF == src
        ]
        assert not landed, (
            f"writes queued behind the locking write landed on locked {bank} filter {filt} "
            f"(src_id {landed}; responses {self.responses}, FILTER_CONFIG 0x{self.after:x}); "
            f"locked is woset and every later write must be refused"
        )
        cocotb.log.info(
            "CHK-FILTER-LOCK-WINDOW: %s filter %d locked, the %d writes queued behind the lock "
            "were refused (responses %s) and FILTER_CONFIG reads 0x%x",
            bank,
            filt,
            len(behind),
            self.responses,
            self.after,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        for bank in _BANKS:
            await self._lock_one(*bank)
