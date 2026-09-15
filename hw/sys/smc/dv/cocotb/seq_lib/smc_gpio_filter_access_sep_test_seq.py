# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO ACCESS_FILTER AxPROT gating: privileged accepted, unprivileged denied.

Both halves of the filter are exercised on the same address in the same locked
state, each paired with a privileged access as its positive control:

  * READ half -- an unprivileged read is refused with DECERR and the error-slave
    signature 0xBADCAB1E, while the privileged read returns the programmed word.
  * WRITE half -- an unprivileged write of the value that would DISARM the
    filter is refused, and a privileged read afterwards shows the register
    unchanged, so the refusal is proven to have taken no effect. The refusal
    code is asserted as "an error response" rather than an exact code: the read
    half is refused with DECERR out of `gpio_filter.sv`'s error slave while the
    write half reaches the SEP_IN AXI port as SLVERR, and no document this bench
    can cite fixes that integration behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import GPIO_INTF_ACCESS_FILTER_REG_DEFAULT  # noqa: E402

GPIO0_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
GPIO1_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 1)

# Address, reset default and every field mask come from the SAME generated
# block, `gpio_intf` -- the block whose ACCESS_FILTER register these addresses
# select. `gpio_poc_pbias_ctrl` is a separately generated block with its own
# ACCESS_FILTER register and no exported address in `smc_addr.h`
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
_FILTER_RESET = GPIO_INTF_ACCESS_FILTER_REG_DEFAULT
_FILTER_LOCK = (
    _FILTER_RESET
    | gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__WRITE_FILTER_ENABLE_bm")
    | gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__READ_FILTER_ENABLE_bm")
)
# The write and read halves carry their own AxPROT requirement fields, so the
# write legs use the AW-derived value and the read legs the AR-derived one.
_AWPROT_PRIV = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_reset")
_ARPROT_PRIV = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_reset")
_PROT_UNPRIV = 0
AXI_RESP_DECERR = 3
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


