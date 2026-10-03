# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG AXI port shapes: multi-beat bursts and the fabric's error responses.

``port_table.adoc`` lists the JTAG2AXI master as the third inbound manager of
the input fabric next to SEP_IN and SYS_IN. The other two carry burst and
error-response scenarios of their own; this sequence drives the same shapes on
the JTAG port so the three managers are held to the same fabric behaviour:

* INCR bursts of 2, 8 and 32 full-width beats into the SPM, each read back as
  one burst of the same length, so a splitter that drops, repeats or reorders
  beats on this port is caught on the data.
* A read of the last unmapped page below ``mmode_region``, which the fabric
  error slave answers with DECERR.
* The GPIO0 ACCESS_FILTER armed over SEP_IN with a privileged write, then an
  unprivileged JTAG write and read of the same register: the read is refused
  with DECERR and the error-slave signature (``hw/ip/gpio/doc/programming.adoc``,
  "Filter Configuration"), the write with an error response whose code is
  reported, and a privileged readback shows the refused write took no effect.
  The filter is restored to its generated reset before the sequence ends.
* Three passes of outstanding writes, then of reads, over the eight scratch
  registers while the manager holds BREADY and RREADY low, so the port's
  response channels stall and, with that many addresses queued behind the
  register path, its address channels stall too; every read must still return
  the word its last write carried.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from ._one_shot import _OneShot
from .smc_addr_map import gpio_intf_u32, smc_addr, smc_indexed_addr
from .smc_axi_port_watch import SmcAxiPortWatch
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_mailbox_data_error_test_seq import CLOCK_GATE_CONTROL, INBOUND_READ_DATA, MAILBOX_CG_EN

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import GPIO_INTF_ACCESS_FILTER_REG_DEFAULT  # noqa: E402

# Full-width beats into the SPM, above the windows the SEP_IN and SYS_IN shape
# sequences use.
BURST_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x3_4000
BURST_BYTES = 8
# AxLEN 1, 7 and 31.
BURST_BEATS = (2, 8, 32)
BURST_STRIDE = 0x400
# Backpressure groups: three passes over the eight scratch registers, with
# the manager holding BREADY and RREADY low for this many cycles. The
# register path serialises the accesses, so this many queued addresses hold
# AWREADY and ARREADY low as well.
BACKPRESSURE_COUNT = 8
BACKPRESSURE_PASSES = 3
READY_HOLD_CYCLES = 64
AXI_RESP_SLVERR = 2

# Last page of the unmapped gap below mmode_region.
UNIMPLEMENTED_ADDR = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - 0x1000

GPIO0_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
FILTER_RESET = GPIO_INTF_ACCESS_FILTER_REG_DEFAULT
FILTER_LOCK = (
    FILTER_RESET
    | gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__WRITE_FILTER_ENABLE_bm")
    | gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__READ_FILTER_ENABLE_bm")
)
AWPROT_PRIV = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_reset")
ARPROT_PRIV = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_reset")
PROT_UNPRIV = 0
AXI_RESP_DECERR = 3
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

# SEP_IN accesses: filter arm and readback, readback after the refused write,
# restore and readback, mailbox clock read, enable and readback, restore and
# readback, 8 scratch restores after the backpressure groups.
EXPECTED_SEP_ACCESSES = 18
# JTAG accesses the scoreboard must have completed: a write and a read per
# burst length, the unimplemented-region read and write, the refused write and
# read, the empty-mailbox read, and the backpressure groups.
EXPECTED_JTAG_ACCESSES = 2 * len(BURST_BEATS) + 5 + 2 * BACKPRESSURE_PASSES * BACKPRESSURE_COUNT


def burst_beat(beats: int, index: int) -> int:
    return (
        0x1A60_0000_0000_0000
        | (beats << 40)
        | (index << 32)
        | (0xFFFF_FFFF ^ (index * 0x0101_0101))
    )


def burst_payload(beats: int) -> int:
    return sum(burst_beat(beats, i) << (64 * i) for i in range(beats))


def burst_base(beats: int) -> int:
    return BURST_BASE + BURST_BEATS.index(beats) * BURST_STRIDE


def backpressure_word(index: int, write_pass: int = BACKPRESSURE_PASSES - 1) -> int:
    return 0xBAC0_0000 | (write_pass << 16) | (index << 8) | (0xFF ^ index)


