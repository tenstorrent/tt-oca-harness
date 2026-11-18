# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Do the OTP bridges still work when the lifecycle posture has closed the fabric one?

The SEP lifecycle specification gates the SMC fabric JTAG2AXI path on Case 2
(``SIP_DBG & CHIPLET_DBG``) and leaves both OTP JTAG2AXIL paths ungated:

* hw/sys/sep/doc/lifecycle_controller.adoc:700 -- "SMC fabric JTAG2AXI path
  |Case 2";
* hw/sys/sep/doc/lifecycle_controller.adoc:714-718 -- "SEP OTP JTAG2AXIL path
  |*Ungated* ... No feature control bit gates it.";
* hw/sys/sep/doc/lifecycle_controller.adoc:723-724 -- "SMC OTP JTAG2AXIL path
  |*Ungated* |Reaches the whole SMC eFuse interface on the same terms";
* hw/sys/sep/doc/lifecycle_controller.adoc:803 -- "DBG_1 and DBG_2 are
  disabled in undemoted PROD and in PROD_END".

The remaining enforcement on the OTP paths is the wrapper access policy, which
the same rows (lifecycle_controller.adoc:718-720, 726-728) and
hw/sys/sep/doc/otp_fuse_controller.adoc:121-125 restrict "in the PROD and
RMA_SIP states" and on an integrity error. PROD_END is not in that list, so
this sequence grades full OTP access in PROD_END on the specification's
enumeration of the restricted states; that the write legs also clear the
per-field ``LOCKS`` rests on the image leaving those lock slots unset, an
observation of the preload rather than a stated value. The other OTP leaves run
with an eFuse image that leaves debug open, so this sequence is the one that
observes an OTP bridge completing while the fabric bridge is shut.

This anchor runs with the PROD_END SEP shadow image, where
seq_lib.smu_lifecycle_table gives ``smc_jtag2axi`` disabled, and then:

* shows the fabric bridge really is shut -- a SINGLE_OP read on the primary
  TAP launches nothing on the DTP -> SMC debug AXI port, and the bridge's own
  SINGLE_OP capture shows the update was never latched;
* drives both OTP bridges to completion over the same TAP in that state, and
  compares what comes back against a value the image or the RDL fixes:
  the SEP eFuse MAP LC_STATE word must read the PROD_END encoding the image
  programmed, and the eFuse bank-control shim CSR must read its RDL reset.

The SEP eFuse bank-control leg is the last step.
hw/sys/sep/doc/otp_fuse_controller.adoc:43-45 states that "Addresses from the
MAP window to the end of the last register window go through the AXI-Lite to
APB bridge, and all others go to the shim's bank control registers", and
hw/sys/smu/doc/port_table.adoc:185 lists ``sep_efuse_bank_ctrl_req_o`` as the
"SEP eFuse bank control AXI-Lite request passthrough" on the SMU boundary. So a
SEP OTP JTAG2AXI access to the shim window is the one stimulus on this bench
that makes the boundary port move without a fuse sense, and its answer comes
back through the same bridge.

Both OTP legs check a value, not just a status: a bridge that returned SUCCESS
with the error slave's 0xbadcab1e, or with a stale capture, fails here.

The fabric deny (CHK-OTP-FABRIC-BLOCKED) grades a reach step, which shows that
the probe's scan path selects the bridge, and four observations of one probe:

* with SMC_AXI_SINGLE_OP in the IR, a non-zero 132-bit pattern and then its
  complement, each followed by 132 zeros, come back on TDO after exactly 132
  bits. hw/ip/jtag/jtag_ptap/doc/architecture.adoc:588 -- "The single-operation
  TDR has `2 + S + D/8 + D + A` bits", which is 2 + 2 + 8 + 64 + 56 = 132 for
  the 56-bit address and 64-bit data of the SMC fabric bridge
  (hw/sys/dtp/doc/jtag.adoc:89-92); hw/sys/dtp/doc/jtag.adoc:175-176 -- "For
  a JTAG2AXI bridge, disabling means TDR update registers are not latched", so
  the shift path stays usable while the bridge is disabled. BYPASS returns the
  pattern after one bit, another register after its own length, and a
  deselected bridge returns nothing, so none of them passes; IDCODE shows the
  TAP is alive, not that this instruction selects this register. The zeros
  leave op 0 in the shift register at Update-DR, which architecture.adoc:619
  defines as "Ignore data and address (nop) Don't send anything over AXI
  during Update-DR", so the scan launches nothing even on an open bridge;
