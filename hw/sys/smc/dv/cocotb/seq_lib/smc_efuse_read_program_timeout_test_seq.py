# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROGRAM/READ timeout CSRs. No Force. timeout_enable|0 fires in ST_WAIT_RESP on this shim.

**The claim is split, and only one half is a DUT-path claim.**

*DUT path (reportable).* ``EFUSE_PROGRAM_REQ_TIMEOUT`` /
``EFUSE_READ_REQ_TIMEOUT`` with ``timeout_enable=1, cycles=0`` must abort the
outstanding request and raise ``EFUSE_PROGRAM_CTRL.PROGRAM_STATUS`` /
leave ``EFUSE_READ_INTERFACE_READ_DATA`` empty; re-programming the RDL-default
cycle count must let the same operation complete. That FSM is real
``efuse_interface_controller`` RTL and every address, field mask and reset used
here is imported by generated symbol from ``efuse_interface_ctrl.h``.

*Model-backed (NOT silicon-path coverage).* ``tb_efuse_programmed_word0`` is a
TB tap on ``u_dut.u_smc_ip_integration.u_efuse_bank_model.u_efuse_bank_reg``
(``tb/tb_top.sv:1274-1277``). SPEC declares that block a stand-in: "The eFuse
bank model (`efuse_bank_model.sv`) is a reference, simulation-only stand-in for
the real foundry OTP macro ... In a production integration it is replaced by the
actual foundry macro driven by the SHIM"
(``hw/ip/efuse/doc/architecture.adoc:163-170``), and its set-once semantics are
``onwrite = woset`` in the DV RDL ``hw/ip/efuse/dv/models/regs/efuse_bank.rdl:14``. The
``OTP=...`` observations below therefore show that the controller's command did
or did not reach the bank model -- they are **not** proof that a fuse burns in
silicon ([BEHAVIORAL-STUB-DECLARED]). Their log lines are prefixed
``MODEL-BACKED``. These legs are the only end-to-end sequencing check available
in this bench.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_preload_word_at

STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
READ_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR")
READ_DATA = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR")
PROG_TMO = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_BASE_ADDR")
READ_TMO = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")

PROG_DATA = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
PROG_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
PROG_RB = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm")
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
TMO_EN_R = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMOUT_ENABLE_bm")
TMO_CYC_RST_P = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_REQ_TIMEOUT__PROGRAM_REQ_TIMEOUT_CYCLES_reset"
)
TMO_CYC_RST_R = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_reset"
)
REQ_ERR = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_bm")
REQ_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_CLEAR_bm"
)
SENSE_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_SENSE_DONE_bm")
PROG_ADDR_ERR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_PROGRAM_ADDR_ERROR_bm"
)
READ_ADDR_ERR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_READ_ADDR_ERROR_bm"
)

