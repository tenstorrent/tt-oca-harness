# SPDX-License-Identifier: Apache-2.0
"""PROGRAM/READ timeout CSRs. No Force. timeout_enable|0 fires in ST_WAIT_RESP on this shim."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

STATUS = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR"
)
PROGRAM_CTRL = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR"
)
READ_CTRL = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR"
)
READ_DATA = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR"
)
PROG_TMO = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_BASE_ADDR"
)
READ_TMO = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR"
)

PROG_DATA = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
PROG_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
PROG_RB = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm"
)
PROG_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_ENABLE_bm")
PROG_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_DONE_bm")
PROG_ERR = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_STATUS_bm")
READ_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__EFUSE_READ_GO_bm")
READ_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_ENABLE_bm")
READ_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_DONE_bm")
READ_ERR = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_STATUS_bm")
TMO_EN_P = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_REQ_TIMEOUT__PROGRAM_REQ_TIMEOUT_ENABLE_bm"
)
TMO_EN_R = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMOUT_ENABLE_bm"
)
TMO_CYC_RST_P = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_REQ_TIMEOUT__PROGRAM_REQ_TIMEOUT_CYCLES_reset"
)
TMO_CYC_RST_R = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_reset"
)
REQ_ERR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_bm"
)
REQ_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_CLEAR_bm"
)

OTP_WORD0_MARKER = 0xA5A55A5A
_BIT = 0
_POLL = 10_000


class smc_efuse_read_program_timeout_test_seq(SmcCsrSeq):
    """Timeout CSR aborts program/read; default timeout recovers the burn."""

    def __init__(self, name: str = "smc_efuse_read_program_timeout_test_seq") -> None:
        super().__init__(name)
        self.prog_tmo_ok = False
        self.prog_rec_ok = False
        self.read_tmo_ok = False
        self.read_rec_ok = False

    async def _wait_mask(self, addr: int, mask: int, label: str) -> int:
        last = 0
        for _ in range(_POLL):
            last = await self.csr_read(label, addr)
            if last & mask:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: mask 0x{mask:x} never set last=0x{last:x}")

    async def _clear_req_err(self) -> None:
        await self.csr_write("STATUS_CLR", STATUS, REQ_ERR_CLR)
        await self.csr_write("STATUS_CLR0", STATUS, 0)

    async def _program(self, label: str, idle: bool = True) -> int:
        cmd = _BIT | PROG_DATA | PROG_GO | PROG_RB | PROG_EN
        await self.csr_write(f"{label}_GO", PROGRAM_CTRL, cmd)
        st = await self._wait_mask(PROGRAM_CTRL, PROG_DONE, f"{label}_DONE")
        if idle:
            await self.csr_write(f"{label}_IDLE", PROGRAM_CTRL, 0)
        return st

    async def _read(self, label: str) -> tuple[int, int]:
        await self.csr_write(f"{label}_GO", READ_CTRL, _BIT | READ_GO | READ_EN)
        st = await self._wait_mask(READ_CTRL, READ_DONE, f"{label}_DONE")
        data = await self.csr_read(f"{label}_DATA", READ_DATA)
        await self.csr_write(f"{label}_IDLE", READ_CTRL, 0)
        return st, data

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        await self.csr_write("PROG_TMO_SHORT", PROG_TMO, TMO_EN_P)
        got = await self.csr_read("PROG_TMO_RB", PROG_TMO, expected=TMO_EN_P)
        st = await self._program("PROG_TMO", idle=False)
        otp = int(dut.tb_efuse_programmed_word0.value)
        assert st & PROG_ERR, f"short program timeout expected status=1 got 0x{st:x}"
        assert otp == OTP_WORD0_MARKER, (
            f"timed-out program sticky-OR OTP: 0x{otp:08x}"
        )
        self.prog_tmo_ok = True
        cocotb.log.info(
            "CHK-EFUSE-TMO-PROG: CTRL=0x%x OTP=0x%x tmo=0x%x", st, otp, got
        )

        st_hold = await self.csr_read("PROG_TMO_HOLD", PROGRAM_CTRL)
        stat_hold = await self.csr_read("STATUS_HOLD", STATUS)
        assert st_hold & PROG_ERR, (
            f"timeout PROGRAM_STATUS not sticky: CTRL=0x{st_hold:x}"
        )
        # PROGRAM_STATUS is live HW from the last op; writing 0 does not
        # clear it. EFUSE_REQ_ERROR stays 0 on this timeout path (STATUS
        # after sense is typically 0x1). Next PROGRAM completion is the
        # cleared-status sample.
        cocotb.log.info(
            "CHK-EFUSE-TMO-PROG-SET: CTRL=0x%x STATUS=0x%x req_err=%d",
            st_hold,
            stat_hold,
            1 if (stat_hold & REQ_ERR) else 0,
        )
        await self.csr_write("PROG_TMO_IDLE", PROGRAM_CTRL, 0)
        await self._clear_req_err()

        await self.csr_write("PROG_TMO_DEF", PROG_TMO, TMO_CYC_RST_P)
        st = await self._program("PROG_REC")
        otp = int(dut.tb_efuse_programmed_word0.value)
        assert (st & PROG_ERR) == 0, f"recovery program status=1 CTRL=0x{st:x}"
        assert (otp & 1) == 1, f"recovery did not set bit0 OTP=0x{otp:08x}"
        self.prog_rec_ok = True
        cocotb.log.info("CHK-EFUSE-TMO-PROG-REC: CTRL=0x%x OTP=0x%x", st, otp)

        await self.csr_write("READ_TMO_SHORT", READ_TMO, TMO_EN_R)
        got = await self.csr_read("READ_TMO_RB", READ_TMO, expected=TMO_EN_R)
        st, data = await self._read("READ_TMO")
        assert data == 0, f"timed-out read data=0x{data:x} want 0"
        self.read_tmo_ok = True
        cocotb.log.info(
            "CHK-EFUSE-TMO-RD: CTRL=0x%x data=0x%x tmo=0x%x", st, data, got
        )

        await self.csr_write("READ_TMO_DEF", READ_TMO, TMO_CYC_RST_R)
        await self._clear_req_err()
        st, data = await self._read("READ_REC")
        assert (st & READ_ERR) == 0, f"recovery read status=1 CTRL=0x{st:x}"
        assert (data & 1) == 1, f"recovery read missed bit0 data=0x{data:x}"
        self.read_rec_ok = True
        cocotb.log.info("CHK-EFUSE-TMO-RD-REC: CTRL=0x%x data=0x%x", st, data)
        cocotb.log.info(
            "CHK-EFUSE-TMO-BASIC: prog=%s rec=%s rd=%s rdrec=%s",
            self.prog_tmo_ok,
            self.prog_rec_ok,
            self.read_tmo_ok,
            self.read_rec_ok,
        )
