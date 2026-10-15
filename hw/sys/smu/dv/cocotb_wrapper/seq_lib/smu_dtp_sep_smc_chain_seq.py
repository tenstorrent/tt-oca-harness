# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""All three subsystems active in one run: SEP decides, DTP enforces, SMC serves.

smu_sep_lcc_flow_test covers the SEP posture alone and smu_sep_dbg_gating_*
covers the DTP gate alone. Here all three subsystems act:

  SMC   firmware boots from ROM and writes its scratch0 marker.
  SEP   firmware (sep_smu_lcc_flow) sets DEMOTE_1/2 -- the one LCC input
        software owns -- which in PROD opens feat_ctrl[15:0] and clears
        dbg_disable.
  DTP   is asked for a JTAG2AXI single-op read of that SMC scratch address; the
        bridge only launches it when dbg_disable.smc_jtag2axi is clear.
  SMC   answers, and the value that comes back up the scan chain is compared
        against what the SMC is actually holding.

Causality comes from running the identical firmware and the identical JTAG
operation under two eFuse images:

  PROD      the per-LC-state feature control profile
            (``hw/sys/sep/doc/lifecycle_controller.adoc``) lets the demote open
            feat_ctrl[15:0], so debug opens and the read must complete and
            return the SMC's live scratch value.
  PROD_END  that profile has no demote entry, so the same demote changes
            nothing, debug stays disabled and the read must not reach AXI at all.

The SEP therefore has to actually participate: with the demote ignored, the
chain breaks. The returned data is compared against the testbench's view of SMC
scratch0, so the check follows whatever the SMC firmware wrote.

The posture after the demote is compared against seq_lib.smu_lifecycle_table:
the state comes from the shadow-preload image the entry names, and the exported
lc_state word and the debug-disable posture must be what the lifecycle
specification gives for that state with both demotes set.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.sep_fw_common import addr_of, load_syms
from seq_lib.smu_addr_map import smc_indexed_addr
from seq_lib.smu_lifecycle_table import lc_raw_from_shadow_preload, lc_state_name, posture
from seq_lib.wrapper_jtag import (
    J2A_OP_READ,
    J2A_SIZE_4B,
    J2A_ST_OKAY,
    J2A_STATUS_NAME,
    PTAP_DEFAULT_IDCODE,
    make_wrapper_ptap,
    require_tdo_resolved,
    single_op_payload,
    single_op_rdata,
    single_op_status,
)

# SMC CPU_CTRL scratch0, SMC-local. The SMC arm firmware writes its marker here,
# so a correct read returns something the SMC put there rather than a reset value.
SMC_SCRATCH0_ADDR = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

PASS_SYM = "sep_smu_lcc_flow_pass_loop"
SETTLE_CYCLES = 2000


