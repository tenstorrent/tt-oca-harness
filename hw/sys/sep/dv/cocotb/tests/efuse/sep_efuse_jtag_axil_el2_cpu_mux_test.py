# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse JTAG-AXIL + EL2-CPU mux arbitration test (PyUVM).

Boots the VeeR EL2 core running the efuse_jtag_el2_mux firmware (a continuous eFuse-MMR
read loop) and, CONCURRENTLY, drives the DUT's real SEP-OTP JTAG AXI-Lite port
(``axil_sep_otp_jtag``, brought out as ``j_axi_*`` in tb_top) via
``ocah_axi_vip.OcahAxiLiteMasterSequence``. Both masters arbitrate at the eFuse
interface controller's
AXI-Lite mux -- proving CPU + JTAG coexistence with no corruption.

The OTP image is real-sensed at LC_STATE=PROD, which makes the JTAG path
LC-restricted: a JTAG access to the MMR token region is allowed, but a JTAG
access to the shadow map / interface CSRs is denied (AMBA decode error plus
the denied-access sentinel). So the single PROD image exercises BOTH the
allowed-MMR coexistence AND the LC-gated deny -- with no backdoor lc_state force
(the reference suite ``force_jtag_lc_state``).

Checkers (each logged):
  * CHK-SENSE / firmware self-checks: real fuse-sense completed, the CPU eFuse-MMR
    read loop ran, and the CPU-published MMR read error count stayed zero.
  * CHK-JTAG-MMR: all JTAG MMR ops (a token1 seed write then per-round reads that
    must return the seeded word, token3 writes + readbacks, token-last reads)
    return OKAY -- the JTAG path reaches the eFuse through the mux. token1 is
    seeded because TOKEN_I is an ``external`` sw=rw word with no reset, so an
    unwritten read returns X.
  * CHK-JTAG-DENY: a JTAG shadow-map read at PROD is DENIED -- DECERR and
    the denied-access sentinel (the LC-gated filter).
  * CHK-JTAG-ALLOW: a JTAG MMR read right after the deny still returns OKAY (MMR is
    allowed even in the restricted state).
  * CHK-JTAG-TOKEN-BLOCK: in PROD/RMA_SIP, JTAG may reach the MMR token
    block. This checker seeds ``SEC_DISABLE_TOKEN_I[0]`` (unreset, as above) and
    then samples it, ``TOKEN_EOP`` and ``SEC_DISABLE_TOKEN_MATCH`` by read. No
    ``TOKEN_EOP`` write is issued: that, and only that, would start a compare.
    ``CHK-JTAG-MMR`` already walks RMA ``TOKEN_I``.
    It is a sample of the allow class, not every TOKEN_I word and MATCH.
  * CHK-JTAG-IFACE-DENY: a JTAG read of the program/read interface
    (`EFUSE_PROGRAM_CTRL`) DECERRs with the denied-access sentinel — same class
    as shadow.
  * CHK-COEXIST: the CPU loop counter (scratch-cold[2], read via the read-only
    scratch_cold_probe_o) advances across the JTAG burst -- the CPU was not stalled
    by the JTAG master.

