# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse reset_n = sense && rst_ni && ext_boot_seq_done_i; fuse_reset_n is 16-stage. Requires +smc_hold_ext_boot. No Force.

Expected-value provenance:

* ``LOCKS`` -- read from ``hw/sys/smc/dv/assets/smc_efuse_default.hex`` at run
  time via ``efuse_preload_word_at`` rather than a hand-transcribed literal,
  which cannot detect the asset and the model disagreeing. That asset is what
  ``efuse_bank_model.sv:140-160`` ``$readmemh``s under the bench-wide
  ``+smc_efuse_hex`` (``smc_sim_cfg.toml:132-134``), so this leg's proof class
  is **transport** (the map returns the sensed word), not fuse programming
  ([NO-UNJUSTIFIED-PRELOAD]).
* ``EFUSE_PROGRAM_INTERFACE_READ_DATA`` -- the generated RDL reset
  ``EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_INTERFACE_READ_DATA__DOUT_reset``
  (``hw/ip/efuse/regs/gen/c/efuse_interface_ctrl.h:153``); no program read-back
  has been issued in this testcase, so the register must still hold it. That
  reset is ``0x0`` and the field is ``sw = r``, so this compare is a
  transport/decode probe and **not** a liveness proof: a dead or unmapped
  window satisfies it equally. Since the field is driven only in the program
  FSM's ``ST_CAPTURE_DATA`` state ("Hardware debug only",
  ``efuse_interface_ctrl.rdl:158``), which this testcase never enters, no
  distinguishing value can be placed in it. Block liveness is instead proven
  on the writable sibling ``EFUSE_READ_REQ_TIMEOUT`` @0x14 (``sw=rw``,
  ``rdl:180``, non-zero reset ``0x800000``) by a reset read plus a
  write/read-back/restore in the same run ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
* ``SCRATCH_COLD_WARM_0`` -- its own reset value 0, backed in the same run by a
  write/read-back positive control proving the register can hold a one
  ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_preload_word_at

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
LOCKS_PRELOAD = efuse_preload_word_at(LOCKS)
PROG_IF_RD = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_INTERFACE_READ_DATA_BASE_ADDR")
PROG_IF_RD_RESET = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_INTERFACE_READ_DATA__DOUT_reset"
)
# `PROG_IF_RD` is `sw = r; hw = w` (efuse_interface_ctrl.rdl:160-163) with a
# generated reset of 0x0, so an `expected=PROG_IF_RD_RESET` compare is also
# satisfied by a dead or unmapped register; the module docstring gives the
# provenance. Block liveness is proven on the writable sibling
# EFUSE_READ_REQ_TIMEOUT @0x14 (`sw=rw`, rdl:180, non-zero reset)
# ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
READ_REQ_TMO = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
READ_REQ_TMO_CYCLES_RESET = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_reset"
)
READ_REQ_TMO_CYCLES_BM = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_bm"
)
# Alternating-bit probe inside the 28-bit cycles field: a stuck-at-0,
# stuck-at-1 or reset-only window cannot read this back.
READ_REQ_TMO_PROBE = 0x0A5A_5A5A & READ_REQ_TMO_CYCLES_BM
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# Positive-control pattern for SCRATCH_COLD_WARM_0: alternating bits so a
# stuck-at-0 or stuck-at-1 register cannot read it back.
SCRATCH_PROBE_PATTERN = 0x5A5A_A5A5
# 16-stage fuse_reset_n pipe + margin. Stay-low after sense must cover this
# or a released ext_boot would already have raised tb_fuse_reset_n.
_PIPE_STAY = 24
_SENSE_BOUND = 200_000
_RELEASE_BOUND = 256


