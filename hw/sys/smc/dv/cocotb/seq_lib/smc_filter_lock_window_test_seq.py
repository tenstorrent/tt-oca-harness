# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes queued right behind the write that locks a filter must be refused.

`filter_ctrl.rdl` makes `FILTER_CONFIG.locked` (bit 63) `woset`: "Lock filter
configurations. Write once register", and once it is set "every subsequent
write to this filter entry's FILTER_CONFIG, START_ADDR and END_ADDR registers
is steered to the AXI error subordinate and terminates with a DECERR response;
reads still return the locked configuration".

The sequence locks filter 15 of each bank with a write of its reset word plus
`locked`, and queues two more writes to `FILTER_CONFIG` directly behind it in
the same outstanding group, carrying `src_id` 5 and 6. Both must be answered
DECERR, and `FILTER_CONFIG` must read the reset word plus `locked` afterwards.
Filter 15 has `entry_enabled` clear throughout, so no traffic is filtered by
it. The two addresses are registered with the SEP_IN monitor as the only
places a DECERR is expected; the locking write itself is held to OKAY.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_decode_probe_utils import AXI_RESP_DECERR

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


def _write(tag: str, addr: int, data: int, refused: bool) -> SmcSysAxiItem:
    """A 64-bit write; a refused one must be answered DECERR, any other OKAY."""
    item = SmcSysAxiItem(f"wr_{tag}")
    item.op = SmcSysAxiOp.WRITE
    item.addr = addr
    item.length = 8
    item.wdata = data
    if refused:
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
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

        lock = _write(f"{bank}_LOCK", addr, base | LOCKED, refused=False)
        behind = [
            _write(f"{bank}_BEHIND_SRC{src}", addr, base | (src << SRC_ID_BP), refused=True)
            for src in BEHIND_SRC_IDS
        ]
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        group = SmcSysAxiGroupItem(f"{bank}_lock_window", [lock, *behind])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 1 + len(behind)
        self.responses = [item.resp_code for item in (lock, *behind)]
        assert lock.resp_code == 0, f"the {bank} locking write answered resp={lock.resp_code}"
        refused = [item.resp_code for item in behind]
        assert all(code == AXI_RESP_DECERR for code in refused), (
            f"the writes queued behind the {bank} locking write answered {refused}; "
            f"filter_ctrl.rdl steers every write after `locked` to the error subordinate, "
            f"which terminates it with DECERR ({AXI_RESP_DECERR})"
        )

        self.after = await self.csr_read(f"{bank}_FILTER_CONFIG_AFTER", addr, length=8)
        assert self.after == base | LOCKED, (
            f"locked {bank} filter {filt} reads FILTER_CONFIG 0x{self.after:x}, not its reset "
            f"word plus locked 0x{base | LOCKED:x} (responses {self.responses}); a refused "
            f"write changes nothing and only a reset clears `locked`"
        )
        cocotb.log.info(
            "CHK-FILTER-LOCK-WINDOW: %s filter %d locked, the %d writes queued behind the lock "
            "were refused with DECERR (responses %s) and FILTER_CONFIG reads 0x%x, its reset "
            "word plus locked",
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