* the bridge's disable input in the PTAP reads 1 before and after the probe.
  hw/ip/jtag/jtag_ptap/doc/architecture.adoc:851-852 -- "when it is 1, the
  corresponding `jtag2axi` instance blocks AXI transaction generation";
* the AW and AR handshake counters on the DTP -> SMC debug port do not move,
  sampled with X/Z failing;
* AWVALID, WVALID and ARVALID on that port are sampled with X/Z failing on
  every clk_smu_i edge from before the probe to the end of the settle window,
  and none is ever high, so a counter that is not wired to the port cannot
  pass;
* the SINGLE_OP capture taken after the window reads op 0 and address 0.
  hw/sys/dtp/doc/jtag.adoc:175-176 -- "For a JTAG2AXI bridge, disabling means
  TDR update registers are not latched"; hw/ip/jtag/jtag_ptap/doc/architecture.adoc
  :615 gives the address field reset 0 and "On a Capture-DR, this field holds
  the previous value"; :619 gives op codes 1 and 2 to a completed AXI
  response and 3 to a request still in progress. A bridge that latched the
  probe captures its non-zero address instead.

PROD_END leaves no open path onto the DTP -> SMC debug port, so the live
control is linked, not in this run. smu_jtag2axi_access_matrix_rand_test
drives this bridge with the gate open through the same driver and encoder
(make_smu_jtag_tap and pack_single_op), waits for the AR and B counters of the
same port to move, and grades the address, size, strobes and data it sees on
the port (CHK-J2AMX-ADDR and its siblings). smu_sep_dbg_gating_test_dev_test
issues an SMC_AXI_SINGLE_OP read with the TEST_DEV image and requires the same
AW/AR counters to move (CHK-SEP-DBG-OPEN); it builds its scan through the
wrapper JTAG driver, so it shows the port opens with the posture, not that
this sequence's encoder reaches the bridge.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_SINGLE_OP_LEN,
    SMC_OTP_AXSIZE_4B,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    pack_otp_single_op,
    pack_single_op,
    require_jtag_tdo_resolved,
    sep_otp_jtag2axi_single_read,
    unpack_otp_single_op,
    unpack_single_op,
)
from seq_lib.smu_lifecycle_table import (
    LC_STATE_PRESENSE,
    lc_raw_from_shadow_preload,
    lc_state_name,
    lc_state_word,
    posture,
)

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEP_ADDR_H = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c" / "sep_addr.h"
_SHIM_CTRL_H = (
    _REPO_ROOT
    / "hw"
    / "ip"
    / "efuse"
    / "dv"
    / "models"
    / "regs"
    / "gen"
    / "c"
    / "efuse_shim_ctrl.h"
)

#: SEP eFuse MAP LC_STATE, the word the shadow image programs.
SEP_EFUSE_LC_STATE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR")
#: SEP eFuse MAP SPARE0, a writable word no other consumer reads.
SEP_EFUSE_SPARE0 = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR")
#: eFuse bank-control shim CSR, outside the MAP/MMR window and therefore on
#: the SMU boundary port.
SEP_EFUSE_SHIM_INIT_TIME = c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_BASE_ADDR"
)
SEP_EFUSE_SHIM_INIT_TIME_RESET = c_header_u32(
    _SHIM_CTRL_H, "EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset"
)

#: SMC eFuse MAP SPARE[0], the word smu_dtp_otp_smc_map_rw_test also uses.
SMC_EFUSE_SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)

#: SMC CPU_CTRL scratch0, SMC-local. A benign always-mapped fabric target; the
#: point is whether the bridge launches, not what it returns.
FABRIC_PROBE_ADDR = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

SEP_SPARE_PATTERN = 0x5A5A_A5A5
SMC_SPARE_PATTERN = 0x1234_ABCD
SHIM_INIT_TIME_PATTERN = 0x0000_0040

OTP_POLL = 128
FABRIC_SETTLE_CYCLES = 4000
#: SMC_AXI_SINGLE_OP address field: bit 76 up, 56 bits (hw/sys/dtp/doc/jtag.adoc:89-92,
#: 56-bit address and 64-bit data).
SINGLE_OP_ADDR_LSB = 76
SINGLE_OP_ADDR_MASK = (1 << 56) - 1
FABRIC_VALIDS = ("dtp_smc_dbg_aw_valid_o", "dtp_smc_dbg_w_valid_o", "dtp_smc_dbg_ar_valid_o")
POSTURE_TIMEOUT_CYCLES = 60000
#: Shift-through pattern for the SINGLE_OP register: bits 0 and 131 set, so a
#: register one bit shorter or longer loses an end bit.
SINGLE_OP_REACH_MASK = (1 << SMC_DBG_SINGLE_OP_LEN) - 1
SINGLE_OP_REACH_PATTERN = (1 << 131) | (0xA5C3_961E_0FF0_3CC3_5A96_E187_D24B_7E81 << 2) | 1