class smc_efuse_boundary_signals_test_seq(SmcCsrSeq):
    """ext_boot hold keeps fuse_reset_n low after sense; release raises it."""

    def __init__(self, name: str = "smc_efuse_boundary_signals_test_seq") -> None:
        super().__init__(name)
        self.hold_ok = False
        self.map_ok = False
        self.release_ok = False
        self.chk_seen: set[str] = set()

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        assert hasattr(dut, "tb_hold_ext_boot"), "tb_hold_ext_boot missing"
        assert int(dut.tb_hold_ext_boot.value) == 1, (
            "+smc_hold_ext_boot required so ext_boot_seq_done stays 0 from t=0"
        )

        last_sense = last_frst = None
        for cycle in range(_SENSE_BOUND):
            await RisingEdge(clk)
            last_sense = int(dut.tb_fuse_sense_done.value)
            last_frst = int(dut.tb_fuse_reset_n.value)
            if last_frst != 0:
                raise AssertionError(
                    f"HOLD: tb_fuse_reset_n rose at cycle {cycle} while "
                    f"ext_boot held (sense={last_sense})"
                )
            if last_sense == 1:
                break
        else:
            raise AssertionError(
                f"HOLD: tb_fuse_sense_done never rose in {_SENSE_BOUND} clocks "
                f"last_sense={last_sense} last_frst={last_frst}"
            )
        self.hold_ok = True
        cocotb.log.info("CHK-EFUSE-BND-HOLD: sense=1 fuse_reset_n=0 hold_ext_boot=1")
        self.chk_seen.add("CHK-EFUSE-BND-HOLD")

        for cycle in range(_PIPE_STAY):
            await RisingEdge(clk)
            if int(dut.tb_fuse_sense_done.value) != 1:
                raise AssertionError(f"STAY: sense dropped at cycle {cycle}")
            if int(dut.tb_fuse_reset_n.value) != 0:
                raise AssertionError(
                    f"STAY: fuse_reset_n rose at cycle {cycle} "
                    f"(pipe would only rise if ext_boot were 1)"
                )
        # Sampled, not assumed: this is the value the summary token reports for
        # the hold leg, so it must come from the DUT rather than from a literal.
        stay_frst = int(dut.tb_fuse_reset_n.value)
        stay_sense = int(dut.tb_fuse_sense_done.value)
        cocotb.log.info(
            "CHK-EFUSE-BND-STAY: fuse_reset_n stayed %d for %d clocks after "
            "sense (sense=%d at the end of the window)",
            stay_frst,
            _PIPE_STAY,
            stay_sense,
        )
        self.chk_seen.add("CHK-EFUSE-BND-STAY")

        locks = await self.csr_read("EFUSE_MAP_LOCKS_HELD", LOCKS, expected=LOCKS_PRELOAD)
        self.map_ok = True
        cocotb.log.info(
            "CHK-EFUSE-BND-MAP: LOCKS=0x%x == preload word 0 of "
            "assets/smc_efuse_default.hex, read after sense while "
            "fuse_reset_n=0 (transport proof; eFuse bank is the DV model)",
            locks,
        )
        self.chk_seen.add("CHK-EFUSE-BND-MAP")

        dut.tb_hold_ext_boot.value = 0
        last_frst = None
        for _ in range(_RELEASE_BOUND):
            await RisingEdge(clk)
            last_frst = int(dut.tb_fuse_reset_n.value)
            if last_frst == 1:
                break
        else:
            raise AssertionError(
                f"RELEASE: tb_fuse_reset_n stayed 0 after ext_boot release "
                f"last={last_frst} bound={_RELEASE_BOUND}"
            )
        # `tb_rst_warm_smc_clk_n` is an unconditional TB output (tb_top.sv), so a
        # missing port is a bench defect: assert it rather than skip the leg
        # ([NO-DUMMY-DEAD-CODE]).
        assert hasattr(dut, "tb_rst_warm_smc_clk_n"), (
            "tb_rst_warm_smc_clk_n missing from the TB top: the warm-reset "
            "release leg has no observation port and cannot be checked"
        )
        last_warm = None
        for _ in range(_RELEASE_BOUND):
            await RisingEdge(clk)
            last_warm = int(dut.tb_rst_warm_smc_clk_n.value)
            if last_warm == 1:
                break
        else:
            raise AssertionError(f"RELEASE: tb_rst_warm_smc_clk_n stayed 0 last={last_warm}")

        # Exact expectation from the generated RDL reset: no program read-back
        # has been issued in this testcase, so DOUT must still be at its reset
        # value ([EXACT-EXPECTATION]).
        prog = await self.csr_read("EFUSE_PROG_IF_RD", PROG_IF_RD, expected=PROG_IF_RD_RESET)
        # Positive control for the compare above (see the PROG_IF_RD_RESET note):
        # the writable sibling at +0x14 in the same register block is read at
        # its non-zero reset, written, read back and restored in the same run.
        tmo_reset = await self.csr_read(
            "EFUSE_READ_REQ_TMO_RESET",
            READ_REQ_TMO,
            expected=READ_REQ_TMO_CYCLES_RESET,
        )
        await self.csr_write("EFUSE_READ_REQ_TMO_PROBE", READ_REQ_TMO, READ_REQ_TMO_PROBE)
        tmo_probe = await self.csr_read(
            "EFUSE_READ_REQ_TMO_PROBE_RB",
            READ_REQ_TMO,
            expected=READ_REQ_TMO_PROBE,
        )
        await self.csr_write(
            "EFUSE_READ_REQ_TMO_RESTORE",
            READ_REQ_TMO,
            READ_REQ_TMO_CYCLES_RESET,
        )
        tmo_restored = await self.csr_read(
            "EFUSE_READ_REQ_TMO_RESTORE_RB",
            READ_REQ_TMO,
            expected=READ_REQ_TMO_CYCLES_RESET,
        )
        warm = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        # Positive control for the `warm == 0` compare above: without it, a
        # SCRATCH_COLD_WARM_0 that is dead, unmapped or stuck at 0 satisfies the
        # post-release expectation just as well as a live one
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). Prove in the same run that the
        # register holds a written pattern, then restore the reset value and
        # re-confirm it, so the zero is a measured state and not an artefact.
        await self.csr_write(
            "SCRATCH_COLD_WARM_0_PROBE", SCRATCH_COLD_WARM_0, SCRATCH_PROBE_PATTERN
        )
        probe = await self.csr_read(
            "SCRATCH_COLD_WARM_0_PROBE_RB",
            SCRATCH_COLD_WARM_0,
            expected=SCRATCH_PROBE_PATTERN,
        )
        await self.csr_write("SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0, 0)
        restored = await self.csr_read(
            "SCRATCH_COLD_WARM_0_RESTORE_RB", SCRATCH_COLD_WARM_0, expected=0
        )
        self.release_ok = True
        cocotb.log.info(
            "CHK-EFUSE-BND-REL: fuse_reset_n=1 rst_warm=1 PROG_IF=0x%x == RDL "
            "reset 0x%x (transport/decode probe only -- sw=r with a 0x0 reset, "
            "so this word alone does not prove the window is live); the "
            "efuse_interface_ctrl block is proven live in the same run on its "
            "writable sibling READ_REQ_TIMEOUT: non-zero reset 0x%x read back, "
            "probe 0x%x written and read back as 0x%x, restored to 0x%x. "
            "COLD_WARM=0x%x at its reset value, backed by its own positive "
            "control (wrote 0x%08x, read back 0x%08x, restored to 0x%x)",
            prog,
            PROG_IF_RD_RESET,
            tmo_reset,
            READ_REQ_TMO_PROBE,
            tmo_probe,
            tmo_restored,
            warm,
            SCRATCH_PROBE_PATTERN,
            probe,
            restored,
        )
        self.chk_seen.add("CHK-EFUSE-BND-REL")
        # Summary token carrying the values each leg observed, so the line is
        # falsifiable against the per-leg tokens above it
        # ([NO-ALWAYS-PASS-CHECKER]).
        cocotb.log.info(
            "CHK-EFUSE-BND-BASIC: hold(sense=%d fuse_reset_n=%d held for %d "
            "clocks after sense) map(LOCKS=0x%x == preload) release("
            "fuse_reset_n=%d rst_warm=%d within %d clocks)",
            stay_sense,
            stay_frst,
            _PIPE_STAY,
            locks,
            last_frst,
            last_warm,
            _RELEASE_BOUND,
        )
        self.chk_seen.add("CHK-EFUSE-BND-BASIC")