def scratch_cold(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", index)


class smc_jtag_axi_shape_test_seq(SmcCsrSeq):
    """Bursts of three lengths and both error responses on the JTAG AXI port."""

    def __init__(self, name: str = "smc_jtag_axi_shape_test_seq") -> None:
        super().__init__(name)
        self.unimplemented_resp: int | None = None
        self.denied_write_resp: int | None = None
        self.denied_read_data: int | None = None
        self.unimplemented_write_resp: int | None = None
        self.empty_mailbox_resp: int | None = None
        self.stalls: dict[str, int] | None = None

    async def _jtag(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        length: int = BURST_BYTES,
        beats: int = 1,
        wdata: int = 0,
        expected: int | None = None,
        allow_error: bool = False,
        expect_error: bool = False,
        prot: int = PROT_UNPRIV,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"jtag_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.beats = beats
        item.wdata = wdata
        item.expected = expected
        item.allow_error = allow_error or expect_error
        item.expect_error = expect_error
        item.prot = prot
        await _OneShot(item, f"jtag_{label}_os").start(self.env.jtag_axi_agent.sequencer)
        return item

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for beats in BURST_BEATS:
            base = burst_base(beats)
            await self._jtag(
                f"burst{beats}_wr", SmcSysAxiOp.WRITE, base, beats=beats, wdata=burst_payload(beats)
            )
            await self._jtag(
                f"burst{beats}_rd",
                SmcSysAxiOp.READ,
                base,
                beats=beats,
                expected=burst_payload(beats),
            )

        monitor = getattr(self.env, "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update({UNIMPLEMENTED_ADDR, GPIO0_FILTER})

        unimpl = await self._jtag(
            "unimplemented_rd", SmcSysAxiOp.READ, UNIMPLEMENTED_ADDR, length=4, allow_error=True
        )
        self.unimplemented_resp = unimpl.resp_code
        assert unimpl.resp_code == AXI_RESP_DECERR, (
            f"JTAG read of unimplemented 0x{UNIMPLEMENTED_ADDR:08x} answered "
            f"{_RESP_NAME.get(unimpl.resp_code, unimpl.resp_code)}, expected DECERR"
        )

        dead_wr = await self._jtag(
            "unimplemented_wr",
            SmcSysAxiOp.WRITE,
            UNIMPLEMENTED_ADDR,
            length=4,
            wdata=0xDEAD_0000,
            allow_error=True,
        )
        self.unimplemented_write_resp = dead_wr.resp_code
        assert dead_wr.resp_code == AXI_RESP_DECERR, (
            f"JTAG write to unimplemented 0x{UNIMPLEMENTED_ADDR:08x} answered "
            f"{_RESP_NAME.get(dead_wr.resp_code, dead_wr.resp_code)}, expected DECERR"
        )

        # A read of an empty mailbox is the register-level SLVERR the mailbox
        # error test proves over SEP_IN; here it is taken over the JTAG port.
        clock_gate = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, length=8)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_ENABLE_MAILBOX",
            CLOCK_GATE_CONTROL,
            clock_gate | MAILBOX_CG_EN,
            length=8,
        )
        await self.csr_read(
            "CLOCK_GATE_CONTROL_ENABLED",
            CLOCK_GATE_CONTROL,
            expected=clock_gate | MAILBOX_CG_EN,
            length=8,
        )
        empty = await self._jtag(
            "mailbox_empty_rd", SmcSysAxiOp.READ, INBOUND_READ_DATA, allow_error=True
        )
        self.empty_mailbox_resp = empty.resp_code
        assert empty.resp_code == AXI_RESP_SLVERR, (
            f"JTAG read of the empty inbound mailbox answered "
            f"{_RESP_NAME.get(empty.resp_code, empty.resp_code)}, expected SLVERR"
        )
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, clock_gate, length=8)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=clock_gate, length=8
        )

        await self.csr_write("GPIO0_FILTER_LOCK", GPIO0_FILTER, FILTER_LOCK, prot=AWPROT_PRIV)
        await self.csr_read(
            "GPIO0_FILTER_LOCKED", GPIO0_FILTER, expected=FILTER_LOCK, prot=ARPROT_PRIV
        )
        denied_wr = await self._jtag(
            "filter_denied_wr",
            SmcSysAxiOp.WRITE,
            GPIO0_FILTER,
            length=4,
            wdata=FILTER_RESET,
            expect_error=True,
        )
        self.denied_write_resp = denied_wr.resp_code
        assert denied_wr.resp_code is not None and denied_wr.resp_code > 1, (
            f"unprivileged JTAG write to the armed filter answered "
            f"{_RESP_NAME.get(denied_wr.resp_code, denied_wr.resp_code)}, expected an error"
        )
        denied_rd = await self._jtag(
            "filter_denied_rd", SmcSysAxiOp.READ, GPIO0_FILTER, length=4, expect_error=True
        )
        self.denied_read_data = denied_rd.rdata & 0xFFFF_FFFF
        assert denied_rd.resp_code == AXI_RESP_DECERR, (
            f"unprivileged JTAG read of the armed filter answered "
            f"{_RESP_NAME.get(denied_rd.resp_code, denied_rd.resp_code)}, expected DECERR"
        )
        assert self.denied_read_data == (self.ERR_SLAVE_SIGNATURE & 0xFFFF_FFFF), (
            f"refused JTAG read returned 0x{self.denied_read_data:08x}, expected the "
            f"error-slave signature 0x{self.ERR_SLAVE_SIGNATURE:08x}"
        )
        # The refused write carried the disarm value; the filter must still be armed.
        await self.csr_read(
            "GPIO0_FILTER_STILL_LOCKED", GPIO0_FILTER, expected=FILTER_LOCK, prot=ARPROT_PRIV
        )
        await self.csr_write("GPIO0_FILTER_RESTORE", GPIO0_FILTER, FILTER_RESET, prot=AWPROT_PRIV)
        await self.csr_read("GPIO0_FILTER_RESTORED", GPIO0_FILTER, expected=FILTER_RESET)

        # Writes first, reads once they have drained: AXI orders nothing
        # between the two channels, so a read pipelined behind its write may
        # return the old word.
        port = SmcAxiPortWatch(cocotb.top, "jtag_axi")
        port_task = cocotb.start_soon(port.run())
        hold = AxiTimingProfile(b_ready_delay=READY_HOLD_CYCLES, r_ready_delay=READY_HOLD_CYCLES)
        writes = []
        reads = []
        for write_pass in range(BACKPRESSURE_PASSES):
            for index in range(BACKPRESSURE_COUNT):
                item = SmcSysAxiItem(f"jtag_backpressure_wr{index}_p{write_pass}")
                item.op = SmcSysAxiOp.WRITE
                item.addr = scratch_cold(index)
                item.length = 4
                item.wdata = backpressure_word(index, write_pass)
                writes.append(item)
                item = SmcSysAxiItem(f"jtag_backpressure_rd{index}_p{write_pass}")
                item.op = SmcSysAxiOp.READ
                item.addr = scratch_cold(index)
                item.length = 4
                item.expected = backpressure_word(index)
                reads.append(item)
        for name, members in (("jtag_backpressure_wr", writes), ("jtag_backpressure_rd", reads)):
            group = SmcSysAxiGroupItem(name, members, timing=hold)
            await _OneShot(group, f"{name}_os").start(self.env.jtag_axi_agent.sequencer)
        port.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await port_task
        self.stalls = dict(port.stalls)
        assert self.stalls["b"] > 0 and self.stalls["r"] > 0, (
            f"the backpressure profile never stalled the response channels: {self.stalls}"
        )
        for index in range(BACKPRESSURE_COUNT):
            await self.csr_write(f"BACKPRESSURE_RESTORE_{index}", scratch_cold(index), 0)

        assert self.accesses == EXPECTED_SEP_ACCESSES, (
            f"issued {self.accesses} SEP_IN accesses, expected {EXPECTED_SEP_ACCESSES}"
        )
        jtag_done = self.env.scoreboard.axi_accesses_by_bus.get("JTAG AXI", 0)
        assert jtag_done == EXPECTED_JTAG_ACCESSES, (
            f"scoreboard completed {jtag_done} JTAG AXI accesses, expected {EXPECTED_JTAG_ACCESSES}"
        )
        cocotb.log.info(
            "CHK-JTAG-AXI-BURSTS: INCR bursts of %s full-width beats written over the JTAG AXI "
            "port at 0x%08x, 0x%08x and 0x%08x each read back in order as one burst of the same "
            "length",
            "/".join(str(b) for b in BURST_BEATS),
            burst_base(BURST_BEATS[0]),
            burst_base(BURST_BEATS[1]),
            burst_base(BURST_BEATS[2]),
        )
        cocotb.log.info(
            "CHK-JTAG-AXI-BACKPRESSURE: %d outstanding JTAG AXI accesses under a %d-cycle "
            "BREADY/RREADY hold stalled aw=%d ar=%d b=%d r=%d cycles; every read returned the "
            "word its last write carried",
            2 * BACKPRESSURE_PASSES * BACKPRESSURE_COUNT,
            READY_HOLD_CYCLES,
            self.stalls["aw"],
            self.stalls["ar"],
            self.stalls["b"],
            self.stalls["r"],
        )
        cocotb.log.info(
            "CHK-JTAG-AXI-ERRORS: JTAG read and write of the unmapped page "
            "0x%08x answered %s and %s; with GPIO0 ACCESS_FILTER armed, the unprivileged JTAG "
            "write was refused with %s and took no effect, and the unprivileged JTAG read "
            "answered DECERR with 0x%08x; the read of the empty inbound mailbox answered %s",
            UNIMPLEMENTED_ADDR,
            _RESP_NAME.get(self.unimplemented_resp, str(self.unimplemented_resp)),
            _RESP_NAME.get(self.unimplemented_write_resp, str(self.unimplemented_write_resp)),
            _RESP_NAME.get(self.denied_write_resp, str(self.denied_write_resp)),
            self.denied_read_data,
            _RESP_NAME.get(self.empty_mailbox_resp, str(self.empty_mailbox_resp)),
        )
