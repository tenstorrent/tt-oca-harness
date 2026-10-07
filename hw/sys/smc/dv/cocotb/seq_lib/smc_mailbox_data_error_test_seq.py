# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox data path and error-response depth test over real SEP_IN AXI.

Every register address and the clock-gate field mask are imported by generated
symbol (``hw/sys/smc/regs/gen/c/smc_addr.h`` / ``blocks/smc_base_config.h``)
([ADDRESS-FROM-AUTHORITATIVE-MAP]).

The DUT-vs-golden compare is the ``expected=`` on each paired ``READ_DATA``
read, enforced by ``SmcScoreboard._check_sys_axi`` (``env/smc_scoreboard.py``): data
written into ``OUTBOUND_WRITE_DATA`` must come back out of
``INBOUND_READ_DATA`` in FIFO order, and vice versa. The scoreboard's
``update_golden`` / ``check_golden`` path is keyed by ``item.addr``, and a
mailbox is a FIFO whose writes land on one address, so an address-keyed model
cannot represent it; the paired-read compare is the verdict.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _SMC_BASE_CFG_H, _field_mask, smc_addr
from .smc_base_test_seq import smc_base_test_seq

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm"
)

OUTBOUND_WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
OUTBOUND_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")
OUTBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
OUTBOUND_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")

INBOUND_WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
INBOUND_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")
INBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_STATUS_BASE_ADDR")
INBOUND_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")

# FIFO payloads. Each is written into one mailbox port and required back out of
# the paired port, so the compare is DUT-vs-stimulus across a real datapath.
OUTBOUND_PAYLOAD_0 = 0x1111_2222_3333_4444
OUTBOUND_PAYLOAD_1 = 0x5555_6666_7777_8888
OUTBOUND_PAYLOAD_OVERFLOW = 0x9999_AAAA_BBBB_CCCC
INBOUND_PAYLOAD_0 = 0xAAAA_BBBB_CCCC_DDDD

EXPECTED_ACCESSES = 22


