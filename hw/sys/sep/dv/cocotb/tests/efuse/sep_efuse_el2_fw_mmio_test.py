# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""EL2 firmware reads one OTP word directly and gets the RMA token results the spec states.

cpu mode. The EL2 CPU boots ``efuse_el2_fw_mmio_test``. It reads SPARE0
word 0 through ``EFUSE_READ_CTRL`` (``doc/programmer/src/smc-programming.adoc``,
eFuse read sequence), then submits the SiP RMA token whose SHA-256 is the
preloaded SiP digest and, on the chiplet channel, first a token whose SHA-256
is not the preloaded chiplet digest and then the token whose SHA-256 is
(``doc/programmer/src/sep-programming.adoc``, ``sep-token-matching``). The firmware makes no verdict: it publishes the raw
values to the scratch-cold words, done marker last, and the leaf reads them
once through the ``scratch_cold_probe_o`` tap.

Real fuse sense of the committed preload ``sep_efuse_el2_fw_mmio.toml``; the
leaf loads the same file as its golden, so the base post-sense compare grades
the sensed shadow.

* CHK-FW-OTP-DIRECT   ``read_done`` = 1, ``read_status`` = 0 (no error), and the
  read data equals the staged SPARE0 word 0 of the image
  (``hw/ip/efuse/doc/architecture.adoc``: a successful read captures the
  response data; ``hw/ip/efuse/regs/efuse_interface_ctrl.rdl``).
* CHK-FW-TOKEN-MATCH  SiP result ``0x15`` (Match), first chiplet result
  ``0x2a`` (Mismatch) and second chiplet result ``0x15`` (Match) in
  ``token_match_status``, each within the firmware poll bound, and neither RMA
  bit of ``TOKEN_MATCH_FAULT`` set (``hw/sys/sep/doc/token_processing.adoc``,
  token result encodings; a new start clears the retained digest validity, so
  the second chiplet result comes from the second digest). The firmware reads
  each result once before its go; a submission whose pre-go status already
  equals its expected code fails, so the graded result comes from that
  submission.