# Word 0 of the eFuse bank MODEL after fuse sense, i.e. word 0 of the preload
# asset the model $readmemh'd at time 0 -- derived from the asset at run time,
# never a hand literal. Model-backed observation, not a silicon claim.
OTP_WORD0_MARKER = efuse_preload_word_at(smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR"))
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
        # Measured words carried by CHK-EFUSE-TMO-BASIC, so the summary
        # token reports what the DUT returned rather than four constants.
        self.prog_tmo_ctrl = None
        self.prog_rec_ctrl = None
        self.read_tmo_data = None
        self.read_ctl_data = None
        self.chk_seen: set[str] = set()

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

    async def _read_no_enable(self, label: str) -> tuple[int, int]:
        """`read_go` with `read_enable` LOW -- the one cause the RDL sanctions.

        `efuse_interface_ctrl.rdl` documents READ_STATUS as "Logic error, assert
        read_go when read is not enabled", and `efuse_read_interface.sv:109-113`
        is the arm that implements it, resolved in `ST_READ_IDLE` before any
        command reaches the bank model. Identical to `_read` except the command
        word omits READ_EN, so the difference between the two is exactly the
        quantity under test.
        """
        await self.csr_write(f"{label}_GO", READ_CTRL, _BIT | READ_GO)
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
        assert otp == OTP_WORD0_MARKER, f"timed-out program sticky-OR OTP: 0x{otp:08x}"
        self.prog_tmo_ok = True
        self.prog_tmo_ctrl = st
        cocotb.log.info(
            "CHK-EFUSE-TMO-PROG: DUT PROGRAM_CTRL=0x%x (PROGRAM_STATUS set by "
            "the timeout FSM) tmo=0x%x; MODEL-BACKED: eFuse bank model word0 "
            "still 0x%x (unburned) -- the bank is efuse_bank_model.sv, a "
            "declared simulation stand-in, so this half is not silicon-path "
            "coverage",
            st,
            got,
            otp,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-PROG")

        st_hold = await self.csr_read("PROG_TMO_HOLD", PROGRAM_CTRL)
        stat_hold = await self.csr_read("STATUS_HOLD", STATUS)
        assert st_hold & PROG_ERR, f"timeout PROGRAM_STATUS not sticky: CTRL=0x{st_hold:x}"
        # PROGRAM_STATUS is live HW from the last op; writing 0 does not clear
        # it. EFUSE_INTERFACE_CTRL_STATUS is asserted per field from the
        # generated header ([EXACT-EXPECTATION]): fuse sense has completed, and
        # a request aborted by the *timeout* counter is neither an eFuse request
        # error nor an address error, so all three error bits must read 0 and
        # SENSE_DONE must read 1.
        assert (stat_hold & SENSE_DONE) == SENSE_DONE, (
            f"STATUS.EFUSE_SENSE_DONE not set after fuse sense: STATUS=0x{stat_hold:x}"
        )
        for _name, _mask in (
            ("EFUSE_REQ_ERROR", REQ_ERR),
            ("EFUSE_PROGRAM_ADDR_ERROR", PROG_ADDR_ERR),
            ("EFUSE_READ_ADDR_ERROR", READ_ADDR_ERR),
        ):
            assert (stat_hold & _mask) == 0, (
                f"STATUS.{_name} set on the program-timeout path "
                f"(STATUS=0x{stat_hold:x}, mask=0x{_mask:x}): the timeout "
                f"counter aborted the request, which is not an error response "
                f"from the eFuse bank"
            )
        cocotb.log.info(
            "CHK-EFUSE-TMO-PROG-SET: PROGRAM_CTRL=0x%x (PROGRAM_STATUS sticky); "
            "STATUS=0x%x with SENSE_DONE(0x%x)=1 and "
            "REQ_ERROR/PROGRAM_ADDR_ERROR/READ_ADDR_ERROR "
            "(0x%x/0x%x/0x%x) all 0, each asserted from the generated header",
            st_hold,
            stat_hold,
            SENSE_DONE,
            REQ_ERR,
            PROG_ADDR_ERR,
            READ_ADDR_ERR,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-PROG-SET")
        await self.csr_write("PROG_TMO_IDLE", PROGRAM_CTRL, 0)
        await self._clear_req_err()

        await self.csr_write("PROG_TMO_DEF", PROG_TMO, TMO_CYC_RST_P)
        st = await self._program("PROG_REC")
        otp = int(dut.tb_efuse_programmed_word0.value)
        assert (st & PROG_ERR) == 0, f"recovery program status=1 CTRL=0x{st:x}"
        assert (otp & 1) == 1, f"recovery did not set bit0 OTP=0x{otp:08x}"
        self.prog_rec_ok = True
        self.prog_rec_ctrl = st
        cocotb.log.info(
            "CHK-EFUSE-TMO-PROG-REC: DUT PROGRAM_CTRL=0x%x (PROGRAM_STATUS "
            "clear with the RDL-default timeout 0x%x); MODEL-BACKED: eFuse "
            "bank model word0 now 0x%x with bit0 set -- burn observed in "
            "efuse_bank_model.sv, a declared simulation stand-in, not silicon",
            st,
            TMO_CYC_RST_P,
            otp,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-PROG-REC")

        await self.csr_write("READ_TMO_SHORT", READ_TMO, TMO_EN_R)
        got = await self.csr_read("READ_TMO_RB", READ_TMO, expected=TMO_EN_R)
        st, data = await self._read("READ_TMO")
        assert st & READ_ERR, f"short read timeout expected READ_STATUS=1 got CTRL=0x{st:x}"
        assert data == 0, f"timed-out read data=0x{data:x} want 0"
        self.read_tmo_ok = True
        self.read_tmo_data = data

        # SAME-CONFIGURATION POSITIVE CONTROL for the `data == 0` above
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]): a dead or unmapped READ_DATA
        # register satisfies `data == 0` on its own. The enable bit stays 1 and
        # only the cycle count changes to the RDL default, so the difference
        # between this read and the one above is exactly the quantity under
        # test.
        tmo_enabled_long = TMO_EN_R | TMO_CYC_RST_R
        await self.csr_write("READ_TMO_EN_LONG", READ_TMO, tmo_enabled_long)
        await self.csr_read("READ_TMO_EN_LONG_RB", READ_TMO, expected=tmo_enabled_long)
        await self._clear_req_err()
        st_ctl, data_ctl = await self._read("READ_TMO_EN_LONG")
        assert (st_ctl & READ_ERR) == 0, (
            f"positive control read (READ_REQ_TIMOUT_ENABLE=1, cycles=RDL "
            f"default 0x{TMO_CYC_RST_R:x}) reported READ_STATUS=1 "
            f"CTRL=0x{st_ctl:x}"
        )
        assert (data_ctl & 1) == 1, (
            f"positive control read returned 0x{data_ctl:x} with bit0 clear: "
            f"with the timeout still ENABLED but given the RDL-default cycle "
            f"count the read must complete and return the burned word, so the "
            f"data==0 result of the short-timeout read above cannot be "
            f"attributed to the timeout"
        )
        self.read_ctl_data = data_ctl
        assert data_ctl != data, (
            f"the short-timeout read and the enabled-long-timeout read both "
            f"returned 0x{data_ctl:x}: READ_DATA does not discriminate the two "
            f"configurations"
        )
        cocotb.log.info(
            "CHK-EFUSE-TMO-RD: with READ_REQ_TIMOUT_ENABLE=1 and cycles=0 the "
            "read aborted and READ_DATA=0x%x (CTRL=0x%x, tmo=0x%x); with the "
            "SAME enable bit set and cycles=RDL default the read completed and "
            "returned 0x%x (CTRL=0x%x, tmo=0x%x) -- so the zero is the "
            "timeout's doing, not a dead READ_DATA register. DUT property: the "
            "abort-vs-complete CONTRAST between the two cycle counts, and the "
            "inequality of the two READ_DATA words. MODEL-BACKED: the specific "
            "completed value (bit0 set) is the word burned into "
            "efuse_bank_model.sv, a declared simulation stand-in, not silicon "
            "-- no claim is made here about what a real eFuse macro returns",
            data,
            st,
            got,
            data_ctl,
            st_ctl,
            tmo_enabled_long,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-RD")

        await self.csr_write("READ_TMO_DEF", READ_TMO, TMO_CYC_RST_R)
        await self._clear_req_err()
        st, data = await self._read("READ_REC")
        assert (st & READ_ERR) == 0, f"recovery read status=1 CTRL=0x{st:x}"
        assert (data & 1) == 1, f"recovery read missed bit0 data=0x{data:x}"
        self.read_rec_ok = True
        cocotb.log.info(
            "CHK-EFUSE-TMO-RD-REC: timeout disabled (READ_TMO=0x%x) -> "
            "READ_CTRL=0x%x READ_DATA=0x%x with bit0 set. DUT property: the "
            "read completes and READ_STATUS stays clear once the timeout is "
            "given the RDL-default cycle count. MODEL-BACKED: bit0 being set "
            "is the burned word from efuse_bank_model.sv, a declared "
            "simulation stand-in, not silicon",
            TMO_CYC_RST_R,
            st,
            data,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-RD-REC")

        # READ_STATUS positive control: the `== 0` READ_STATUS assertions on the
        # enabled reads above cannot on their own distinguish a working status
        # bit from a dead one ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        #
        # Armed by the recovery read immediately above, which proves
        # READ_STATUS == 0 on a *successful* read: `efuse_read_interface.sv:95`
        # defaults `read_err_d = read_err_q`, so the field holds and a stale 1
        # would otherwise satisfy this leg.
        #
        # `efuse_interface_controller.sv:612` gates `read_enable` with
        # `&& ~efuse_req_err`, so a sticky req-err reaches the same
        # `!read_enable_i` branch and would set READ_STATUS for the wrong
        # reason: STATUS is read and REQ_ERROR required clear first.
        stat_pre = await self.csr_read("RD_NOEN_STATUS_PRE", STATUS)
        assert (stat_pre & REQ_ERR) == 0, (
            f"STATUS.EFUSE_REQ_ERROR already set (STATUS=0x{stat_pre:x}) before "
            f"the no-enable read: efuse_interface_controller.sv:612 would route "
            f"that down the same !read_enable branch, so a READ_STATUS=1 below "
            f"could not be attributed to read_enable=0"
        )
        st_noen, data_noen = await self._read_no_enable("READ_NOEN")
        assert (st_noen & READ_ERR) == READ_ERR, (
            f"read_go asserted with read_enable=0 did not set READ_STATUS "
            f"(READ_CTRL=0x{st_noen:x}, mask=0x{READ_ERR:x}); "
            f"efuse_interface_ctrl.rdl documents this as the field's cause and "
            f"efuse_read_interface.sv:109-113 implements it"
        )
        # READ_DATA is not asserted here: the no-enable arm
        # (`efuse_read_interface.sv:109-113`) leaves `read_back_data_d` at its
        # `:98` hold, so the register keeps the previous successful read's word,
        # while the OOB arm (`:114-123`) and the macro-error / secure_tm /
        # req-err arm (`:137-142`) both clear it. Asserting either behaviour
        # here would fail this positive control for a reason other than the
        # property it establishes. The value is logged as an observation.
        cocotb.log.info(
            "CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE: the SAME command word as "
            "the recovery read minus READ_ENABLE(0x%x) gives READ_CTRL=0x%x "
            "with READ_STATUS(0x%x)=1 and READ_DATA=0x%x, against READ_CTRL="
            "0x%x READ_STATUS=0 on the enabled read at the same cycle count. "
            "STATUS=0x%x with REQ_ERROR(0x%x)=0 excludes the sticky-req-err "
            "path to the same branch. DUT property: READ_STATUS discriminates "
            "the two, so the `READ_STATUS == 0` assertions above are "
            "falsifiable. OBSERVED, NOT ASSERTED: READ_DATA holds the previous "
            "read's word rather than being scrubbed as the OOB and reject arms "
            "scrub theirs -- see the comment above",
            READ_EN,
            st_noen,
            READ_ERR,
            data_noen,
            st,
            stat_pre,
            REQ_ERR,
        )
        self.chk_seen.add("CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE")
        await self._clear_req_err()

        # Summary token carrying the measured words, so the line is falsifiable
        # against the per-leg tokens above it ([NO-ALWAYS-PASS-CHECKER]).
        cocotb.log.info(
            "CHK-EFUSE-TMO-BASIC: prog(aborted CTRL=0x%x) prog_rec(CTRL=0x%x) "
            "rd(short-timeout READ_DATA=0x%x vs enabled-long READ_DATA=0x%x) "
            "rd_rec(CTRL=0x%x READ_DATA=0x%x)",
            self.prog_tmo_ctrl,
            self.prog_rec_ctrl,
            self.read_tmo_data,
            self.read_ctl_data,
            st,
            data,
        )
        self.chk_seen.add("CHK-EFUSE-TMO-BASIC")