class smc_gpio_filter_access_sep_test_seq(SmcCsrSeq):
    """GPIO0/1 ACCESS_FILTER: privileged lock sticks; unprivileged is denied."""

    def __init__(self, name: str = "smc_gpio_filter_access_sep_test_seq") -> None:
        super().__init__(name)
        #: Response codes the DUT returned on each denied access, published so
        #: the testcase module can report measurements rather than flags.
        self.denied_resps: list[int] = []

    async def _write_denied(self, name: str, addr: int, data: int) -> int:
        """Unprivileged ACCESS_FILTER write must be refused on the B channel.

        The expectation is "an error response", not an exact code: the read
        half of this same filter is refused with DECERR straight out of
        `gpio_filter.sv`'s `prim_axil_err_slv`
        (`hw/common/och_prim/rtl/prim_axil_err_slv.sv:85-95`, `Resp =
        RESP_DECERR`), while the write half arrives at the SEP_IN AXI port as
        SLVERR, and no document this bench can cite fixes that integration
        behaviour. The caller pairs this leg with the property that carries the
        security claim: the refused write must not take effect, proven by a
        privileged readback afterwards.
        """
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        item.expect_error = True
        item.prot = _PROT_UNPRIV
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: an unprivileged write to a write-filtered "
            f"register must be refused with an error response, got "
            f"resp={item.resp_code} ({_RESP_NAME.get(item.resp_code, '?')})"
        )
        self.denied_resps.append(item.resp_code)
        return item.resp_code

    async def _read_denied_decerr(self, name: str, addr: int) -> int:
        """Unprivileged ACCESS_FILTER read must DECERR with 0xBADCAB1E."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.expect_error = True
        item.prot = _PROT_UNPRIV
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{name} @ 0x{addr:08x}: expected DECERR, got "
            f"resp={item.resp_code} ({_RESP_NAME.get(item.resp_code, '?')})"
        )
        got = item.rdata & 0xFFFF_FFFF
        assert got == (self.ERR_SLAVE_SIGNATURE & 0xFFFF_FFFF), (
            f"{name} @ 0x{addr:08x}: expected 0x{self.ERR_SLAVE_SIGNATURE:08x}, got 0x{got:08x}"
        )
        self.denied_resps.append(item.resp_code)
        return item.rdata

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update({GPIO0_FILTER, GPIO1_FILTER})

        got = await self.csr_read(
            "GPIO0_FILTER_PRE", GPIO0_FILTER, expected=_FILTER_RESET, prot=_PROT_UNPRIV
        )
        cocotb.log.info("CHK-GPIO-FILTER-PRE: GPIO0 ACCESS_FILTER reset 0x%x with AxPROT=0", got)

        await self.csr_write("GPIO0_FILTER_LOCK", GPIO0_FILTER, _FILTER_LOCK, prot=_AWPROT_PRIV)
        got = await self.csr_read(
            "GPIO0_FILTER_PRIV", GPIO0_FILTER, expected=_FILTER_LOCK, prot=_ARPROT_PRIV
        )
        cocotb.log.info("CHK-GPIO-FILTER-PRIV: GPIO0 ACCESS_FILTER 0x%x with AxPROT=1", got)

        resp = await self._read_denied_decerr("GPIO0_FILTER_UNPRIV", GPIO0_FILTER)
        cocotb.log.info(
            "CHK-GPIO-FILTER-UNPRIV: GPIO0 ACCESS_FILTER AxPROT=0 read -> resp=%s rdata=0x%08x",
            _RESP_NAME.get(AXI_RESP_DECERR),
            resp & 0xFFFF_FFFF,
        )

        # Write half of the same filter, on the same address, in the same locked
        # state. The payload is `_FILTER_RESET`, the value that would CLEAR both
        # filter-enable bits: if the refused write had landed, the filter would
        # have disarmed itself, so the privileged readback that follows is a
        # direct test of "the refused write took no effect" rather than a
        # response-code observation.
        wr_resp = await self._write_denied("GPIO0_FILTER_UNPRIV_WR", GPIO0_FILTER, _FILTER_RESET)
        got = await self.csr_read(
            "GPIO0_FILTER_AFTER_DENIED_WR",
            GPIO0_FILTER,
            expected=_FILTER_LOCK,
            prot=_ARPROT_PRIV,
        )
        # Positive control for the deny: the same address in the same state still
        # accepts a PRIVILEGED write, so the refusal above is the AxPROT filter
        # and not a window that stopped accepting writes altogether.
        await self.csr_write("GPIO0_FILTER_PRIV_WR", GPIO0_FILTER, _FILTER_LOCK, prot=_AWPROT_PRIV)
        cocotb.log.info(
            "CHK-GPIO-FILTER-WR-DENY: GPIO0 ACCESS_FILTER AxPROT=0 write of "
            "0x%x refused with resp=%s (%d) and the register still reads 0x%x, "
            "so the denied write took no effect; a privileged write to the same "
            "address in the same state is accepted",
            _FILTER_RESET,
            _RESP_NAME.get(wr_resp, "?"),
            wr_resp,
            got,
        )

        await self.csr_write("GPIO1_FILTER_LOCK", GPIO1_FILTER, _FILTER_LOCK, prot=_AWPROT_PRIV)
        got = await self.csr_read(
            "GPIO1_FILTER_PRIV", GPIO1_FILTER, expected=_FILTER_LOCK, prot=_ARPROT_PRIV
        )
        resp = await self._read_denied_decerr("GPIO1_FILTER_UNPRIV", GPIO1_FILTER)
        cocotb.log.info(
            "CHK-GPIO-FILTER-GPIO1: GPIO1 ACCESS_FILTER priv=0x%x unpriv rdata=0x%08x DECERR",
            got,
            resp & 0xFFFF_FFFF,
        )
