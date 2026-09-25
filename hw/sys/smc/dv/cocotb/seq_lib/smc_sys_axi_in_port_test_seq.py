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

The write and read channels of the port are then driven together: the filter
decides each direction from its own request (``axi_filter_wrap.sv:211,221``,
``isolate_write`` / ``isolate_read`` are separate terms), so an entry that
allows both must admit a write and a read presented in the same cycle. Four
interleaved passes go out as one outstanding group; SEP_IN reads back the write
targets and each read carries the value SEP_IN seeded, so a filter that blocked
one direction while the other was in flight, or crossed the two decisions,
fails on the data rather than only on the response.

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
from cocotb.triggers import ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

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


def scratch_cold(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", index)


VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
SCRATCH_COLD_0 = scratch_cold(0)
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
SCRATCH_PATTERN = 0x5A5A_C0DE
AXI_RESP_DECERR = 3
# Multi-beat INCR bursts into the SPM, above the window other hosted
# sequences use; a 2-beat and a 16-beat burst of full-width beats.
BURST_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x3_2000
BURST_BYTES = 8
SHORT_BURST_BEATS = 2
LONG_BURST_BEATS = 16


def burst_beat(index: int) -> int:
    return 0x5B5B_0000_0000_0000 | (index << 32) | (0xFFFF_FFFF ^ index)


def burst_payload(beats: int) -> int:
    return sum(burst_beat(i) << (64 * i) for i in range(beats))


# Last page of ecam_region: a generated-map region with no block behind it,
# which the fabric error slave answers with DECERR (the error-depth test proves
# this over SEP_IN).
UNIMPLEMENTED_ADDR = (
    smc_addr("SMC_TOP_ECAM_REGION_BASE_ADDR") + smc_addr("SMC_TOP_ECAM_REGION_SIZE") - 0x1000
)
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

# Concurrent-direction phase: two registers written and two read per pass.
DUPLEX_WRITE_INDICES = (2, 3)
DUPLEX_READ_INDICES = (4, 5)
DUPLEX_PASSES = 4


def duplex_seed(index: int) -> int:
    """Word SEP_IN parks in a read source before the concurrent phase."""
    return 0x5EED_0000 | (index << 8) | index


def duplex_pattern(index: int, pass_index: int = DUPLEX_PASSES - 1) -> int:
    """Word the SYS_IN write of one pass carries into a write target."""
    return 0x0DD0_0000 | (pass_index << 16) | (index << 8) | (0xFF ^ index)


# SEP_IN accesses: 3 admit writes + config readback, scratch readback, scratch
# restore + readback, 2 duplex seeds, 2 duplex readbacks, 4 duplex restores,
# 3 restore writes + config readback.
EXPECTED_SEP_ACCESSES = 19
# SYS_IN accesses the scoreboard must have completed: pre-admit read,
# VERSION_LO read, scratch write, scratch read, the concurrent group, two
# burst writes with their two burst reads, and the unimplemented-region read.
EXPECTED_SYS_IN_ACCESSES = (
    4 + DUPLEX_PASSES * (len(DUPLEX_WRITE_INDICES) + len(DUPLEX_READ_INDICES)) + 5
)


class _FilterWatch:
    """Counts the cycles the inbound filter admitted a write and a read at once.

    ``axi_filter_wrap.sv`` raises ``write_filter_hit`` / ``read_filter_hit``
    from the matching entry and drives ``isolate_write`` / ``isolate_read`` from
    that entry's per-direction rule, with block-by-default when nothing matches
    (``smc_input_fabric.sv:348``). Admitting both directions in one cycle is
    therefore both hits set with neither isolate.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.duplex_admitted = 0

    def _read(self, name: str) -> int:
        value = getattr(self.dut, name).value
        return int(value) if value.is_resolvable else 0

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            if (
                self._read("sys_axi_awvalid")
                and self._read("sys_axi_arvalid")
                and self._read("tb_inb_write_hit")
                and self._read("tb_inb_read_hit")
                and not self._read("tb_inb_isolate_write")
                and not self._read("tb_inb_isolate_read")
            ):
                self.duplex_admitted += 1


class smc_sys_axi_in_port_test_seq(SmcCsrSeq):
    """Admit through inbound entry 0, then read and write over sys_axi_in."""

    def __init__(self, name: str = "smc_sys_axi_in_port_test_seq") -> None:
        super().__init__(name)
        self.pre_admit_resp: int | None = None
        self.sys_read_word: int | None = None
        self.sys_scratch_word: int | None = None
        self.duplex_admitted: int | None = None
        self.unimplemented_resp: int | None = None

    async def _sys_in(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        expected: int | None = None,
        allow_error: bool = False,
        length: int = 4,
        beats: int = 1,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.beats = beats
        item.wdata = wdata
        item.expected = expected
        item.allow_error = allow_error
        await _OneShot(item, f"sys_in_{label}_os").start(self.env.sys_in_axi_agent.sequencer)
        return item

    def _duplex_member(
        self, label: str, op: SmcSysAxiOp, addr: int, *, wdata: int = 0, expected: int | None = None
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        item.expected = expected
        return item

    async def _duplex_phase(self, watch: "_FilterWatch") -> None:
        """Drive the SYS_IN write and read channels together through the filter."""
        for index in DUPLEX_READ_INDICES:
            await self.csr_write(f"DUPLEX_SEED_{index}", scratch_cold(index), duplex_seed(index))

        members: list[SmcSysAxiItem] = []
        for pass_index in range(DUPLEX_PASSES):
            for index in DUPLEX_WRITE_INDICES:
                members.append(
                    self._duplex_member(
                        f"DUPLEX_WR{index}_P{pass_index}",
                        SmcSysAxiOp.WRITE,
                        scratch_cold(index),
                        wdata=duplex_pattern(index, pass_index),
                    )
                )
            for index in DUPLEX_READ_INDICES:
                members.append(
                    self._duplex_member(
                        f"DUPLEX_RD{index}_P{pass_index}",
                        SmcSysAxiOp.READ,
                        scratch_cold(index),
                        expected=duplex_seed(index),
                    )
                )
        group = SmcSysAxiGroupItem("sys_in_duplex_group", members)
        await _OneShot(group, "sys_in_duplex_os").start(self.env.sys_in_axi_agent.sequencer)

        for index in DUPLEX_WRITE_INDICES:
            await self.csr_read(
                f"DUPLEX_WR{index}_RB", scratch_cold(index), expected=duplex_pattern(index)
            )
        for index in DUPLEX_WRITE_INDICES + DUPLEX_READ_INDICES:
            await self.csr_write(f"DUPLEX_RESTORE_{index}", scratch_cold(index), 0)

        self.duplex_admitted = watch.duplex_admitted
        assert self.duplex_admitted > 0, (
            "the inbound filter never admitted a SYS_IN write and read in the "
            "same cycle, so the concurrent-direction stimulus this phase is "
            "built on never reached the filter"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        watch = _FilterWatch(cocotb.top)
        watcher = cocotb.start_soon(watch.run())

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

        # Multi-beat INCR bursts through the admitted port into the SPM, each
        # read back as one burst.
        for tag, beats in (("SHORT", SHORT_BURST_BEATS), ("LONG", LONG_BURST_BEATS)):
            base = BURST_BASE + (0x100 if tag == "LONG" else 0)
            await self._sys_in(
                f"BURST_{tag}_WR",
                SmcSysAxiOp.WRITE,
                base,
                length=BURST_BYTES,
                beats=beats,
                wdata=burst_payload(beats),
            )
            await self._sys_in(
                f"BURST_{tag}_RD",
                SmcSysAxiOp.READ,
                base,
                length=BURST_BYTES,
                beats=beats,
                expected=burst_payload(beats),
            )

        # A region with no block behind it: admitted by the pass-all entry,
        # answered by the fabric error slave.
        monitor = getattr(self.env, "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.add(UNIMPLEMENTED_ADDR)
        unimpl = await self._sys_in(
            "UNIMPLEMENTED_RD", SmcSysAxiOp.READ, UNIMPLEMENTED_ADDR, allow_error=True
        )
        self.unimplemented_resp = unimpl.resp_code
        assert unimpl.resp_code == AXI_RESP_DECERR, (
            f"sys_axi_in read of unimplemented 0x{UNIMPLEMENTED_ADDR:08x} answered "
            f"{_RESP_NAME.get(unimpl.resp_code, unimpl.resp_code)}, expected DECERR"
        )

        await self._duplex_phase(watch)
        watch.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await watcher

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
            "CHK-SYS-AXI-IN-DUPLEX: %d outstanding sys_axi_in accesses drove the write and read "
            "channels together; the inbound filter admitted both directions in %d cycle(s), each "
            "read returned the word SEP_IN seeded and SCRATCH_COLD_%s held pass %d after the group",
            DUPLEX_PASSES * (len(DUPLEX_WRITE_INDICES) + len(DUPLEX_READ_INDICES)),
            self.duplex_admitted,
            "/".join(str(i) for i in DUPLEX_WRITE_INDICES),
            DUPLEX_PASSES - 1,
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-NOT-CLOSED: unused-port-tied-idle -- every inbound port of this bench "
            "carries an agent, none is tied to zero"
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-BURST: AxLEN=%d and AxLEN=%d INCR bursts of %d-byte beats written "
            "over sys_axi_in at 0x%08x and 0x%08x each read back in order as one burst; a "
            "sys_axi_in read of the unimplemented ecam_region page 0x%08x answered %s",
            SHORT_BURST_BEATS - 1,
            LONG_BURST_BEATS - 1,
            BURST_BYTES,
            BURST_BASE,
            BURST_BASE + 0x100,
            UNIMPLEMENTED_ADDR,
            _RESP_NAME.get(self.unimplemented_resp, str(self.unimplemented_resp)),
        )
