# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox outbound-0 IRQEN/STATUS via J2A. SEP=1, no Force. IRQ pin / doorbell not claimed."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import mailbox_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")
IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
STATUS_EMPTY = mailbox_u32("AXIL_MAILBOX__STATUS__EMPTY_bm")
STATUS_FULL = mailbox_u32("AXIL_MAILBOX__STATUS__FULL_bm")
STATUS_WTHRESH = mailbox_u32("AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
STATUS_RTHRESH = mailbox_u32("AXIL_MAILBOX__STATUS__READ_LEVEL_ABOVE_THRESH_bm")
# Idle outbound FIFO: empty asserted, full/thresh clear. EMPTY_reset in the
# header is 0 (field POR); the live empty flag is hardware-driven.
IDLE_STATUS = STATUS_EMPTY
IRQEN_PAT = (
    mailbox_u32("AXIL_MAILBOX__IRQEN__WTIRQ_bm")
    | mailbox_u32("AXIL_MAILBOX__IRQEN__RTIRQ_bm")
    | mailbox_u32("AXIL_MAILBOX__IRQEN__EIRQ_bm")
)
POLL = 128
MASK32 = 0xFFFF_FFFF


class smu_smc_mailbox_sanity_test_seq:
    """J2A mailbox outbound-0 STATUS + IRQEN R/W."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=POLL,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"MBX RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & MASK32

    async def _wr32(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=POLL,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"MBX WR {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-MBX-JTAG-READY", (idcode, gate), (DTP_DEFAULT_IDCODE, 0))

        status = await self._rd32(jtag, STATUS, "STATUS")
        busy = STATUS_FULL | STATUS_WTHRESH | STATUS_RTHRESH
        if (status & STATUS_EMPTY) != STATUS_EMPTY or (status & busy) != 0:
            raise AssertionError(
                f"idle STATUS=0x{status:08x} want EMPTY=0x{IDLE_STATUS:08x} "
                f"(full/thresh must be 0, mask=0x{busy:x})"
            )
        err = await self._rd32(jtag, ERROR_FLAGS, "ERROR_FLAGS")
        if err != 0:
            raise AssertionError(f"ERROR_FLAGS want 0 got 0x{err:08x}")
        self.s2_ok = True
        self._log(f"CHK-MBX-STATUS @0x{STATUS:08x} data=0x{status:08x}")
        sb.expect_eq("CHK-MBX-STATUS", status, IDLE_STATUS)
        sb.expect_eq("CHK-MBX-ERR-FLAGS", err, 0)

        await self._wr32(jtag, IRQEN, IRQEN_PAT, "IRQEN")
        got = await self._rd32(jtag, IRQEN, "IRQEN")
        if got != IRQEN_PAT:
            raise AssertionError(f"IRQEN readback want 0x{IRQEN_PAT:08x} got 0x{got:08x}")
        self.s3_ok = True
        sb.expect_eq("CHK-MBX-IRQEN", got, IRQEN_PAT, evidence="SMC_MBX_CSR_OK")

        await self._wr32(jtag, IRQEN, 0, "IRQEN-CLR")
        clr = await self._rd32(jtag, IRQEN, "IRQEN-CLR")
        if clr != 0:
            raise AssertionError(f"IRQEN clear want 0 got 0x{clr:08x}")
        status2 = await self._rd32(jtag, STATUS, "STATUS-POST")
        if (status2 & STATUS_EMPTY) != STATUS_EMPTY or (status2 & busy) != 0:
            raise AssertionError(
                f"post-clear STATUS=0x{status2:08x} want EMPTY=0x{IDLE_STATUS:08x} "
                f"(full/thresh must be 0, mask=0x{busy:x})"
            )
        self.s4_ok = True
        sb.expect_eq("CHK-MBX-IRQEN-CLR", clr, 0)

        self._log(
            f"PASS MBX-SANITY s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} "
            f"status=0x{status:08x} irqen_clr=0x{clr:08x}"
        )
