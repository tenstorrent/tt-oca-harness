# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse READ_STATUS on a timed-out read.

`hw/ip/efuse/regs/efuse_interface_ctrl.rdl` defines
``EFUSE_READ_CTRL.READ_STATUS`` as the read interface's error report
(``read_done`` says the read completed, ``read_status`` says how),
``EFUSE_READ_REQ_TIMEOUT`` arms a bound on the cycles the interface waits for a
SHIM response, and the eFuse section of
`doc/programmer/src/smc-programming.adoc` has software check ``read_status``
after every completion. A read that hits that bound is therefore a completed
read with an error: ``read_done=1`` and ``read_status=1``. This sequence proves
the 1 is produced by the timeout.

The arming leg is what makes the check real. ``READ_STATUS`` is a status bit
that holds until the next completion, so a stale 1 from an earlier error would
satisfy the timeout leg on its own; a successful read at the RDL-default cycle
count comes first, and ``READ_STATUS`` must be observed 0 there.
``STATUS.EFUSE_REQ_ERROR`` is also required clear beforehand, because a sticky
request error reports through ``READ_STATUS`` as well and would set the bit for
a reason that is not the timeout.
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
            f"(STATUS=0x{stat_pre:x}): a sticky request error also reports "
            f"through READ_STATUS, so a READ_STATUS=1 below could not be "
            f"attributed to the timeout"
        )

        st_ok, data_ok = await self._read("READ_OK")
        assert (st_ok & READ_ERR) == 0, (
            f"arming read reported READ_STATUS=1 at the RDL-default cycle count "
            f"(READ_CTRL=0x{st_ok:x}); the bit holds until the next completion, "
            f"so the timeout leg below could not distinguish a fresh error from "
            f"this stale one"
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
            + f". READ_DATA is 0x{data_tmo:x} here against 0x{data_ok:x} "
            f"there, and 0 is a legitimate fuse value. "
            f"efuse_interface_ctrl.rdl EFUSE_READ_CTRL.read_status is the read "
            f"interface's error report and a timed-out read is a completed "
            f"read with an error, so it must read 1 here"
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