class SmuOtpBridgesUnderDbgDisableSeq:
    """Both OTP bridges complete while the lifecycle posture blocks the fabric bridge."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger

    def _rd(self, name: str, *, allow_xz: bool = False) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on the wrapper tb top")
        return self.test.read_int(pin, name, allow_xz=allow_xz)

    def _dbg_counts(self) -> tuple[int, int]:
        return (
            self._rd("dtp_smc_dbg_aw_count_o"),
            self._rd("dtp_smc_dbg_ar_count_o"),
        )

    def _fabric_valid_pins(self) -> list:
        pins = [getattr(self.dut, name, None) for name in FABRIC_VALIDS]
        missing = [name for name, pin in zip(FABRIC_VALIDS, pins) if pin is None]
        if missing:
            raise AssertionError(f"{missing} unobservable on the wrapper tb top")
        return pins

    async def _watch_fabric_valids(self, pins: list, tally: dict[str, int]) -> None:
        """Count clk_smu_i edges, edges with a VALID high, and edges with a VALID at X/Z."""
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            tally["edges"] += 1
            values = [pin.value for pin in pins]
            if not all(v.is_resolvable for v in values):
                tally["xz"] += 1
            elif any(int(v) for v in values):
                tally["valid"] += 1

    async def _single_op_shift_through(self, jtag, pattern: int) -> int:
        """Shift ``pattern`` then SINGLE_OP-length zeros; return the bits after the first 132.

        The zeros are what the register holds at Update-DR, so the scan
        writes op 0 (nop) whatever the gate does.
        """
        await jtag.shift_ir(DTP_IR_SMC_AXI_SINGLE_OP, back_to_rti=False)
        out = await jtag.shift_dr(pattern, 2 * SMC_DBG_SINGLE_OP_LEN, back_to_rti=True)
        require_jtag_tdo_resolved("SMC_AXI_SINGLE_OP shift-through")
        for _ in range(2):
            await jtag.step_tms(0)
        return (int(out) >> SMC_DBG_SINGLE_OP_LEN) & SINGLE_OP_REACH_MASK

    async def _await_posture_settled(self) -> None:
        """Block until the LCC reflects the shadow image rather than its pre-sense word."""
        for _ in range(POSTURE_TIMEOUT_CYCLES):
            if self._rd("smc_lc_state_in_o", allow_xz=True) != LC_STATE_PRESENSE:
                # Let dbg_disable follow feat_ctrl before anything reads it.
                await ClockCycles(self.dut.clk_smu_i, 200)
                return
            await ClockCycles(self.dut.clk_smu_i, 10)
        raise AssertionError(
            f"lifecycle posture never left its pre-sense value within "
            f"{POSTURE_TIMEOUT_CYCLES} cycles; the SEP shadow image was not applied"
        )

    async def _sep_otp_rd(self, jtag, addr: int, name: str) -> int:
        status, rdata = await sep_otp_jtag2axi_single_read(jtag, addr, poll_limit=OTP_POLL)
        require_jtag_tdo_resolved(f"SEP OTP J2A RD {name}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SEP OTP J2A RD {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        value = int(rdata) & 0xFFFF_FFFF
        self.log.info("SEP OTP J2A RD %s @0x%08x -> 0x%08x SUCCESS", name, addr, value)
        return value

    async def _sep_otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        """SEP OTP SINGLE_OP write; polls the capture until the status leaves BUSY."""
        raw = pack_otp_single_op(J2A_OP_WRITE, addr, data, wstrb=0xF, size=SMC_OTP_AXSIZE_4B)
        await jtag.write("SEP_OTP_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"SEP OTP J2A WR issue {name}")
        await ClockCycles(self.dut.clk_smu_i, 32)
        status = None
        for _ in range(OTP_POLL):
            capt = await jtag.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"SEP OTP J2A WR poll {name}")
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 16)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SEP OTP J2A WR {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.log.info("SEP OTP J2A WR %s @0x%08x data=0x%08x SUCCESS", name, addr, data)

    async def _smc_otp_rd(self, jtag, addr: int, name: str) -> int:
        status, rdata = await otp_jtag2axi_single_read(
            jtag, addr, poll_limit=OTP_POLL, require_complete=True
        )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC OTP J2A RD {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        value = int(rdata) & 0xFFFF_FFFF
        self.log.info("SMC OTP J2A RD %s @0x%08x -> 0x%08x SUCCESS", name, addr, value)
        return value

    async def _smc_otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        status, _ = await otp_jtag2axi_single_write(
            jtag, addr, data, poll_limit=OTP_POLL, require_complete=True
        )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC OTP J2A WR {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.log.info("SMC OTP J2A WR %s @0x%08x data=0x%08x SUCCESS", name, addr, data)

    async def run(self) -> None:
        sb = self.test.env.scoreboard

        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        assert preload is not None, (
            "+sep_shadow_reg_preload is required: it names the lifecycle state under test"
        )
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        want = posture(state)
        assert want.smc_jtag2axi_disabled, (
            f"{state} leaves the SMC fabric JTAG2AXI path open; this anchor needs a state "
            "whose posture closes it, otherwise 'OTP works while the fabric is blocked' "
            "is not the scenario being run"
        )

        await self._await_posture_settled()

        lc_state = self._rd("smc_lc_state_in_o")
        fabric_gated = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self.log.info(
            "posture: %s lc_state=0x%02x smc_jtag2axi_disabled=%d (spec: lc_state=0x%02x "
            "smc_jtag2axi_disabled=%d)",
            state,
            lc_state,
            fabric_gated,
            want.lc_state,
            int(want.smc_jtag2axi_disabled),
        )
        sb.expect_eq(
            f"(lc_state, smc_jtag2axi_disabled) carry the {state} posture",
            (lc_state, fabric_gated),
            (want.lc_state, 1),
            evidence="CHK-OTP-DBG-POSTURE",
        )

        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"TAP not answering: IDCODE 0x{idcode:08x}")

        # The fabric bridge is shut. Without this the OTP results below would be
        # equally consistent with a posture that never closed anything.
        if not FABRIC_PROBE_ADDR & SINGLE_OP_ADDR_MASK:
            raise AssertionError("the fabric probe address must differ from the capture reset 0")
        if SINGLE_OP_REACH_PATTERN.bit_length() != SMC_DBG_SINGLE_OP_LEN:
            raise AssertionError("the reach pattern must set bit 131 of the SINGLE_OP register")
        gate_before = self._rd("tb_smc_jtag2axi_security_disable")
        before_aw, before_ar = self._dbg_counts()
        tally = {"edges": 0, "valid": 0, "xz": 0}
        watcher = cocotb.start_soon(self._watch_fabric_valids(self._fabric_valid_pins(), tally))
        # The complement scan fails a TDO bit the VIP read as 0 from X/Z.
        reach_in = (SINGLE_OP_REACH_PATTERN, SINGLE_OP_REACH_PATTERN ^ SINGLE_OP_REACH_MASK)
        reach_out = [await self._single_op_shift_through(jtag, p) for p in reach_in]
        reach_in_hex = tuple(f"0x{p:033x}" for p in reach_in)
        reach_out_hex = tuple(f"0x{p:033x}" for p in reach_out)
        self.log.info(
            "SMC_AXI_SINGLE_OP shift-through after %d bits: in %s out %s",
            SMC_DBG_SINGLE_OP_LEN,
            reach_in_hex,
            reach_out_hex,
        )
        await jtag.write(
            "SMC_AXI_SINGLE_OP",
            pack_single_op(J2A_OP_READ, FABRIC_PROBE_ADDR, size=SMC_DBG_AXSIZE_4B),
        )
        require_jtag_tdo_resolved("SMC_AXI_SINGLE_OP probe")
        await ClockCycles(self.dut.clk_smu_i, FABRIC_SETTLE_CYCLES)
        watcher.cancel()
        after_aw, after_ar = self._dbg_counts()
        capt = int(await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0))
        require_jtag_tdo_resolved("SMC_AXI_SINGLE_OP capture")
        gate_after = self._rd("tb_smc_jtag2axi_security_disable")
        capt_op, capt_data = unpack_single_op(capt)
        capt_addr = (capt >> SINGLE_OP_ADDR_LSB) & SINGLE_OP_ADDR_MASK
        self.log.info(
            "DTP->SMC debug AXI after a SINGLE_OP read of 0x%08x: gate %d->%d AW %d->%d "
            "AR %d->%d; %d clk_smu_i edges, %d with a VALID high, %d with a VALID at X/Z; "
            "capture op=%d addr=0x%x data=0x%x",
            FABRIC_PROBE_ADDR,
            gate_before,
            gate_after,
            before_aw,
            after_aw,
            before_ar,
            after_ar,
            tally["edges"],
            tally["valid"],
            tally["xz"],
            capt_op,
            capt_addr,
            capt_data,
        )
        sb.expect_eq(
            "SMC fabric bridge refuses the SINGLE_OP while the posture blocks it: "
            f"(shift-through out for in {reach_in_hex}, gate before, gate after, AW delta, "
            "AR delta, VALID edges, X/Z edges, window covered, capture op, capture addr)",
            (
                reach_out_hex,
                gate_before,
                gate_after,
                after_aw - before_aw,
                after_ar - before_ar,
                tally["valid"],
                tally["xz"],
                tally["edges"] >= FABRIC_SETTLE_CYCLES,
                capt_op,
                capt_addr,
            ),
            (reach_in_hex, 1, 1, 0, 0, 0, 0, True, J2A_STATUS_SUCCESS, 0),
            evidence="CHK-OTP-FABRIC-BLOCKED",
        )

        # SMC OTP bridge, same TAP, same gated state.
        await self._smc_otp_wr(jtag, SMC_EFUSE_SPARE0, SMC_SPARE_PATTERN, "SMC_SPARE0")
        smc_rb = await self._smc_otp_rd(jtag, SMC_EFUSE_SPARE0, "SMC_SPARE0")
        sb.expect_eq(
            "SMC OTP bridge write/readback while the fabric bridge is blocked",
            smc_rb,
            SMC_SPARE_PATTERN,
            evidence="CHK-OTP-SMC-RW-WHILE-BLOCKED",
        )

        # SEP OTP bridge: the LC_STATE word the image programmed, read back
        # through the bridge. The expected value is the encoding
        # smu_lifecycle_table derives for the state, so a bridge that returned
        # the error slave's pattern or a stale capture fails here.
        want_lc_word = lc_state_word(lc_raw_from_shadow_preload(str(preload)))
        sep_lc = await self._sep_otp_rd(jtag, SEP_EFUSE_LC_STATE, "SEP_EFUSE_LC_STATE")
        sb.expect_eq(
            "SEP OTP bridge returns the LC_STATE word the shadow image programmed",
            sep_lc & 0xFF,
            want_lc_word,
            evidence="CHK-OTP-SEP-LC-READ-WHILE-BLOCKED",
        )

        await self._sep_otp_wr(jtag, SEP_EFUSE_SPARE0, SEP_SPARE_PATTERN, "SEP_SPARE0")
        sep_rb = await self._sep_otp_rd(jtag, SEP_EFUSE_SPARE0, "SEP_SPARE0")
        sb.expect_eq(
            "SEP OTP bridge write/readback while the fabric bridge is blocked",
            sep_rb,
            SEP_SPARE_PATTERN,
            evidence="CHK-OTP-SEP-RW-WHILE-BLOCKED",
        )

        # The shim window: past the last register window, so it goes to the
        # shim's bank control registers (otp_fuse_controller.adoc:43-45) on the
        # passthrough port that crosses the SMU boundary (port_table.adoc:185).
        shim_reset = await self._sep_otp_rd(jtag, SEP_EFUSE_SHIM_INIT_TIME, "SEP_SHIM_INIT_TIME")
        sb.expect_eq(
            "eFuse bank-control shim CSR reads its RDL reset over the SEP OTP bridge",
            shim_reset,
            SEP_EFUSE_SHIM_INIT_TIME_RESET,
            evidence="CHK-OTP-SEP-BANK-CTRL-READ",
        )
        await self._sep_otp_wr(
            jtag, SEP_EFUSE_SHIM_INIT_TIME, SHIM_INIT_TIME_PATTERN, "SEP_SHIM_INIT_TIME"
        )
        shim_rb = await self._sep_otp_rd(jtag, SEP_EFUSE_SHIM_INIT_TIME, "SEP_SHIM_INIT_TIME")
        sb.expect_eq(
            "eFuse bank-control shim CSR takes a write over the SEP OTP bridge",
            shim_rb,
            SHIM_INIT_TIME_PATTERN,
            evidence="CHK-OTP-SEP-BANK-CTRL-WRITE",
        )
        await self._sep_otp_wr(
            jtag,
            SEP_EFUSE_SHIM_INIT_TIME,
            SEP_EFUSE_SHIM_INIT_TIME_RESET,
            "SEP_SHIM_INIT_TIME restore",
        )

        # The gate has to still be shut at the end, or the OTP completions above
        # cannot be attributed to the blocked-fabric state they were taken in.
        sb.expect_eq(
            "lifecycle posture still blocks the fabric bridge after the OTP traffic",
            self._rd("lcc_dbg_disable_smc_jtag2axi_o"),
            1,
            evidence="CHK-OTP-DBG-POSTURE-HELD",
        )
