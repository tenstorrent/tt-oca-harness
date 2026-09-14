# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse READ_STATUS on a timed-out read.

**Fails while the read timeout arm leaves READ_STATUS clear.** The sequence
holds that defect in runnable form.

`hw/ip/efuse/regs/efuse_interface_ctrl.rdl` documents
``EFUSE_READ_CTRL.READ_STATUS`` as the read interface's error report, and
`hw/ip/efuse/rtl/efuse_program_interface.sv` sets its program-side counterpart
``program_err_d = 1'b1`` on the timeout arm. The read side does not:
`efuse_read_interface.sv`'s ``ST_WAIT_RESP`` timeout arm sets ``read_done``,
clears busy and data and pulses ``read_timeout_event``, but never assigns
``read_err_d``, whose ``always_comb`` default at ``:95`` is ``read_err_q`` -- a
hold. Because the success arm at ``:148`` clears it, a timeout that follows any
successful read reports ``read_done=1, read_status=0, read_back_data=0``:
indistinguishable from a legitimate read of a fuse whose value is zero. The
only observation that names the timeout is ``is_read_timeout_debug_o``, a debug
port with no CSR behind it.

The arming leg is what makes this a real check rather than a coincidence.
``read_err_d`` holds, so a stale 1 from an earlier error would satisfy the
timeout leg on its own; the successful read below is required first, and
``READ_STATUS`` must be observed 0 there. ``STATUS.EFUSE_REQ_ERROR`` is also
required clear, because `efuse_interface_controller.sv:612` gates
``read_enable`` with ``&& ~efuse_req_err`` and would route a sticky req-err
down the ``!read_enable_i`` branch, setting ``READ_STATUS`` for a reason that is
not the timeout.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_read_program_timeout_test_seq import (
    _BIT,
    READ_CTRL,
    READ_DATA,
    READ_DONE,
    READ_EN,
    READ_ERR,
    READ_GO,
    READ_TMO,
    REQ_ERR,
    REQ_ERR_CLR,
    STATUS,
    TMO_CYC_RST_R,
    TMO_EN_R,
)

_POLL = 10_000


class smc_efuse_read_timeout_status_test_seq(SmcCsrSeq):
    """A timed-out eFuse read must set READ_STATUS."""

    def __init__(self, name: str = "smc_efuse_read_timeout_status_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def _wait_done(self, label: str) -> int:
        last = 0
        for _ in range(_POLL):
            last = await self.csr_read(label, READ_CTRL)
            if last & READ_DONE:
                return last
            await cocotb.triggers.RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: READ_DONE never set, last READ_CTRL=0x{last:x}")

    async def _read(self, label: str) -> tuple[int, int]:
        await self.csr_write(f"{label}_GO", READ_CTRL, _BIT | READ_GO | READ_EN)
        st = await self._wait_done(f"{label}_DONE")
        data = await self.csr_read(f"{label}_DATA", READ_DATA)
        await self.csr_write(f"{label}_IDLE", READ_CTRL, 0)
        return st, data

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        # ---- Arm: a successful read at the RDL-default cycle count ----
        await self.csr_write("READ_TMO_DEF", READ_TMO, TMO_CYC_RST_R)
        await self.csr_write("STATUS_CLR", STATUS, REQ_ERR_CLR)
        await self.csr_write("STATUS_CLR0", STATUS, 0)

        stat_pre = await self.csr_read("STATUS_PRE", STATUS)
        assert (stat_pre & REQ_ERR) == 0, (
            f"STATUS.EFUSE_REQ_ERROR set before the arming read "
            f"(STATUS=0x{stat_pre:x}): efuse_interface_controller.sv:612 would "
            f"route that down the same !read_enable branch, so a READ_STATUS=1 "
            f"below could not be attributed to the timeout"
        )

        st_ok, data_ok = await self._read("READ_OK")
        assert (st_ok & READ_ERR) == 0, (
            f"arming read reported READ_STATUS=1 at the RDL-default cycle count "
            f"(READ_CTRL=0x{st_ok:x}); read_err_d holds, so the timeout leg "
            f"below cannot then distinguish a fresh error from this stale one"
        )
        cocotb.log.info(
            "CHK-EFUSE-TMO-RD-STATUS-ARM: READ_TMO=0x%x (RDL default) -> "
            "READ_CTRL=0x%x with READ_STATUS(0x%x)=0, READ_DATA=0x%x. "
            "STATUS=0x%x with REQ_ERROR(0x%x)=0. The bit is proven clear "
            "immediately before the leg that requires it to set",
            TMO_CYC_RST_R,
            st_ok,
            READ_ERR,
            data_ok,
            stat_pre,
            REQ_ERR,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-RD-STATUS-ARM")

        # ---- The leg: same command word, timeout armed with cycles=0 ----
        await self.csr_write("READ_TMO_SHORT", READ_TMO, TMO_EN_R)
        await self.csr_read("READ_TMO_SHORT_RB", READ_TMO, expected=TMO_EN_R)
        st_tmo, data_tmo = await self._read("READ_TMO")

        assert (st_tmo & READ_ERR) == READ_ERR, (
            f"CHK-EFUSE-TMO-RD-STATUS-SET: the read timed out but READ_STATUS "
            f"(0x{READ_ERR:x}) stayed 0. READ_CTRL reads 0x{st_tmo:x} here and "
            f"0x{st_ok:x} on the successful read one leg earlier"
            + (
                " -- the same word, so the register carries no information "
                "distinguishing a timed-out read from a completed one"
                if st_tmo == st_ok
                else ""
            )
            + f". The only difference software can see is READ_DATA: "
            f"0x{data_tmo:x} here against 0x{data_ok:x} there, and 0 is a "
            f"legitimate fuse value. Defect: "
            f"efuse_read_interface.sv's ST_WAIT_RESP timeout arm never assigns "
            f"read_err_d, whose always_comb default is a hold, while "
            f"efuse_program_interface.sv sets program_err_d on the identical "
            f"arm"
        )
        cocotb.log.info(
            "CHK-EFUSE-TMO-RD-STATUS-SET: READ_TMO=0x%x (enable=1, cycles=0) -> "
            "READ_CTRL=0x%x with READ_STATUS(0x%x)=1 and READ_DATA=0x%x, "
            "against READ_CTRL=0x%x READ_STATUS=0 on the arming read. Armed by "
            "CHK-EFUSE-TMO-RD-STATUS-ARM, so the 1 is a transition",
            TMO_EN_R,
            st_tmo,
            READ_ERR,
            data_tmo,
            st_ok,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-RD-STATUS-SET")

        # Restore the default cycle count so this sequence leaves the timeout
        # disarmed for anything that runs after it.
        await self.csr_write("READ_TMO_RESTORE", READ_TMO, TMO_CYC_RST_R)
        await self.csr_write("STATUS_CLR_EXIT", STATUS, REQ_ERR_CLR)
        await self.csr_write("STATUS_CLR0_EXIT", STATUS, 0)
