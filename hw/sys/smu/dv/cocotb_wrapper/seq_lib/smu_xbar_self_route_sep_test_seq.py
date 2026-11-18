# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_self_route_sep_test. No Force.

``hw/sys/smu/doc/index.adoc`` ("AXI Crossbar", the routing table by initiator
and decoded aperture) answers a ``sep_out`` request that matches the SEP
aperture with DECERR: no initiator is connected to its own subsystem's inbound
port, the crossbar generates the response itself, and the request reaches no
subordinate. The SEP master the bench drives without firmware is the debug
module's system bus (``smu_dtp_sep_dm_sba_test_seq``); the SEP route demux
sends an address inside the aperture ``SEP_GLOBAL_BASE_ADDR`` and
``SEP_REGION_SIZE`` describe to the outbound filter and ``sep_out``
(``hw/sys/sep/doc/fabric.adoc``, the output fabric).

S0..S3 are ``smu_dtp_sep_dm_dmi_test``: TEST_DEV posture, PTAP IDCODE, SEP
STAP selected, debug module active. The outbound filter is then opened over
one page that is neither SEP-local nor in the SMC window. With the SEP
aperture at its reset base the control system-bus write and read of a word in
that page each cross ``smu_axi_out`` and return the written word. With
``SEP_GLOBAL_BASE_ADDR`` moved onto the page, the same write and read each
report a non-zero ``sberror`` (the error the crossbar's DECERR raises at the
debug module; the code is logged), the crossbar accepts both on ``sep_out``
(``sep_smn_out_*_count_o``) and the ``sep_in``, ``smc_in`` and ``ext_out``
taps do not move. The base is restored and the read returns the word again.
"""

from __future__ import annotations

from cocotb.triggers import ClockCycles

from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    EGRESS_ADDR,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    smu_dtp_sep_dm_sba_test_seq,
)

EVIDENCE = "CHK-XBAR-SELF-SEP-DECERR"
# The SEP aperture is moved onto the page the egress control uses, so the same
# word is first a miss column address and then a self-route one.
SELF_BASE = EGRESS_ADDR
SELF_PAGE_END = SELF_BASE + 0xFFF
PROBE_ADDR = SELF_BASE + 0x100
CONTROL_WORD = 0x5E1F_0C1D
SELF_WORD = 0xDEC0_DE5E
SBERROR_NONE = 0
SUBORDINATE_TAPS = (
    "sep_xbar_in_aw_count_o",
    "sep_xbar_in_ar_count_o",
    "smc_xbar_in_aw_count_o",
    "smc_xbar_in_ar_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
SEP_OUT_TAPS = ("sep_smn_out_aw_count_o", "sep_smn_out_ar_count_o")
EGRESS_TAPS = ("smu_axi_out_write_count_o", "smu_axi_out_read_count_o")
TAP_SETTLE_CYCLES = 64
EGRESS_POLL_CYCLES = 4000


class smu_xbar_self_route_sep_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """A sep_out request into the SEP's own aperture answers DECERR at the crossbar."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.done = False

    def _tap(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    def _taps(self, names: tuple[str, ...]) -> dict[str, int]:
        return {name: self._tap(name) for name in names}

    def _deltas(self, names: tuple[str, ...], before: dict[str, int]) -> dict[str, int]:
        return {name: self._tap(name) - before[name] for name in names}

    async def _sba_error(self, jtag, what: str) -> int:
        """Poll sbcs until the system bus is idle; return sberror without raising on it."""
        for _ in range(SBA_POLLS):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if sbcs & SBCS_SBBUSY:
                continue
            return (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        raise AssertionError(f"system-bus {what}: sbbusy never cleared")

    async def _sba_issue_write(self, jtag, addr: int, data: int) -> None:
        """The write of ``_sba_write`` without its wait, so the error code can be read."""
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE)
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        await self._dmi(jtag, SBDATA0_ADDR, data, DMI_OP_WRITE)

    async def _sba_issue_read(self, jtag, addr: int) -> None:
        """The read of ``_sba_read`` without its wait, so the error code can be read."""
        await self._dmi(
            jtag,
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
        )
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        dut = self.dut

        # S4: the outbound filter admits the page; the SEP aperture is at its reset base.
        await self._sba_write(jtag, OUTBOUND_START_ADDR, SELF_BASE)
        await self._sba_write(jtag, OUTBOUND_END_ADDR, SELF_PAGE_END)
        await self._sba_write(jtag, OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN)
        base = await self._port_settles("sep_global_base_o", SEP_GLOBAL_BASE_RESET)
        sb.expect_eq("sep_global_base_o at its RDL reset value", base, SEP_GLOBAL_BASE_RESET)

        # S5: control, the word outside both apertures leaves on smu_axi_out and returns.
        before = self._taps(EGRESS_TAPS)
        await self._sba_write(jtag, PROBE_ADDR, CONTROL_WORD)
        readback = await self._sba_read(jtag, PROBE_ADDR)
        for _ in range(EGRESS_POLL_CYCLES // TAP_SETTLE_CYCLES):
            if all(delta >= 1 for delta in self._deltas(EGRESS_TAPS, before).values()):
                break
            await ClockCycles(dut.clk_smu_i, TAP_SETTLE_CYCLES)
        egress = self._deltas(EGRESS_TAPS, before)
        self._log(
            f"control: system-bus write/read at 0x{PROBE_ADDR:08x} readback=0x{readback:08x} "
            f"smu_axi_out {egress}"
        )
        sb.expect_eq(
            f"a system-bus write and read at 0x{PROBE_ADDR:08x}, outside both apertures, each "
            "cross smu_axi_out once and the read returns the written word",
            (readback, egress),
            (CONTROL_WORD, dict.fromkeys(EGRESS_TAPS, 1)),
            evidence=EVIDENCE,
        )

        # S6: the SEP aperture moved onto the page; the same word is now a self-route.
        await self._sba_write(jtag, SEP_GLOBAL_BASE_ADDR, SELF_BASE)
        base = await self._port_settles("sep_global_base_o", SELF_BASE)
        sb.expect_eq("sep_global_base_o carries the programmed self-route base", base, SELF_BASE)
        before_sub = self._taps(SUBORDINATE_TAPS)
        before_out = self._taps(SEP_OUT_TAPS)
        await self._sba_issue_write(jtag, PROBE_ADDR, SELF_WORD)
        wr_err = await self._sba_error(jtag, f"write 0x{PROBE_ADDR:08x}")
        await self._sba_issue_read(jtag, PROBE_ADDR)
        rd_err = await self._sba_error(jtag, f"read 0x{PROBE_ADDR:08x}")
        await ClockCycles(dut.clk_smu_i, TAP_SETTLE_CYCLES)
        subordinate = self._deltas(SUBORDINATE_TAPS, before_sub)
        sep_out = self._deltas(SEP_OUT_TAPS, before_out)
        self._log(
            f"CHK-XBAR-SELF-SEP-DECERR: system-bus write/read at 0x{PROBE_ADDR:08x} inside the "
            f"SEP aperture at 0x{SELF_BASE:08x} sberror={wr_err}/{rd_err}; sep_out accepts "
            f"{sep_out}; sep_in, smc_in and ext_out taps {subordinate}"
        )
        sb.expect_eq(
            f"CHK-XBAR-SELF-SEP-DECERR the system-bus write and read at 0x{PROBE_ADDR:08x} in "
            f"the SEP's own aperture each report an error (sberror {wr_err} and {rd_err}), the "
            "crossbar accepts both on sep_out, and the sep_in, smc_in and ext_out taps do not "
            "move",
            (wr_err != SBERROR_NONE, rd_err != SBERROR_NONE, sep_out, subordinate),
            (True, True, dict.fromkeys(SEP_OUT_TAPS, 1), dict.fromkeys(SUBORDINATE_TAPS, 0)),
            evidence=EVIDENCE,
        )

        # S7: the base restored, the page is the miss column again.
        await self._sba_write(jtag, SEP_GLOBAL_BASE_ADDR, SEP_GLOBAL_BASE_RESET)
        base = await self._port_settles("sep_global_base_o", SEP_GLOBAL_BASE_RESET)
        again = await self._sba_read(jtag, PROBE_ADDR)
        sb.expect_eq(
            "with the base restored the system-bus read returns the control word with no error",
            (base, again),
            (SEP_GLOBAL_BASE_RESET, CONTROL_WORD),
            evidence=EVIDENCE,
        )
        self.done = True
