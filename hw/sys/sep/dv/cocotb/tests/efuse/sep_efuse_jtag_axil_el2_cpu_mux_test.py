# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse JTAG-AXIL + EL2-CPU mux arbitration test (PyUVM).

Boots VeeR EL2 with the efuse_jtag_el2_mux firmware (a continuous eFuse-MMR read loop) while
``ocah_axi_vip.OcahAxiLiteMasterSequence`` drives the real SEP-OTP JTAG AXI-Lite port
(``axil_sep_otp_jtag``, ``j_axi_*`` in tb_top). Both masters arbitrate at the eFuse interface
controller's AXI-Lite mux.

The OTP image is real-sensed at LC_STATE=PROD, which restricts the JTAG path: MMR token accesses
are allowed, and shadow-map and interface-CSR accesses get the error response and data that
``hw/ip/efuse/doc/architecture.adoc`` specifies. One PROD image covers both the allowed
coexistence and the LC-gated deny without forcing lc_state.

Checkers (each logged):
  * CHK-SENSE / firmware self-checks: fuse sense completed, the CPU seeded its token0 word, the
    read loop ran, and the CPU MMR read error count stayed zero.
  * CHK-JTAG-MMR: every JTAG MMR op returns OKAY (token1 seed write, per-round token1 reads of
    the seeded word, token3 writes + readbacks). TOKEN_I is an ``external`` sw=rw word with no
    reset, so it is seeded before any read.
  * CHK-JTAG-DENY: a JTAG shadow-map read at PROD gets SLVERR or DECERR with data 0xbadcab1e.
  * CHK-JTAG-ALLOW: a JTAG MMR read right after the deny still returns OKAY.
  * CHK-JTAG-TOKEN-BLOCK: JTAG reads of a seeded ``SEC_DISABLE_TOKEN_I[0]``, ``TOKEN_EOP`` and
    ``SEC_DISABLE_TOKEN_MATCH`` return OKAY. No ``TOKEN_EOP`` write is issued, since that starts
    a compare. This samples the allow class; it does not walk every token word.
  * CHK-JTAG-IFACE-DENY: a JTAG read of ``EFUSE_PROGRAM_CTRL`` gets the same deny as shadow.
  * CHK-COEXIST: the CPU loop counter (scratch-cold[2], via scratch_cold_probe_o) advances across
    the JTAG burst, and the CPU loop checks its token0 seed every iteration while JTAG uses
    token1 and token3, so a stall or cross-port corruption fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_lcc_golden import LC_PROD
from env.sep_spec_tables import EFUSE_ERR_SLV_RDATA
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_inbound_filter_rule_seq import RESP_DECERR, RESP_SLVERR

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
# Interface control sits outside the token block and is blocked in PROD.
# architecture.adoc (eFuse lifecycle-based JTAG permissions) specifies "an error
# response with data value 0xbadcab1e" and does not name the response code, so
# SLVERR and DECERR both satisfy it; OKAY or a timeout does not.
_JTAG_DENY_RESPS = (RESP_SLVERR, RESP_DECERR)
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
        lane = 0xFFFF_FFFF << (32 * idx)
        return self.rd(cocotb.top.scratch_cold_probe_o, mask=lane) >> (32 * idx)

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

        # --- LC-gated: shadow read DENIED at PROD. An error response with the
        # error-slave data architecture.adoc specifies. ---
        code, rdata = await self.jtag_axil_op(write=False, addr=_EFUSE_SHADOW_BASE)
        assert code in _JTAG_DENY_RESPS, (
            f"JTAG shadow read at PROD must be DENIED with an error response "
            f"(SLVERR or DECERR), got resp={code} rdata=0x{rdata:08x}"
        )
        assert rdata == EFUSE_ERR_SLV_RDATA, (
            f"JTAG denied-read data 0x{rdata:08x} != 0x{EFUSE_ERR_SLV_RDATA:08x} "
            "(architecture.adoc error-slave data)"
        )
        self.logger.info(
            "CHK-JTAG-DENY PASS: JTAG shadow read @0x%08x denied (resp=%d, rdata=0x%08x)",
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
        assert code in _JTAG_DENY_RESPS, (
            f"CHK-JTAG-IFACE-DENY FAIL: JTAG EFUSE_PROGRAM_CTRL @0x{_EFUSE_IFACE_PROGRAM:08x} "
            f"in PROD must return an error response; got resp={code} rdata=0x{rdata:08x}"
        )
        assert rdata == EFUSE_ERR_SLV_RDATA, (
            f"CHK-JTAG-IFACE-DENY FAIL: denied-read data 0x{rdata:08x} != "
            f"0x{EFUSE_ERR_SLV_RDATA:08x} (architecture.adoc error-slave data)"
        )
        self.logger.info(
            "CHK-JTAG-IFACE-DENY PASS: JTAG program-interface read @0x%08x denied "
            "(resp=%d, rdata=0x%08x)",
            _EFUSE_IFACE_PROGRAM,
            code,
            rdata,
        )

        self.logger.info("SEP eFuse JTAG/EL2 mux test PASS")
