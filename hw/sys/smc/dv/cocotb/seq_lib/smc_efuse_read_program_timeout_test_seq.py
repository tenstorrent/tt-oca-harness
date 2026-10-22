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
(``tb/tb_top.sv``). SPEC declares that block a stand-in: "The eFuse bank model
(`efuse_bank_model.sv`) is a reference, simulation-only stand-in for the real
foundry OTP macro ... In a production integration it is replaced by the actual
foundry macro driven by the SHIM" (``hw/ip/efuse/doc/architecture.adoc``, eFuse
Bank Model), and its set-once semantics are ``onwrite = woset`` in the DV RDL
``hw/ip/efuse/dv/models/regs/efuse_bank.rdl``. The ``OTP=...`` observations
below therefore show that the controller's command did or did not reach the
bank model -- they are **not** proof that a fuse burns in silicon
([BEHAVIORAL-STUB-DECLARED]). Their log lines are prefixed
``MODEL-BACKED``. These legs are the only end-to-end sequencing check available
in this bench.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import efuse_ifc_u32, smc_addr, smc_efuse_map_u32, smc_indexed_addr
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

PROG_BUSY = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_BUSY_bm")
READ_BUSY = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_BUSY_bm")
PROG_ADDR_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_PROGRAM_ADDR_ERROR_CLEAR_bm"
)
READ_ADDR_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_READ_ADDR_ERROR_CLEAR_bm"
)
STATUS_ERRORS = REQ_ERR | PROG_ADDR_ERR | READ_ADDR_ERR

# Fuse bit address of a SMC_EFUSE_MAP byte: map word n is preload word n, which
# holds fuse bits 32n..32n+31 (smc_efuse_vip_utils preload layout).
EFUSE_MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
LOCKS_ADDR = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
SPARE4_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 4)
SPARE27_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 27)
SPARE0_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
SPARE4_WLOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE4_WRITE_LOCK_bm")
SPARE4_RLOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE4_READ_LOCK_bm")
SPARE27_WLOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE27_WRITE_LOCK_bm")
SPARE27_RLOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE27_READ_LOCK_bm")

#: Bit addresses of SMC_COV_B4_010: 0xFFFF is out of range under every reading;
#: 0x2000 and 0x6000 are measured only, and 0x1FFF is the last bit of the
#: 8192-bit reading (SF-025).
OOR_ADDR = 0xFFFF
OOR_EXTRA = (0x2000, 0x6000)
LAST_IN_RANGE = 0x1FFF
#: Word w of the S7 upper-ones read: the first word of SPARE[0], unlocked here.
ONES_WORD_BIT = (SPARE0_ADDR - EFUSE_MAP_BASE) * 8
UPPER_ONES = (29, 30, 31)
UPPER_ONES_MASK = sum(1 << b for b in UPPER_ONES)
SPARE4_BIT = (SPARE4_ADDR - EFUSE_MAP_BASE) * 8
WORD_MASK = 0xFFFF_FFFF

FENCE = (
    "EXISTING-TIMEOUT-LEGS",
    "OOR-PROG",
    "PROG-CLEAR",
    "OOR-READ",
    "READ-CLEAR",
    "LAST-IN-RANGE",
    "UPPER-ONES",
    "WRITE-LOCKS",
    "READ-LOCKS",
)


