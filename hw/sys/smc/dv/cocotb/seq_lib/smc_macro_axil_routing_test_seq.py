# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One bounded SEP_IN read used by the macro AXI-Lite routing test.

Issues a single real CSR read to a peripheral-xbar macro window and captures
the response fields so the test can assert routing/decode plus the
per-window expected response (OKAY or DECERR).
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq


class smc_macro_axil_read_seq(smc_base_test_seq):
    """Read one macro window and expose rdata / resp_code / timed_out."""

    def __init__(self, name: str, addr: int, timeout_ns: int = 400) -> None:
        super().__init__(name)
        self.addr = addr
        self.timeout_ns = timeout_ns
        self.rdata: int = 0
        self.resp_code: int | None = None
        self.timed_out: bool = False

    async def body(self) -> None:
        item = SmcSysAxiItem(f"rd_macro_0x{self.addr:08x}")
        item.op = SmcSysAxiOp.READ
        item.addr = self.addr
        item.length = 4
        # Tolerate DECERR and timeout; the test asserts the exact outcome.
        # allow_timeout: macro AXIL may hang when TB leaves resp idle (deferred
        # needs_dtp_csr_sub / rtl_placeholder); second evidence = resp_code/rdata assert.
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = self.timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        self.rdata = item.rdata
        self.resp_code = item.resp_code
        self.timed_out = item.timed_out