Deltas vs the reference suite: real PROD-sense replaces its backdoor
``force_jtag_lc_state``; a live CPU loop window replaces its backdoor
``uvm_hdl_deposit`` UVM_DONE release.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_inbound_filter_rule_seq import ERR_SLV_RDATA, RESP_DECERR

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "efuse_jtag_el2_mux_test")
_ITCM_HEX = os.path.join(_FW_DIR, "efuse_jtag_el2_mux_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "efuse_jtag_el2_mux_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# eFuse addresses reachable on the JTAG AXI-Lite port.
_EFUSE_SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")  # shadow map -> DENIED to JTAG at PROD
_EFUSE_MMR_TOKEN1 = sym("EFUSE_MMR_RMA_SIP_TOKEN_I_1__REG_ADDR")  # MMR token region -> ALLOWED
_EFUSE_MMR_TOKEN3 = sym("EFUSE_MMR_RMA_SIP_TOKEN_I_3__REG_ADDR")
# Seeded into token1 before the read loop; distinct from the 0xE905_5xxx the
# loop writes to token3, so a read that aliased onto token3 would fail.
_TOKEN1_SEED = 0x5A5A_1001
# Token-block members beyond the two RMA TOKEN_I words already walked above.
_EFUSE_MMR_SEC_DIS_I0 = sym("EFUSE_MMR_SEC_DISABLE_TOKEN_I_0__REG_ADDR")
_EFUSE_MMR_TOKEN_EOP = sym("EFUSE_MMR_TOKEN_EOP_REG_ADDR")
_EFUSE_MMR_SEC_DIS_MATCH = sym("EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_REG_ADDR")
# Seeded into SEC_DISABLE_TOKEN_I[0] before the token-block sample reads it.
_SEC_DIS_I0_SEED = 0x5A5A_4001
# Interface control sits outside the token block and must DECERR in PROD.
# DECERR is the AMBA AXI4-Lite decode error (IHI 0022). The data sentinel is
# the same DV-owned denied-access value inbound-filter deny grades.
_EFUSE_IFACE_PROGRAM = sym("EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR")

_CPU_READY = 0xE905_0001
_SCRATCH_READY = 0
_SCRATCH_COUNT = 2
_SCRATCH_ERR = 3

_READY_POLL_CYCLES = 200_000
_COUNT_POLL_CYCLES = 100_000
_JTAG_MIN_ROUNDS = 16
_JTAG_MAX_ROUNDS = 512


@pyuvm.test()
class sep_efuse_jtag_axil_el2_cpu_mux_test(sep_base_test):
    """EL2 eFuse-MMR loop + concurrent JTAG-AXIL traffic arbitrating at the mux."""

    build_env = False

    def _scratch(self, idx: int) -> int:
        probe = self.rd(cocotb.top.scratch_cold_probe_o)
        return (probe >> (32 * idx)) & 0xFFFF_FFFF

    async def _wait_ready(self) -> bool:
        dut = cocotb.top
        for _ in range(_READY_POLL_CYCLES):
            await RisingEdge(dut.clk_i)
            if self._scratch(_SCRATCH_READY) == _CPU_READY:
                return True
        return False

    async def _wait_count_gt(self, baseline: int) -> int | None:
        dut = cocotb.top
        for _ in range(_COUNT_POLL_CYCLES):
            await RisingEdge(dut.clk_i)
            count = self._scratch(_SCRATCH_COUNT)
            if count > baseline:
                return count
        return None

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Real-sense a PROD OTP image -> JTAG path is LC-restricted (shadow denied,
        # MMR allowed). No backdoor lc_state force.
        image = self.select_efuse_image(lc_raw=LC_PROD)
        # Non-vacuity guard: select_efuse_image ignores lc_raw under
        # +sep_efuse_preload, so a non-PROD preload would un-gate JTAG and the
        # shadow-deny check could pass for the wrong reason. Require PROD here
        # (mirrors the inbound-filter gating test).
        assert image.lc_raw() == LC_PROD, (
            f"test bug: image LC_STATE is not PROD (0x{image.lc_raw():x}); "
            "the JTAG LC-gating proof requires a PROD image"
        )
        self.write_efuse_image(image)

        # Stage the firmware TCM images, then boot the EL2 (real fuse sense).
        for src, dst in ((_ITCM_HEX, "sep_itcm.hex"), (_DTCM_HEX, "sep_dtcm.hex")):
            if not os.path.isfile(src):
                raise FileNotFoundError(f"firmware image not found: {src} (build it first)")
            import shutil

            shutil.copyfile(src, os.path.join(os.getcwd(), dst))
        self._log_firmware_identity(_ITCM_HEX, _DTCM_HEX)

        async def _load_tcm() -> None:
            from cocotb.triggers import ClockCycles

            dut.tcm_load_i.value = 1
            await ClockCycles(dut.clk_i, 4)
            dut.tcm_load_i.value = 0
            await ClockCycles(dut.clk_i, 4)

        await self.bring_up_cpu_boot(_ICCM_BASE >> 1, pre_reset_hook=_load_tcm)

        assert await self._wait_ready(), "EL2 never published CPU_READY (eFuse loop not running)"
        assert self._scratch(_SCRATCH_ERR) == 0, (
            f"CPU eFuse MMR read error count nonzero before JTAG burst: "
            f"{self._scratch(_SCRATCH_ERR)}"
        )
        ready_count = self._scratch(_SCRATCH_COUNT)
        cnt_before = await self._wait_count_gt(ready_count)
        assert cnt_before is not None, (
            f"EL2 published CPU_READY but eFuse loop counter did not advance "
            f"from {ready_count} before the JTAG burst"
        )

        # Seed token1 before the read loop reads it. RMA_SIP_TOKEN_I is an
        # `external` sw=rw token-input word (hw/ip/efuse/regs/efuse_mmr.rdl): the
        # regblock defines no reset for it, so it holds X until software writes
        # it. The loop below reads it every round, and an unwritten read returns
        # X, which the AXI-Lite master cannot convert to an int.
        code, _ = await self.jtag_axil_op(write=True, addr=_EFUSE_MMR_TOKEN1, wdata=_TOKEN1_SEED)
        assert code == 0, f"JTAG MMR token1 seed write not OKAY (resp={code})"

        # --- JTAG MMR ops, concurrent with the CPU loop: all allowed (OKAY) ---
        cnt_after = cnt_before
        rounds = 0
        for i in range(_JTAG_MAX_ROUNDS):
            code, rdata = await self.jtag_axil_op(write=False, addr=_EFUSE_MMR_TOKEN1)
            assert code == 0, f"JTAG MMR token1 read {i} not OKAY (resp={code})"
            # The seed is untouched by the token3 traffic in between, so this also
            # shows the JTAG reads are not aliasing onto the word being written.
            assert rdata == _TOKEN1_SEED, (
                f"JTAG MMR token1 read {i} got 0x{rdata:08x}, expected the seeded "
                f"0x{_TOKEN1_SEED:08x}"
            )
            token3_value = 0xE905_5000 | i
            code, _ = await self.jtag_axil_op(
                write=True, addr=_EFUSE_MMR_TOKEN3, wdata=token3_value
            )
            assert code == 0, f"JTAG MMR token3 write {i} not OKAY (resp={code})"
            code, rdata = await self.jtag_axil_op(write=False, addr=_EFUSE_MMR_TOKEN3)
            assert code == 0, f"JTAG MMR token3 readback {i} not OKAY (resp={code})"
            assert rdata == token3_value, (
                f"JTAG MMR token3 readback {i} got 0x{rdata:08x}, expected 0x{token3_value:08x}"
            )
            rounds = i + 1
            cnt_after = self._scratch(_SCRATCH_COUNT)
            if rounds >= _JTAG_MIN_ROUNDS and cnt_after > cnt_before:
                break
        self.logger.info(
            "CHK-JTAG-MMR PASS: %d JTAG MMR rounds all OKAY (mux reached eFuse)", rounds
        )

        # --- LC-gated: shadow read DENIED at PROD. DECERR plus the denied-access
        # sentinel; a SLVERR or any other non-OKAY is a contract violation. ---
        code, rdata = await self.jtag_axil_op(write=False, addr=_EFUSE_SHADOW_BASE)
        assert code == RESP_DECERR, (
            f"JTAG shadow read at PROD must be DENIED with DECERR (resp={RESP_DECERR}), "
            f"got resp={code} rdata=0x{rdata:08x}"
        )
        assert rdata == ERR_SLV_RDATA, (
            f"JTAG denied-read data 0x{rdata:08x} != 0x{ERR_SLV_RDATA:08x}"
        )
        self.logger.info(
            "CHK-JTAG-DENY PASS: JTAG shadow read @0x%08x denied with DECERR (resp=%d, rdata=0x%08x)",
            _EFUSE_SHADOW_BASE,
            code,
            rdata,
        )

        # --- MMR still allowed in the restricted state ---
        code, _ = await self.jtag_axil_op(write=False, addr=_EFUSE_MMR_TOKEN1)
        assert code == 0, f"JTAG MMR read after deny must be OKAY (resp={code})"
        self.logger.info("CHK-JTAG-ALLOW PASS: JTAG MMR read still OKAY in restricted state")

        # --- CPU progressed concurrently with the JTAG burst ---
        assert cnt_after > cnt_before, (
            f"CPU eFuse loop did not advance during JTAG burst "
            f"(before={cnt_before}, after={cnt_after}) -- mux starved the CPU"
        )
        self.logger.info(
            "CHK-COEXIST PASS: CPU loop advanced %d->%d during %d JTAG MMR rounds",
            cnt_before,
            cnt_after,
            rounds,
        )
        cpu_err = self._scratch(_SCRATCH_ERR)
        assert cpu_err == 0, f"CPU eFuse MMR read error count nonzero after JTAG burst: {cpu_err}"
        self.logger.info("CHK-CPU-MMR PASS: CPU eFuse MMR read error count stayed zero")

        # Seed the token-input word first, for the same reason token1 is seeded:
        # SEC_DISABLE_TOKEN_I is `external` sw=rw with no reset, so an unwritten
        # read returns X. Writing a TOKEN_I word starts no compare -- only a
        # TOKEN_EOP write does, which this checker never issues.
        code, _ = await self.jtag_axil_op(
            write=True, addr=_EFUSE_MMR_SEC_DIS_I0, wdata=_SEC_DIS_I0_SEED
        )
        assert code == 0, f"JTAG SEC_DISABLE_TOKEN_I[0] seed write not OKAY (resp={code})"

        # Sample of the PROD/RMA_SIP MMR token-block allow class. Reads only
        # beyond that seed -- a TOKEN_EOP write would start a compare.
        # CHK-JTAG-MMR already walks RMA TOKEN_I.
        for label, addr in (
            ("SEC_DISABLE_TOKEN_I[0]", _EFUSE_MMR_SEC_DIS_I0),
            ("TOKEN_EOP", _EFUSE_MMR_TOKEN_EOP),
            ("SEC_DISABLE_TOKEN_MATCH", _EFUSE_MMR_SEC_DIS_MATCH),
        ):
            code, rdata = await self.jtag_axil_op(write=False, addr=addr)
            assert code == 0, (
                f"CHK-JTAG-TOKEN-BLOCK FAIL: JTAG {label} @0x{addr:08x} in PROD "
                f"must be OKAY; got resp={code} rdata=0x{rdata:08x}"
            )
            if addr == _EFUSE_MMR_SEC_DIS_I0:
                assert rdata == _SEC_DIS_I0_SEED, (
                    f"CHK-JTAG-TOKEN-BLOCK FAIL: JTAG {label} read back "
                    f"0x{rdata:08x}, expected the seeded 0x{_SEC_DIS_I0_SEED:08x}"
                )
        self.logger.info(
            "CHK-JTAG-TOKEN-BLOCK PASS: JTAG SEC_DISABLE_TOKEN_I / TOKEN_EOP / "
            "SEC_DISABLE_TOKEN_MATCH all OKAY in PROD"
        )

        code, rdata = await self.jtag_axil_op(write=False, addr=_EFUSE_IFACE_PROGRAM)
        assert code == RESP_DECERR, (
            f"CHK-JTAG-IFACE-DENY FAIL: JTAG EFUSE_PROGRAM_CTRL @0x{_EFUSE_IFACE_PROGRAM:08x} "
            f"in PROD must DECERR; got resp={code} rdata=0x{rdata:08x}"
        )
        assert rdata == ERR_SLV_RDATA, (
            f"CHK-JTAG-IFACE-DENY FAIL: denied-read data 0x{rdata:08x} != 0x{ERR_SLV_RDATA:08x}"
        )
        self.logger.info(
            "CHK-JTAG-IFACE-DENY PASS: JTAG program-interface read @0x%08x denied "
            "with DECERR (resp=%d, rdata=0x%08x)",
            _EFUSE_IFACE_PROGRAM,
            code,
            rdata,
        )

        self.logger.info("SEP eFuse JTAG/EL2 mux test PASS")