``req_error`` and the sense-wait result are logged, not graded. Both checks
are evaluated before the leaf fails, and a firmware that never publishes the
done marker fails both.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import LC_PROD, SepEfuseImage
from env.sep_efuse_plan import (
    MATCH_STATUS_MASK,
    TOKEN_OTHER,
    TOKEN_T1,
    TOKEN_T2,
    bit_address,
    rma_digest_pins,
)
from env.sep_rma_token import token_digest
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_MMR, sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "efuse_el2_fw_mmio_test")
_ITCM_HEX = os.path.join(_FW_DIR, "efuse_el2_fw_mmio_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "efuse_el2_fw_mmio_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP eFuse EL2 firmware MMIO test"

# Token result codes (hw/sys/sep/doc/token_processing.adoc, token result
# encodings): Match and Mismatch.
_CODE_MATCH = 0x15
_CODE_MISMATCH = 0x2A

# Scratch-cold layout, marker, poll bound and tokens; efuse_el2_fw_mmio_test.c
# holds the same values.
_DONE_MARKER = 0xE905_00A5
_SCRATCH_DONE = 0
_SCRATCH_READ_FLAGS = 1
_SCRATCH_READ_DATA = 2
_SCRATCH_SIP_MATCH = 3
_SCRATCH_CHIP_MATCH = 4  # [7:0] first, [15:8] second chiplet; [31:16] second polls
_SCRATCH_POLLS = 5  # [15:0] SiP, [31:16] first chiplet
_SCRATCH_FAULT = 6
# [0] sense wait; [15:8] SiP, [23:16] first and [31:24] second chiplet pre-go TOKEN_MATCH
_SCRATCH_SENSE = 7
_N_SCRATCH = 8
_FLAG_COMPLETED = 1 << 0
_FLAG_READ_STATUS = 1 << 1
_FLAG_REQ_ERROR = 1 << 2
_TOKEN_POLL_BOUND = 4096
_SIP_TOKEN = TOKEN_T1
_CHIP_TOKEN = TOKEN_OTHER
_CHIP_MATCH_TOKEN = TOKEN_T2
_READ_FIELD = "SPARE0"

_SIP_DIGEST = "RMA_SIP_TOKEN_DIGEST"
_CHIP_DIGEST = "RMA_CHIPLET_TOKEN_DIGEST"
_SIP_FAULT_BM = EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_sip_token_fault")
_CHIP_FAULT_BM = EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_chiplet_token_fault")


def _flag(value: int, bit: int) -> int:
    return int(bool(value & bit))


@pyuvm.test()
class sep_efuse_el2_fw_mmio_test(sep_base_test):
    """EL2 firmware direct OTP read data and RMA token results equal the image goldens."""

    build_env = False
    required_evidence = ("CHK-FW-OTP-DIRECT", "CHK-FW-TOKEN-MATCH")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _check_image(self, img: SepEfuseImage) -> int:
        """Assert the preload is the image this leaf grades against; return the read word index."""
        pins = rma_digest_pins()
        assert img.lc_raw() == LC_PROD, f"test bug: preload LC raw 0x{img.lc_raw():x} is not PROD"
        assert img.field_int("TRANSIENT_RMA_EN") == 0, "test bug: TRANSIENT_RMA_EN is set"
        for name in (_SIP_DIGEST, _CHIP_DIGEST):
            assert img.field_int(name) == pins[name], f"test bug: preload {name} is not the pin"
        assert token_digest(_SIP_TOKEN) == img.field_int(_SIP_DIGEST), (
            "test bug: the SiP token does not hash to the SiP digest"
        )
        assert token_digest(_CHIP_TOKEN) != img.field_int(_CHIP_DIGEST), (
            "test bug: the chiplet token hashes to the chiplet digest"
        )
        assert token_digest(_CHIP_MATCH_TOKEN) == img.field_int(_CHIP_DIGEST), (
            "test bug: the second chiplet token does not hash to the chiplet digest"
        )
        word = SepEfuseImage.field(_READ_FIELD).word
        staged = img.words[word]
        assert staged != 0 and img.words.count(staged) == 1, (
            f"test bug: staged {_READ_FIELD} word 0x{staged:08x} is zero or not unique in the image"
        )
        return word

    def _published(self) -> list[int]:
        lanes = (1 << (32 * _N_SCRATCH)) - 1
        probe = self.rd(cocotb.top.scratch_cold_probe_o, mask=lanes)
        return [(probe >> (32 * i)) & 0xFFFF_FFFF for i in range(_N_SCRATCH)]

    def _chk(self, fails: list[str], name: str, ok: bool, fields: str) -> None:
        line = f"CHK-{name} {'PASS' if ok else 'FAIL'}: seed={self.random_seed()} {fields}"
        if ok:
            self.logger.info(line)
        else:
            self.logger.error(line)
            fails.append(name)

    async def run_scenario(self) -> None:
        img = self.select_efuse_image()
        word = self._check_image(img)
        self.write_efuse_image(img)
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        pub = self._published()
        marker = pub[_SCRATCH_DONE]
        marker_ok = marker == _DONE_MARKER
        fails: list[str] = []

        flags = pub[_SCRATCH_READ_FLAGS]
        completed = _flag(flags, _FLAG_COMPLETED)
        read_status = _flag(flags, _FLAG_READ_STATUS)
        data = pub[_SCRATCH_READ_DATA]
        exp = img.words[word]
        self._chk(
            fails,
            "FW-OTP-DIRECT",
            marker_ok and completed == 1 and read_status == 0 and data == exp,
            f"marker=0x{marker:08x} addr={bit_address(_READ_FIELD)} completed={completed} "
            f"read_status={read_status} req_error={_flag(flags, _FLAG_REQ_ERROR)} "
            f"data=0x{data:08x} exp=0x{exp:08x}",
        )

        sip = pub[_SCRATCH_SIP_MATCH]
        chip_word = pub[_SCRATCH_CHIP_MATCH]
        chip = chip_word & 0xFF
        chip2 = (chip_word >> 8) & 0xFF
        chip2_polls = chip_word >> 16
        polls = pub[_SCRATCH_POLLS]
        sip_polls = polls & 0xFFFF
        chip_polls = polls >> 16
        fault = pub[_SCRATCH_FAULT]
        sense = pub[_SCRATCH_SENSE]
        sip_pre = (sense >> 8) & 0xFF
        chip_pre = (sense >> 16) & 0xFF
        chip2_pre = sense >> 24
        # _check_image holds the digest relation behind each expected code.
        sip_exp = _CODE_MATCH
        chip_exp = _CODE_MISMATCH
        chip2_exp = _CODE_MATCH
        self._chk(
            fails,
            "FW-TOKEN-MATCH",
            marker_ok
            and sip & MATCH_STATUS_MASK == sip_exp
            and chip & MATCH_STATUS_MASK == chip_exp
            and chip2 & MATCH_STATUS_MASK == chip2_exp
            and 0 < sip_polls <= _TOKEN_POLL_BOUND
            and 0 < chip_polls <= _TOKEN_POLL_BOUND
            and 0 < chip2_polls <= _TOKEN_POLL_BOUND
            and fault & (_SIP_FAULT_BM | _CHIP_FAULT_BM) == 0
            and sip_pre & MATCH_STATUS_MASK != sip_exp
            and chip_pre & MATCH_STATUS_MASK != chip_exp
            and chip2_pre & MATCH_STATUS_MASK != chip2_exp,
            f"marker=0x{marker:08x} sip=0x{sip:08x} sip_exp=0x{sip_exp:02x} sip_pre=0x{sip_pre:02x} "
            f"sip_polls={sip_polls} chip=0x{chip:02x} chip_exp=0x{chip_exp:02x} "
            f"chip_pre=0x{chip_pre:02x} chip_polls={chip_polls} chip2=0x{chip2:02x} "
            f"chip2_exp=0x{chip2_exp:02x} chip2_pre=0x{chip2_pre:02x} chip2_polls={chip2_polls} "
            f"bound={_TOKEN_POLL_BOUND} "
            f"fault=0x{fault:08x} sense_wait={sense & 1}",
        )

        if fails:
            raise AssertionError(f"{len(fails)} check(s) failed: " + ", ".join(fails))
