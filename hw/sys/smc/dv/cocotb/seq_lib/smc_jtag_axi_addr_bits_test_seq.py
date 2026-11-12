# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG AXI port: address bits above the SMC map and bit 27 falling after a set.

The JTAG inbound manager and the output port carry a 56-bit address (`port_table.adoc`). Every
access the other JTAG leaves issue sits inside the SMC's 32-bit map with bit 27 clear or set
once, so the address bits above bit 31 never rise on the port and bit 27 never falls. This
sequence takes the unimplemented word below the M-mode region, which the fabric's error slave
answers with DECERR inside the SMC (`smc_jtag_axi_shape_test`), and reads and writes it with
address bits [36:34], [39:38] and [55:41] set in turn: an address outside the SMC map leaves on
the output port (`fabric.adoc`, every other address goes straight through), so each such access
must complete OKAY from the system responder with the output port carrying the driven 56-bit
address, while the access with the bits clear decodes inside and answers DECERR. A read of the
CLINT `MTIME` address, which sets bit 27 and at the reset `REGION_SIZE` lies beyond the local
aperture, leaves on the output port the same way; a scratch register whose address clears bit
27 is then written and read back.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

UNIMPLEMENTED_ADDR = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - 0x1000
CLINT_MTIME = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
BIT27 = 1 << 27
SCRATCH_PATTERN = 0x5A3C_0F96
assert CLINT_MTIME & BIT27 and not SCRATCH_COLD_0 & BIT27 and not UNIMPLEMENTED_ADDR & BIT27, (
    "CLINT MTIME must carry address bit 27; the scratch register and the unimplemented word must not"
)
# Address bit groups above the SMC's 32-bit map, each set on its own access.
HIGH_GROUPS = (
    ("36:34", sum(1 << b for b in range(34, 37))),
    ("39:38", sum(1 << b for b in range(38, 40))),
    ("55:41", sum(1 << b for b in range(41, 56))),
)
WRITE_GROUPS = (("36", 1 << 36), ("55:41", sum(1 << b for b in range(41, 56))))
AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
PROT_UNPRIV = 0
CHECKERS = (
    "CHK-JTAGADDR-BIT27-FALLS",
    "CHK-JTAGADDR-READ-HIGH-BITS",
    "CHK-JTAGADDR-WRITE-HIGH-BITS",
)
PLANNED_ACCESSES = 3 + len(HIGH_GROUPS) + 1 + len(WRITE_GROUPS) + 1


class _OneShot(pyuvm.uvm_sequence):
    def __init__(self, item: SmcSysAxiItem, name: str) -> None:
        super().__init__(name)
        self.item = item

    async def body(self) -> None:
        await self.start_item(self.item)
        await self.finish_item(self.item)


class smc_jtag_axi_addr_bits_test_seq(SmcCsrSeq):
    """Address bits above the map and bit 27 falling, on the JTAG AXI port."""

    def __init__(self, name: str = "smc_jtag_axi_addr_bits_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    async def _jtag(
        self, label: str, op: SmcSysAxiOp, addr: int, wdata: int = 0, decerr: bool = False
    ) -> SmcSysAxiItem:
        """One 4-byte JTAG access; DECERR when `decerr`, else OKAY, and the port's address."""
        item = SmcSysAxiItem(f"jtag_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        item.allow_error = decerr
        item.expect_error = decerr
        item.prot = PROT_UNPRIV
        await _OneShot(item, f"jtag_{label}_os").start(self.env.jtag_axi_agent.sequencer)
        self.accesses += 1
        want = AXI_RESP_DECERR if decerr else AXI_RESP_OKAY
        assert item.resp_code == want, (
            f"JTAG {op.value} at {addr:#016x} answered resp {item.resp_code}, expected {want}"
        )
        return item

    def _output_addr(self, op: SmcSysAxiOp, addr: int) -> None:
        """The output port's last address of `op` equals the driven 56-bit address."""
        monitor = self.env.output_axi_monitor
        seen = monitor.last_araddr if op is SmcSysAxiOp.READ else monitor.last_awaddr
        assert seen == addr, (
            f"JTAG {op.value} at {addr:#016x} left the SMC with output address "
            f"{seen if seen is None else f'{seen:#016x}'}"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        high_addrs = [UNIMPLEMENTED_ADDR | bits for _n, bits in HIGH_GROUPS]
        write_addrs = [UNIMPLEMENTED_ADDR | bits for _n, bits in WRITE_GROUPS]

        await self._jtag("bit27_set_rd", SmcSysAxiOp.READ, CLINT_MTIME)
        self._output_addr(SmcSysAxiOp.READ, CLINT_MTIME)
        await self._jtag("bit27_clear_wr", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, SCRATCH_PATTERN)
        back = await self._jtag("bit27_clear_rd", SmcSysAxiOp.READ, SCRATCH_COLD_0)
        assert back.rdata == SCRATCH_PATTERN, (
            f"scratch register {SCRATCH_COLD_0:#010x} read {back.rdata:#x} over the JTAG port "
            f"after a write of {SCRATCH_PATTERN:#x}"
        )
        self._chk(
            "CHK-JTAGADDR-BIT27-FALLS",
            f"read of the CLINT MTIME address {CLINT_MTIME:#010x} (bit 27 set, beyond the local "
            f"aperture at reset) left on the output port at that address and answered OKAY, "
            f"then {SCRATCH_COLD_0:#010x} (bit 27 clear) took {SCRATCH_PATTERN:#x} and read it "
            f"back",
        )

        for (name, _bits), addr in zip(HIGH_GROUPS, high_addrs):
            await self._jtag(f"high{name}_rd", SmcSysAxiOp.READ, addr)
            self._output_addr(SmcSysAxiOp.READ, addr)
        await self._jtag("high_clear_rd", SmcSysAxiOp.READ, UNIMPLEMENTED_ADDR, decerr=True)
        self._chk(
            "CHK-JTAGADDR-READ-HIGH-BITS",
            f"reads with address bits {', '.join(n for n, _b in HIGH_GROUPS)} set above the "
            f"unimplemented word each left on the output port at the driven address and "
            f"answered OKAY; the read with them clear answered DECERR inside the SMC",
        )

        for (name, _bits), addr in zip(WRITE_GROUPS, write_addrs):
            await self._jtag(f"high{name}_wr", SmcSysAxiOp.WRITE, addr, 0xDEAD_0000)
            self._output_addr(SmcSysAxiOp.WRITE, addr)
        await self._jtag(
            "high_clear_wr", SmcSysAxiOp.WRITE, UNIMPLEMENTED_ADDR, 0xDEAD_0000, decerr=True
        )
        self._chk(
            "CHK-JTAGADDR-WRITE-HIGH-BITS",
            f"writes with address bits {', '.join(n for n, _b in WRITE_GROUPS)} set above the "
            f"unimplemented word each left on the output port at the driven address and "
            f"answered OKAY; the write with them clear answered DECERR inside the SMC",
        )