class smc_mailbox_data_error_test_seq(smc_base_test_seq):
    """Exercise mailbox write/read data flow and illegal access responses."""

    def __init__(self, name: str = "smc_mailbox_data_error_test_seq") -> None:
        super().__init__(name)
        self.accesses = 0
        self.clock_gate_value: int = 0
        self.chk_seen: set[str] = set()

    async def _read(
        self,
        name: str,
        addr: int,
        expected: int | None = None,
        expected_resp: int = AXI_RESP_OKAY,
        allow_error: bool = False,
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        item.expected_resp = expected_resp
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(
        self,
        name: str,
        addr: int,
        data: int,
        expected_resp: int = AXI_RESP_OKAY,
        allow_error: bool = False,
    ) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        item.expected_resp = expected_resp
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _enable_mailbox_clock(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | MAILBOX_CG_EN
        await self._write("CLOCK_GATE_CONTROL_ENABLE_MAILBOX", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL_ENABLED", CLOCK_GATE_CONTROL, expected=enabled)

    async def _restore_mailbox_clock(self) -> None:
        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.clock_gate_value)
        await self._read(
            "CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=self.clock_gate_value
        )

    async def body(self) -> None:
        await self._enable_mailbox_clock()

        await self._read("OUTBOUND_STATUS_BASE", OUTBOUND_STATUS)
        await self._read("INBOUND_STATUS_BASE", INBOUND_STATUS)
        await self._read("OUTBOUND_ERROR_FLAGS_BASE", OUTBOUND_ERROR_FLAGS)
        await self._read("INBOUND_ERROR_FLAGS_BASE", INBOUND_ERROR_FLAGS)

        # Writes to READ_DATA are illegal valid-address operations.
        await self._write(
            "OUTBOUND_READ_DATA_ILLEGAL",
            OUTBOUND_READ_DATA,
            0xBAD0_BAD0_0000_0001,
            expected_resp=AXI_RESP_SLVERR,
            allow_error=True,
        )
        await self._write(
            "INBOUND_READ_DATA_ILLEGAL",
            INBOUND_READ_DATA,
            0xBAD0_BAD0_0000_0002,
            expected_resp=AXI_RESP_SLVERR,
            allow_error=True,
        )

        # Outbound write-data is consumed from the paired inbound read-data port.
        await self._write("OUTBOUND_WRITE_DATA_0", OUTBOUND_WRITE_DATA, OUTBOUND_PAYLOAD_0)
        await self._write("OUTBOUND_WRITE_DATA_1", OUTBOUND_WRITE_DATA, OUTBOUND_PAYLOAD_1)
        await self._write(
            "OUTBOUND_WRITE_DATA_FULL",
            OUTBOUND_WRITE_DATA,
            OUTBOUND_PAYLOAD_OVERFLOW,
            expected_resp=AXI_RESP_SLVERR,
            allow_error=True,
        )
        # DUT-vs-stimulus compares (scoreboard-enforced via `item.expected`):
        # FIFO order and payload integrity across the outbound->inbound path.
        await self._read("INBOUND_READ_DATA_0", INBOUND_READ_DATA, expected=OUTBOUND_PAYLOAD_0)
        await self._read("INBOUND_READ_DATA_1", INBOUND_READ_DATA, expected=OUTBOUND_PAYLOAD_1)
        await self._read(
            "INBOUND_READ_DATA_EMPTY",
            INBOUND_READ_DATA,
            expected_resp=AXI_RESP_SLVERR,
            allow_error=True,
        )

        # Inbound write-data is consumed from the paired outbound read-data port.
        await self._write("INBOUND_WRITE_DATA_0", INBOUND_WRITE_DATA, INBOUND_PAYLOAD_0)
        await self._read("OUTBOUND_READ_DATA_0", OUTBOUND_READ_DATA, expected=INBOUND_PAYLOAD_0)
        await self._read(
            "OUTBOUND_READ_DATA_EMPTY",
            OUTBOUND_READ_DATA,
            expected_resp=AXI_RESP_SLVERR,
            allow_error=True,
        )

        await self._read("OUTBOUND_STATUS_FINAL", OUTBOUND_STATUS)
        await self._read("INBOUND_STATUS_FINAL", INBOUND_STATUS)

        await self._restore_mailbox_clock()

        # Loop integrity (the sequence issued every step) ...
        assert self.accesses == EXPECTED_ACCESSES, (
            f"mailbox data/error sequence issued {self.accesses} accesses, "
            f"expected {EXPECTED_ACCESSES} (loop integrity, not reachability)"
        )
        # ... corroborated against the SCOREBOARD's own count. `self.accesses`
        # is bumped by `_read`/`_write` regardless of what the DUT returned, so
        # on its own it cannot see a mis-bound analysis path that left every
        # compare unexecuted ([NO-DUMMY-DEAD-CODE] / [NO-ZERO-ACTIVITY-PASS]).
        # `sys_axi_checks_seen` is incremented by the scoreboard only for items
        # it actually checked, and each such check asserts `resp_ok`.
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "MAILBOX_DATA_ERROR: no scoreboard on this sequence's env, so the "
            "CSR traffic cannot be corroborated independently of the "
            "sequence's own counter"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"MAILBOX_DATA_ERROR: the scoreboard checked only "
            f"{sb.sys_axi_checks_seen} SYS AXI item(s) but this sequence issued "
            f"{self.accesses} access(es) -- the traffic never reached the "
            f"scoreboard, so none of it is checked evidence"
        )
        cocotb.log.info(
            "CHK-MAILBOX-FIFO-DATA: outbound->inbound returned 0x%016x then "
            "0x%016x in FIFO order and inbound->outbound returned 0x%016x, "
            "each compared by the scoreboard against the value this sequence "
            "wrote into the paired port; overflow write, both empty reads and "
            "both READ_DATA writes answered SLVERR; %d access(es) issued and "
            "%d checked by the scoreboard",
            OUTBOUND_PAYLOAD_0,
            OUTBOUND_PAYLOAD_1,
            INBOUND_PAYLOAD_0,
            self.accesses,
            sb.sys_axi_checks_seen,
        )
        self.chk_seen.add("CHK-MAILBOX-FIFO-DATA")
