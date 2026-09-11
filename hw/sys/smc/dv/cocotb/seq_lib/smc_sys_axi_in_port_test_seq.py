# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""sys_axi_in carries a read and a write to a local register once an inbound entry admits it.

``port_table.adoc`` declares ``sys_axi_in_req_i`` as the system AXI input
(56-bit address, 64-bit data, 6-bit ID, 12-bit user) into the input fabric,
and ``fabric.adoc`` (Inbound Filtering) makes the inbound filter the gate an
external transaction must pass. Inbound entry 0 is programmed over SEP_IN to
admit every address (the same pass-all recipe the output-fabric tests use),
then the SYS_IN port reads a register with a non-zero generated reset and
writes a scratch word that is read back over both ports, so the same storage
is shown reachable from the system port and from SEP_IN. The entry is restored
to its generated reset afterwards.

The pre-admit SYS_IN read is issued with the error response tolerated and its
response is reported, not asserted: the specification leaves the reset state
of the sixteen inbound entries to the chiplet integration. No inbound port is
tied off in this bench (SEP_IN, SYS_IN and JTAG all carry agents), so the
"unused port tied idle" cell is left open.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
SCRATCH_PATTERN = 0x5A5A_C0DE
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

# SEP_IN accesses: 3 admit writes + config readback, scratch readback, scratch
# restore + readback, 3 restore writes + config readback.
EXPECTED_SEP_ACCESSES = 11
# SYS_IN accesses the scoreboard must have completed: pre-admit read,
# VERSION_LO read, scratch write, scratch read.
EXPECTED_SYS_IN_ACCESSES = 4


class smc_sys_axi_in_port_test_seq(SmcCsrSeq):
    """Admit through inbound entry 0, then read and write over sys_axi_in."""

    def __init__(self, name: str = "smc_sys_axi_in_port_test_seq") -> None:
        super().__init__(name)
        self.pre_admit_resp: int | None = None
        self.sys_read_word: int | None = None
        self.sys_scratch_word: int | None = None

    async def _sys_in(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        expected: int | None = None,
        allow_error: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        item.expected = expected
        item.allow_error = allow_error
        await _OneShot(item, f"sys_in_{label}_os").start(self.env.sys_in_axi_agent.sequencer)
        return item

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        pre = await self._sys_in(
            "PRE_ADMIT_VERSION_LO", SmcSysAxiOp.READ, VERSION_LO, allow_error=True
        )
        self.pre_admit_resp = pre.resp_code

        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, INBOUND_PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )

        rd = await self._sys_in(
            "VERSION_LO", SmcSysAxiOp.READ, VERSION_LO, expected=CHIP_CONFIG_VERSION_LO_REG_DEFAULT
        )
        self.sys_read_word = rd.rdata & 0xFFFF_FFFF
        await self._sys_in("SCRATCH_WR", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=SCRATCH_PATTERN)
        await self.csr_read("SCRATCH_COLD_0_VIA_SEP_IN", SCRATCH_COLD_0, expected=SCRATCH_PATTERN)
        rb = await self._sys_in(
            "SCRATCH_RD", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=SCRATCH_PATTERN
        )
        self.sys_scratch_word = rb.rdata & 0xFFFF_FFFF
        await self.csr_write("SCRATCH_COLD_0_RESTORE", SCRATCH_COLD_0, 0)
        await self.csr_read("SCRATCH_COLD_0_RESTORE_RB", SCRATCH_COLD_0, expected=0)

        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )

        assert self.accesses == EXPECTED_SEP_ACCESSES, (
            f"issued {self.accesses} SEP_IN accesses, expected {EXPECTED_SEP_ACCESSES}"
        )
        sys_in_done = self.env.scoreboard.axi_accesses_by_bus.get("SYS_IN AXI", 0)
        assert sys_in_done == EXPECTED_SYS_IN_ACCESSES, (
            f"scoreboard completed {sys_in_done} SYS_IN AXI accesses, expected {EXPECTED_SYS_IN_ACCESSES}"
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-READ: after inbound entry 0 admitted [0, 0x%x], a sys_axi_in read of "
            "CHIP_CONFIG.VERSION_LO returned 0x%08x == generated reset 0x%x (pre-admit read of the "
            "same address answered %s, reported not asserted)",
            INBOUND_PASS_ALL_END,
            self.sys_read_word,
            CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
            _RESP_NAME.get(self.pre_admit_resp, str(self.pre_admit_resp)),
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-WRITE: sys_axi_in wrote 0x%08x to SCRATCH_COLD_0; SEP_IN read it back "
            "and sys_axi_in read 0x%08x; %d SYS_IN and %d SEP_IN accesses completed",
            SCRATCH_PATTERN,
            self.sys_scratch_word,
            sys_in_done,
            self.accesses,
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-NOT-CLOSED: unused-port-tied-idle -- every inbound port of this bench "
            "carries an agent, none is tied to zero"
        )
