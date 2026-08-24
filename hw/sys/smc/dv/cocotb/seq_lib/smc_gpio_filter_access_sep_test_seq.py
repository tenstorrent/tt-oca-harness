# SPDX-License-Identifier: Apache-2.0
"""GPIO ACCESS_FILTER AxPROT: privileged OKAY, unprivileged DECERR+0xBADCAB1E."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp
from .smc_addr_map import gpio_poc_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import GPIO_INTF_ACCESS_FILTER_REG_DEFAULT  # noqa: E402

GPIO0_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
GPIO1_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 1)

_FILTER_RESET = GPIO_INTF_ACCESS_FILTER_REG_DEFAULT
_FILTER_LOCK = (
    _FILTER_RESET
    | gpio_poc_u32("GPIO_POC_PBIAS_CTRL__ACCESS_FILTER__WRITE_FILTER_ENABLE_bm")
    | gpio_poc_u32("GPIO_POC_PBIAS_CTRL__ACCESS_FILTER__READ_FILTER_ENABLE_bm")
)
_PROT_PRIV = gpio_poc_u32(
    "GPIO_POC_PBIAS_CTRL__ACCESS_FILTER__AWPROT_REQUIREMENT_reset"
)
_PROT_UNPRIV = 0
AXI_RESP_DECERR = 3
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


class smc_gpio_filter_access_sep_test_seq(SmcCsrSeq):
    """GPIO0/1 ACCESS_FILTER: privileged lock sticks; unprivileged is denied."""

    def __init__(self, name: str = "smc_gpio_filter_access_sep_test_seq") -> None:
        super().__init__(name)
        self.pre_ok = False
        self.priv_ok = False
        self.unpriv_ok = False
        self.gpio1_ok = False

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
            f"{name} @ 0x{addr:08x}: expected 0x{self.ERR_SLAVE_SIGNATURE:08x}, "
            f"got 0x{got:08x}"
        )
        return item.rdata

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update({GPIO0_FILTER, GPIO1_FILTER})

        got = await self.csr_read(
            "GPIO0_FILTER_PRE", GPIO0_FILTER, expected=_FILTER_RESET, prot=_PROT_UNPRIV
        )
        self.pre_ok = True
        cocotb.log.info(
            "CHK-GPIO-FILTER-PRE: GPIO0 ACCESS_FILTER reset 0x%x with AxPROT=0", got
        )

        await self.csr_write(
            "GPIO0_FILTER_LOCK", GPIO0_FILTER, _FILTER_LOCK, prot=_PROT_PRIV
        )
        got = await self.csr_read(
            "GPIO0_FILTER_PRIV", GPIO0_FILTER, expected=_FILTER_LOCK, prot=_PROT_PRIV
        )
        self.priv_ok = True
        cocotb.log.info(
            "CHK-GPIO-FILTER-PRIV: GPIO0 ACCESS_FILTER 0x%x with AxPROT=1", got
        )

        await self._read_denied_decerr("GPIO0_FILTER_UNPRIV", GPIO0_FILTER)
        self.unpriv_ok = True
        cocotb.log.info(
            "CHK-GPIO-FILTER-UNPRIV: GPIO0 ACCESS_FILTER AxPROT=0 DECERR+0xBADCAB1E"
        )

        await self.csr_write(
            "GPIO1_FILTER_LOCK", GPIO1_FILTER, _FILTER_LOCK, prot=_PROT_PRIV
        )
        got = await self.csr_read(
            "GPIO1_FILTER_PRIV", GPIO1_FILTER, expected=_FILTER_LOCK, prot=_PROT_PRIV
        )
        await self._read_denied_decerr("GPIO1_FILTER_UNPRIV", GPIO1_FILTER)
        self.gpio1_ok = True
        cocotb.log.info(
            "CHK-GPIO-FILTER-GPIO1: GPIO1 ACCESS_FILTER priv=0x%x unpriv DECERR", got
        )
        cocotb.log.info(
            "CHK-GPIO-FILTER-BASIC: pre=%s priv=%s unpriv=%s gpio1=%s",
            self.pre_ok,
            self.priv_ok,
            self.unpriv_ok,
            self.gpio1_ok,
        )