class SmuDtpSepSmcChainSeq:
    """SEP sets the posture, DTP gates on it, SMC answers the resulting read."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SMU_DTP_SEP_SMC_CHAIN_OK", "SEP_POSTURE_GOVERNS_DTP_TO_SMC_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    def _rd_resolved(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=False)

    async def _await_sep_demote(self, pass_pc: int, max_cycles: int) -> None:
        """Run until the SEP firmware has finished setting both demotes."""
        for _ in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                if pc == pass_pc:
                    await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)
                    return
        raise AssertionError(
            f"SEP firmware never reached its pass loop 0x{pass_pc:08x} within "
            f"{max_cycles} cycles; the posture was never driven"
        )

    async def _await_smc_marker(self, timeout_cycles: int = 200000) -> int:
        """Wait for the SMC firmware to publish its scratch0 marker.

        The SMC boots from ROM and gets there later than the SEP finishes its
        demote, so the chain has to wait for it. Reading a still-zero scratch
        would also make the later data comparison vacuous -- a JTAG read
        returning 0 would "match" a scratch that was never written.
        """
        for _ in range(timeout_cycles):
            value = self._rd(self.dut.smc_scratch_0_o, "smc_scratch_0_o")
            if value != 0:
                return value
            await ClockCycles(self.dut.clk_smu_i, 20)
        raise AssertionError(
            f"SMC scratch0 stayed 0 for {timeout_cycles} cycles -- the SMC "
            "firmware never ran, so nothing downstream would be attributable to it"
        )

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)

        raw = cocotb.plusargs.get("chain_expect_served")
        assert raw is not None, "+chain_expect_served is required"
        expect_served = bool(int(str(raw), 0))

        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        assert preload is not None, (
            "+sep_shadow_reg_preload is required: it names the lifecycle state under test"
        )
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        want = posture(state, demoted=True)
        assert want.smc_jtag2axi_disabled == (not expect_served), (
            f"+chain_expect_served={int(expect_served)} contradicts the demoted {state} "
            f"posture the specification gives (smc_jtag2axi disabled={want.smc_jtag2axi_disabled})"
        )

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_lcc_flow.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, PASS_SYM)

        self.log.info("=" * 70)
        self.log.info("TEST: DTP-SEP-SMC chain -- SEP decides, DTP enforces, SMC serves")
        self.log.info("=" * 70)

        # 1. SMC: it boots from ROM and lands later than the SEP, so wait for
        #    its marker before anything depends on it.
        await self._await_smc_marker()

        # 2. SEP: run the firmware that drives the posture.
        await self._await_sep_demote(pass_pc, max_cycles)

        lc_state = self._rd_resolved(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        dbg_disable = self._rd_resolved(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        smc_j2a_disabled = bool(
            self._rd_resolved(
                self.dut.lcc_dbg_disable_smc_jtag2axi_o, "lcc_dbg_disable_smc_jtag2axi_o"
            )
        )
        demote1 = self._rd(self.dut.lcc_demote_state_1_o, "lcc_demote_state_1_o")
        smc_scratch = self._rd(self.dut.smc_scratch_0_o, "smc_scratch_0_o")
        self.log.info(
            "after the SEP demote: %s lc_state=0x%02x demote1=%s dbg_disable=0x%04x "
            "smc_jtag2axi_disabled=%s (spec: lc_state=0x%02x all_open=%s "
            "smc_jtag2axi_disabled=%s); SMC scratch0 currently holds 0x%08x",
            state,
            lc_state,
            format(demote1, "#04b"),
            dbg_disable,
            smc_j2a_disabled,
            want.lc_state,
            want.all_open,
            want.smc_jtag2axi_disabled,
            smc_scratch,
        )

        errors: list[str] = []
        if demote1 != 0b01:
            errors.append(
                f"SEP did not assert DEMOTE_1 at the SMU boundary ({demote1:#04b}); "
                "the rest of the chain would not be attributable to the SEP"
            )
        if lc_state != want.lc_state:
            errors.append(
                f"lc_state reads 0x{lc_state:02x}, {state} encodes as 0x{want.lc_state:02x}"
            )
        if want.all_open and dbg_disable != 0:
            errors.append(
                f"the demote should leave every debug path open in {state}, but "
                f"dbg_disable is 0x{dbg_disable:04x}"
            )
        if smc_j2a_disabled != want.smc_jtag2axi_disabled:
            errors.append(
                f"dbg_disable.smc_jtag2axi is {int(smc_j2a_disabled)} after the demote, "
                f"{state} requires {int(want.smc_jtag2axi_disabled)}"
            )
        assert not errors, "DTP-SEP-SMC chain (setup): " + "; ".join(errors)

        # 3. DTP: ask for the read over the primary TAP.
        jtag = make_wrapper_ptap(100)
        await jtag.reset_tap()
        idcode = await jtag.read_idcode()
        require_tdo_resolved("IDCODE")
        assert idcode == PTAP_DEFAULT_IDCODE, f"TAP not answering (0x{idcode:08x})"

        before_ar = self._rd(self.dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o")
        await jtag.write(
            "SMC_AXI_SINGLE_OP",
            single_op_payload(J2A_OP_READ, SMC_SCRATCH0_ADDR, size=J2A_SIZE_4B),
        )
        await ClockCycles(self.dut.clk_smu_i, 4000)
        after_ar = self._rd(self.dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o")

        # 4. SMC: capture whatever came back.
        captured = int(await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0))
        require_tdo_resolved("SINGLE_OP capture")
        status = single_op_status(captured)
        rdata = single_op_rdata(captured)
        launched = after_ar > before_ar
        self.log.info(
            "JTAG2AXI read of 0x%08x: launched=%s (AR %d->%d) status=%s rdata=0x%016x",
            SMC_SCRATCH0_ADDR,
            launched,
            before_ar,
            after_ar,
            J2A_STATUS_NAME.get(status, status),
            rdata,
        )

        if expect_served:
            if not launched:
                errors.append(
                    "debug should be open after the SEP demote, but the bridge "
                    "launched nothing on the DTP->SMC port"
                )
            elif status != J2A_ST_OKAY:
                errors.append(
                    f"the read reached the SMC but came back {J2A_STATUS_NAME.get(status, status)}"
                )
            elif (rdata & 0xFFFF_FFFF) != smc_scratch:
                errors.append(
                    f"the read returned 0x{rdata & 0xFFFF_FFFF:08x} but the SMC is "
                    f"holding 0x{smc_scratch:08x}; the data did not come from the SMC"
                )
        else:
            if launched:
                errors.append(
                    "the demote is ignored in this state, so debug should stay "
                    "disabled -- but the bridge still launched a transaction"
                )

        assert not errors, "DTP-SEP-SMC chain: " + "; ".join(errors)

        if expect_served:
            self.log.info(
                "CHK-DTP-SEP-SMC-CHAIN: PASS (%s: SEP demote -> dbg_disable 0x%04x, every "
                "path open -> DTP launched the read -> SMC answered OKAY with 0x%08x, "
                "matching the value the SMC firmware wrote)",
                state,
                dbg_disable,
                rdata & 0xFFFF_FFFF,
            )
        else:
            self.log.info(
                "CHK-DTP-SEP-SMC-CHAIN-BLOCKED: PASS (%s: same firmware and same JTAG "
                "operation, but this state ignores the demote: dbg_disable=0x%04x with "
                "smc_jtag2axi disabled, and the bridge launched nothing)",
                state,
                dbg_disable,
            )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
