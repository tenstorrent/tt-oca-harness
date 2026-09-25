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
* A read of the last page of ``ecam_region``, a generated-map region with no
  block behind it, which the fabric error slave answers with DECERR.
* The GPIO0 ACCESS_FILTER armed over SEP_IN with a privileged write, then an
  unprivileged JTAG write and read of the same register: the read is refused
  with DECERR and the error-slave signature (``hw/ip/gpio/doc/programming.adoc``,
  "Filter Configuration"), the write with an error response whose code is
  reported, and a privileged readback shows the refused write took no effect.
  The filter is restored to its generated reset before the sequence ends.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import gpio_intf_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

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

# Last page of ecam_region: a generated-map region with no block behind it.
UNIMPLEMENTED_ADDR = (
    smc_addr("SMC_TOP_ECAM_REGION_BASE_ADDR") + smc_addr("SMC_TOP_ECAM_REGION_SIZE") - 0x1000
)

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
# restore and readback.
EXPECTED_SEP_ACCESSES = 5
# JTAG accesses the scoreboard must have completed: a write and a read per
# burst length, the unimplemented-region read, the refused write and read.
EXPECTED_JTAG_ACCESSES = 2 * len(BURST_BEATS) + 3


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


class smc_jtag_axi_shape_test_seq(SmcCsrSeq):
    """Bursts of three lengths and both error responses on the JTAG AXI port."""

    def __init__(self, name: str = "smc_jtag_axi_shape_test_seq") -> None:
        super().__init__(name)
        self.unimplemented_resp: int | None = None
        self.denied_write_resp: int | None = None
        self.denied_read_data: int | None = None

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
            "CHK-JTAG-AXI-ERRORS: JTAG read of the unimplemented ecam_region page 0x%08x answered "
            "%s; with GPIO0 ACCESS_FILTER armed, the unprivileged JTAG write was refused with %s "
            "and took no effect, and the unprivileged JTAG read answered DECERR with 0x%08x",
            UNIMPLEMENTED_ADDR,
            _RESP_NAME.get(self.unimplemented_resp, str(self.unimplemented_resp)),
            _RESP_NAME.get(self.denied_write_resp, str(self.denied_write_resp)),
            self.denied_read_data,
        )