@dataclass
class _BoundedWait:
    """One bounded poll: its bound, whether expiry is tolerated, and what it last saw."""

    name: str
    bound: int
    unit: str
    allow_timeout: bool = False
    timed_out: bool = False
    used: int = 0
    last: str = "not sampled"


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
        self.waits: list[_BoundedWait] = []
        self.axi_items: list[SmcSysAxiItem] = []
        self.fence: list[tuple[str, int, int]] = []

    async def finish_item(self, item) -> None:
        await super().finish_item(item)
        self.axi_items.append(item)

    def _stamp(self, term: str) -> None:
        """Close fence term ``term``; its count is the SEP_IN accesses issued since the last term."""
        count = len(self.axi_items) - sum(c for _t, c, _ns in self.fence)
        self.fence.append((term, count, int(get_sim_time("ns"))))

    async def _poll(self, wait: _BoundedWait, addr: int, done: Callable[[int], bool]) -> int:
        """Read ``addr`` until ``done`` holds, at most ``wait.bound`` reads."""
        self.waits.append(wait)
        value = 0
        for i in range(wait.bound):
            value = await self.csr_read(wait.name, addr)
            wait.used = i + 1
            wait.last = f"0x{value:08x}"
            if done(value):
                cocotb.log.info(
                    "WAIT %s: bound=%d %s allow_timeout=%s timed_out=%s used=%d last=%s",
                    wait.name,
                    wait.bound,
                    wait.unit,
                    wait.allow_timeout,
                    wait.timed_out,
                    wait.used,
                    wait.last,
                )
                return value
            await RisingEdge(cocotb.top.clk_smc_i)
        wait.timed_out = True
        cocotb.log.info(
            "WAIT %s: expired after bound=%d %s allow_timeout=%s timed_out=%s last=%s",
            wait.name,
            wait.bound,
            wait.unit,
            wait.allow_timeout,
            wait.timed_out,
            wait.last,
        )
        if not wait.allow_timeout:
            raise AssertionError(
                f"{wait.name}: condition not met within {wait.bound} {wait.unit}; "
                f"last observed {wait.last}"
            )
        return value

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
        read_go when read is not enabled", and `efuse_read_interface.sv`
        resolves that arm in `ST_READ_IDLE` before any command reaches the bank
        model. Identical to `_read` except the command word omits READ_EN, so
        the difference between the two is exactly the quantity under test.
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
        # READ_STATUS == 0 on a *successful* read: `efuse_read_interface.sv`
        # defaults `read_err_d = read_err_q`, so the field holds and a stale 1
        # would otherwise satisfy this leg.
        #
        # `efuse_interface_controller.sv` gates `read_enable` with
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
        # READ_DATA is not asserted here: the no-enable arm of
        # `efuse_read_interface.sv` holds `read_back_data_d`, so the register
        # keeps the previous successful read's word, while the OOB arm and the
        # macro-error / secure_tm / req-err arm both clear it. The value is
        # logged as an observation.
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

        await self._range_legs()

    async def _status(self, label: str) -> int:
        return await self.csr_read(label, STATUS)

    async def _prog_cmd(self, label: str, addr: int, complete: bool) -> tuple[int, int]:
        """Program ``addr`` with efuse_data 1; poll busy low (and done high when ``complete``)."""
        await self.csr_write(f"{label}_GO", PROGRAM_CTRL, addr | PROG_DATA | PROG_GO | PROG_EN)

        def want(v: int) -> bool:
            return not v & PROG_BUSY and (not complete or bool(v & PROG_DONE))

        ctrl = await self._poll(_BoundedWait(f"{label}_BUSY", _POLL, "polls"), PROGRAM_CTRL, want)
        return ctrl, await self._status(f"{label}_STATUS")

    async def _read_cmd(self, label: str, addr: int, complete: bool) -> tuple[int, int]:
        """Read ``addr``; poll busy low (and done high when ``complete``)."""
        await self.csr_write(f"{label}_GO", READ_CTRL, addr | READ_GO | READ_EN)

        def want(v: int) -> bool:
            return not v & READ_BUSY and (not complete or bool(v & READ_DONE))

        ctrl = await self._poll(_BoundedWait(f"{label}_BUSY", _POLL, "polls"), READ_CTRL, want)
        return ctrl, await self._status(f"{label}_STATUS")

    async def _read_locks(self, label: str) -> int:
        lo = await self.csr_read(f"{label}_LO", LOCKS_ADDR)
        hi = await self.csr_read(f"{label}_HI", LOCKS_ADDR + 4)
        return ((hi & WORD_MASK) << 32) | (lo & WORD_MASK)

    async def _shadow_read(self, label: str, addr: int) -> SmcSysAxiItem:
        """SEP_IN read that must complete within the agent bound; any RRESP is recorded."""
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        bound = item.timeout_ns or self.cfg.axi_timeout_ns
        cocotb.log.info(
            "WAIT %s: bound=%d ns allow_timeout=%s timed_out=%s resp=%s",
            label,
            bound,
            item.allow_timeout,
            item.timed_out,
            item.resp_code,
        )
        assert not item.timed_out and item.resp_code is not None, (
            f"{label} @ 0x{addr:08x}: no response within {bound} ns "
            f"(timed_out={item.timed_out}, resp={item.resp_code})"
        )
        return item

    async def _range_legs(self) -> None:
        # S1: the existing legs left both timeout registers at their RDL reset and
        # every STATUS error bit clear.
        await self.csr_read("S1_PROG_TMO", PROG_TMO, expected=TMO_CYC_RST_P)
        await self.csr_read("S1_READ_TMO", READ_TMO, expected=TMO_CYC_RST_R)
        st = await self._status("S1_STATUS")
        assert st & STATUS_ERRORS == 0, f"S1: STATUS=0x{st:x} has an error bit in 6:4 set"
        cocotb.log.info("STEP S1: STATUS=0x%x, bits 6:4 clear; timeout registers at reset", st)
        self._stamp("EXISTING-TIMEOUT-LEGS")

        # S2: out-of-range program at 0xFFFF.
        ctrl, st = await self._prog_cmd("S2_OOR_PROG", OOR_ADDR, complete=False)
        pctrl = await self.csr_read("S2_OOR_PROG_CTRL", PROGRAM_CTRL)
        assert st & PROG_ADDR_ERR, (
            f"S2: program at 0x{OOR_ADDR:x} left efuse_program_addr_error clear "
            f"(STATUS=0x{st:x}, PROGRAM_CTRL=0x{pctrl:x})"
        )
        cocotb.log.info(
            "STEP S2: program 0x%x -> STATUS=0x%x PROGRAM_CTRL=0x%x program_status=%d "
            "program_done=%d (measured, SF-027)",
            OOR_ADDR,
            st,
            pctrl,
            int(bool(pctrl & PROG_ERR)),
            int(bool(pctrl & PROG_DONE)),
        )
        self._stamp("OOR-PROG")

        # S3: W1P clear, then an in-range program of bit 0.
        await self.csr_write("S3_CLR", STATUS, PROG_ADDR_ERR_CLR)
        st_clr = await self._status("S3_STATUS_CLR")
        assert st_clr & PROG_ADDR_ERR == 0, (
            f"S3: efuse_program_addr_error still set after the bit-9 W1P write (STATUS=0x{st_clr:x})"
        )
        await self.csr_write("S3_IDLE", PROGRAM_CTRL, 0)
        ctrl0, st0 = await self._prog_cmd("S3_PROG0", _BIT, complete=True)
        assert st0 & PROG_ADDR_ERR == 0, (
            f"S3: in-range program of bit {_BIT} set efuse_program_addr_error "
            f"(STATUS=0x{st0:x}, PROGRAM_CTRL=0x{ctrl0:x})"
        )
        await self.csr_write("S3_PROG0_IDLE", PROGRAM_CTRL, 0)
        cocotb.log.info(
            "STEP S3: after clear STATUS=0x%x; in-range program bit %d PROGRAM_CTRL=0x%x STATUS=0x%x",
            st_clr,
            _BIT,
            ctrl0,
            st0,
        )
        self._stamp("PROG-CLEAR")

        extra_prog = []
        for addr in OOR_EXTRA:
            ctrl, st = await self._prog_cmd(f"S2_PROG_{addr:x}", addr, complete=False)
            extra_prog.append((addr, int(bool(st & PROG_ADDR_ERR)), st, ctrl))
            await self.csr_write(f"S2_PROG_{addr:x}_CLR", STATUS, PROG_ADDR_ERR_CLR)
            await self.csr_write(f"S2_PROG_{addr:x}_IDLE", PROGRAM_CTRL, 0)
        cocotb.log.info(
            "CHK-EFUSE-OOR-PROG: addr 0x%04X err=1; clear -> 0; in-range -> 0; %s logged "
            "(measured, LINKED-ISSUE SF-025/SF-027; 0xFFFF PROGRAM_CTRL=0x%x)",
            OOR_ADDR,
            " ".join(
                f"0x{a:04X} err={e} (STATUS=0x{s:x} CTRL=0x{c:x})" for a, e, s, c in extra_prog
            ),
            pctrl,
        )
        self.chk_seen.add("CHK-EFUSE-OOR-PROG")

        # S4: out-of-range read at 0xFFFF.
        ctrl, st = await self._read_cmd("S4_OOR_READ", OOR_ADDR, complete=False)
        rctrl = await self.csr_read("S4_OOR_READ_CTRL", READ_CTRL)
        assert st & READ_ADDR_ERR and rctrl & READ_ERR, (
            f"S4: read at 0x{OOR_ADDR:x} gave STATUS=0x{st:x} READ_CTRL=0x{rctrl:x}; "
            f"efuse_read_addr_error and read_status must both read 1"
        )
        cocotb.log.info("STEP S4: read 0x%x -> STATUS=0x%x READ_CTRL=0x%x", OOR_ADDR, st, rctrl)
        self._stamp("OOR-READ")

        # S5: W1P clear, then an in-range read of bit 0.
        await self.csr_write("S5_CLR", STATUS, READ_ADDR_ERR_CLR)
        st_clr = await self._status("S5_STATUS_CLR")
        assert st_clr & READ_ADDR_ERR == 0, (
            f"S5: efuse_read_addr_error still set after the bit-10 W1P write (STATUS=0x{st_clr:x})"
        )
        await self.csr_write("S5_IDLE", READ_CTRL, 0)
        ctrl0, st0 = await self._read_cmd("S5_READ0", _BIT, complete=True)
        assert st0 & READ_ADDR_ERR == 0, (
            f"S5: in-range read of bit {_BIT} set efuse_read_addr_error "
            f"(STATUS=0x{st0:x}, READ_CTRL=0x{ctrl0:x})"
        )
        await self.csr_write("S5_READ0_IDLE", READ_CTRL, 0)
        cocotb.log.info(
            "STEP S5: after clear STATUS=0x%x; in-range read bit %d READ_CTRL=0x%x STATUS=0x%x",
            st_clr,
            _BIT,
            ctrl0,
            st0,
        )
        self._stamp("READ-CLEAR")

        extra_read = []
        for addr in OOR_EXTRA:
            ctrl, st = await self._read_cmd(f"S4_READ_{addr:x}", addr, complete=False)
            extra_read.append((addr, int(bool(st & READ_ADDR_ERR)), st, ctrl))
            await self.csr_write(f"S4_READ_{addr:x}_CLR", STATUS, READ_ADDR_ERR_CLR)
            await self.csr_write(f"S4_READ_{addr:x}_IDLE", READ_CTRL, 0)
        cocotb.log.info(
            "CHK-EFUSE-OOR-READ: addr 0x%04X err=1 read_status=1; clear -> 0; in-range -> 0; "
            "%s logged (measured, LINKED-ISSUE SF-025)",
            OOR_ADDR,
            " ".join(
                f"0x{a:04X} err={e} (STATUS=0x{s:x} CTRL=0x{c:x})" for a, e, s, c in extra_read
            ),
        )
        self.chk_seen.add("CHK-EFUSE-OOR-READ")

        # S6: last in-range bit address, program then read.
        pctrl, pst = await self._prog_cmd("S6_PROG_LAST", LAST_IN_RANGE, complete=True)
        await self.csr_write("S6_PROG_LAST_CLR", STATUS, PROG_ADDR_ERR_CLR)
        await self.csr_write("S6_PROG_LAST_IDLE", PROGRAM_CTRL, 0)
        rctrl, rst = await self._read_cmd("S6_READ_LAST", LAST_IN_RANGE, complete=True)
        await self.csr_write("S6_READ_LAST_CLR", STATUS, READ_ADDR_ERR_CLR)
        await self.csr_write("S6_READ_LAST_IDLE", READ_CTRL, 0)
        cocotb.log.info(
            "CHK-EFUSE-LAST-IN-RANGE: addr 0x%04X program err=%d read err=%d, both completed "
            "(PROGRAM_CTRL=0x%x STATUS=0x%x; READ_CTRL=0x%x STATUS=0x%x; measured, "
            "LINKED-ISSUE SF-025)",
            LAST_IN_RANGE,
            int(bool(pst & PROG_ADDR_ERR)),
            int(bool(rst & READ_ADDR_ERR)),
            pctrl,
            pst,
            rctrl,
            rst,
        )
        self.chk_seen.add("CHK-EFUSE-LAST-IN-RANGE")
        self._stamp("LAST-IN-RANGE")

        # S7: burn bits 29..31 of word w, then read the word back twice.
        for b in UPPER_ONES:
            ctrl, st = await self._prog_cmd(f"S7_PROG_{b}", ONES_WORD_BIT + b, complete=True)
            assert ctrl & PROG_ERR == 0 and st & STATUS_ERRORS == 0, (
                f"S7: program of bit 0x{ONES_WORD_BIT + b:x} failed "
                f"(PROGRAM_CTRL=0x{ctrl:x}, STATUS=0x{st:x})"
            )
            await self.csr_write(f"S7_PROG_{b}_IDLE", PROGRAM_CTRL, 0)
        rctrl, _st = await self._read_cmd("S7_READ", ONES_WORD_BIT, complete=True)
        assert rctrl & READ_ERR == 0, f"S7: read_status set (READ_CTRL=0x{rctrl:x})"
        dout = await self.csr_read("S7_DOUT", READ_DATA)
        for i in range(3):
            await self._status(f"S7_STATUS_{i}")
        dout2 = await self.csr_read("S7_DOUT_AGAIN", READ_DATA)
        await self.csr_write("S7_READ_IDLE", READ_CTRL, 0)
        assert dout & UPPER_ONES_MASK == UPPER_ONES_MASK, (
            f"S7: READ_DATA=0x{dout:08x} for bit address 0x{ONES_WORD_BIT:x}; bits 31:29 not 0b111"
        )
        assert dout2 == dout, f"S7: READ_DATA re-read 0x{dout2:08x} differs from 0x{dout:08x}"
        cocotb.log.info(
            "CHK-EFUSE-RDATA-UPPER-ONES: dout=0x%08x [31:29]=0b%s, re-read identical "
            "(word bit address 0x%x, READ_CTRL=0x%x; bits per read and alignment SF-031)",
            dout,
            format((dout >> UPPER_ONES[0]) & 0b111, "03b"),
            ONES_WORD_BIT,
            rctrl,
        )
        self.chk_seen.add("CHK-EFUSE-RDATA-UPPER-ONES")
        self._stamp("UPPER-ONES")

        # S8: write locks on slots 8 and 31; a write of 0 must not clear them.
        wlocks = SPARE4_WLOCK | SPARE27_WLOCK
        await self.csr_write("S8_LOCKS_SET", LOCKS_ADDR, wlocks, length=8)
        set_rb = await self._read_locks("S8_LOCKS_SET_RB")
        await self.csr_write("S8_LOCKS_ZERO", LOCKS_ADDR, 0, length=8)
        zero_rb = await self._read_locks("S8_LOCKS_ZERO_RB")
        assert set_rb & wlocks == wlocks, f"S8: LOCKS=0x{set_rb:016x} after setting 0x{wlocks:x}"
        assert zero_rb & wlocks == wlocks, (
            f"S8: LOCKS=0x{zero_rb:016x} after writing 0; RW1S bits 0x{wlocks:x} cleared"
        )
        ctrl, st = await self._prog_cmd("S8_PROG_SPARE4", SPARE4_BIT, complete=False)
        await self.csr_write("S8_REQ_ERR_CLR", STATUS, REQ_ERR_CLR)
        await self.csr_write("S8_PROG_IDLE", PROGRAM_CTRL, 0)
        st_after = await self._status("S8_STATUS_AFTER_CLR")
        cocotb.log.info(
            "CHK-EFUSE-GUARD-HI-WRITE: lock bits %d/%d set=1, after write 0 still 1; "
            "req_error after SPARE4 program=%d (bit address 0x%x, PROGRAM_CTRL=0x%x "
            "STATUS=0x%x, after clear 0x%x; LOCKS 0x%016x / 0x%016x; measured, "
            "LINKED-ISSUE SF-028)",
            SPARE4_WLOCK.bit_length() - 1,
            SPARE27_WLOCK.bit_length() - 1,
            int(bool(st & REQ_ERR)),
            SPARE4_BIT,
            ctrl,
            st,
            st_after,
            set_rb,
            zero_rb,
        )
        self.chk_seen.add("CHK-EFUSE-GUARD-HI-WRITE")
        self._stamp("WRITE-LOCKS")

        # S9: read locks on slots 8 and 31, then read both shadow registers.
        rlocks = SPARE4_RLOCK | SPARE27_RLOCK
        await self.csr_write("S9_LOCKS_SET", LOCKS_ADDR, rlocks, length=8)
        rd_rb = await self._read_locks("S9_LOCKS_SET_RB")
        assert rd_rb & rlocks == rlocks, f"S9: LOCKS=0x{rd_rb:016x} after setting 0x{rlocks:x}"
        sp4 = await self._shadow_read("S9_SPARE4", SPARE4_ADDR)
        sp27 = await self._shadow_read("S9_SPARE27", SPARE27_ADDR)
        cocotb.log.info(
            "CHK-EFUSE-GUARD-HI-READ: read locks %d/%d = 1; SPARE4 resp=%d data=0x%08x; "
            "SPARE27 resp=%d data=0x%08x (LOCKS 0x%016x; measured, LINKED-ISSUE SF-029/SF-028)",
            SPARE4_RLOCK.bit_length() - 1,
            SPARE27_RLOCK.bit_length() - 1,
            sp4.resp_code,
            sp4.rdata & WORD_MASK,
            sp27.resp_code,
            sp27.rdata & WORD_MASK,
            rd_rb,
        )
        self.chk_seen.add("CHK-EFUSE-GUARD-HI-READ")
        self._stamp("READ-LOCKS")

        self._timeout_paths()
        self._nonvac()

    def _timeout_paths(self) -> None:
        bounds = sorted({item.timeout_ns or self.cfg.axi_timeout_ns for item in self.axi_items})
        axi_allow = sum(1 for item in self.axi_items if item.allow_timeout)
        axi_expired = sum(1 for item in self.axi_items if item.timed_out)
        expired = [w.name for w in self.waits if w.timed_out]
        tolerant = [w.name for w in self.waits if w.allow_timeout]
        assert self.waits, "no bounded waits recorded"
        assert not expired and not tolerant and not axi_expired and not axi_allow, (
            f"bounded waits expired {expired} / tolerating expiry {tolerant}; SEP_IN accesses "
            f"expired {axi_expired} / tolerating expiry {axi_allow}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired: %s; "
            "%d SEP_IN accesses bound %s ns allow_timeout=%d timed_out=%d; expiry raises "
            "AssertionError with the last observed state",
            len(self.waits),
            len(expired),
            "; ".join(
                f"{w.name} bound={w.bound} {w.unit} allow_timeout={w.allow_timeout} "
                f"timed_out={w.timed_out} used={w.used} last={w.last}"
                for w in self.waits
            ),
            len(self.axi_items),
            bounds,
            axi_allow,
            axi_expired,
        )
        self.chk_seen.add("CHK-TIMEOUT-PATHS")

    def _nonvac(self) -> None:
        terms = [t for t, _c, _ns in self.fence]
        assert terms == list(FENCE), f"fence terms {terms}, want {list(FENCE)}"
        zero = [t for t, c, _ns in self.fence if c <= 0]
        assert not zero, f"fence terms with zero count {zero}"
        times = [ns for _t, _c, ns in self.fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing {times}"
        cocotb.log.info(
            "CHK-NONVAC: %s (%s)",
            " < ".join(FENCE),
            ", ".join(f"{t} count={c} t={ns}ns" for t, c, ns in self.fence),
        )
        self.chk_seen.add("CHK-NONVAC")
