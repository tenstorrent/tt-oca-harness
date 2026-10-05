# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The KM CRC co-processor matches an independent golden in all three modes.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_crc.parhex. RANDCFG.

The CRC engine has no register interface. It is a PicoRV32 PCPI co-processor
reached by a custom-0 instruction, so the only honest activation is KM firmware
issuing one -- hence a dedicated service ROM rather than ``rom_main``. The ROM
applies one instruction per request and returns the raw result; every golden
and cross-check lives here.

All three modes walk in this leaf: they share one datapath, one state register
and one result path.

Checkers:
  CHK-WORD    every seeded CRC-32C word vector equals the independent golden
  CHK-BYTE    every seeded CRC-32C byte vector equals the independent golden
  CHK-ROHC    every seeded CRC-8/ROHC vector equals the independent golden
  CHK-XCHAIN  hardware-only cross-check, independent of the golden: one word
              through the word instruction equals the same four bytes through
              four byte instructions from the same start state
  CHK-POLY    the two polynomial families disagree: the same state and byte
              give different results in CRC-32C byte mode and CRC-8/ROHC,
              compared over the low byte so the two modes' differing result
              WIDTHS cannot satisfy it on their own
  CHK-NARROW  CRC-8/ROHC leaves the upper 24 result bits clear. The golden
              already masks to eight bits, so CHK-ROHC covers the value; the
              zero-extension is its own RTL assertion and is named here
  CHK-UPPER   both byte modes ignore the operand's upper 24 bits: the same low
              byte under different garbage returns the same result
  CHK-MOVE    a guard on the operand screen rather than independent evidence:
              no vector's result equals its own input state. Once the value
              KATs pass this cannot fail, because the screen already removed
              every fixed point; it is here so that a screen which silently
              stopped working is caught at the point it would start hiding a
              co-processor that returns rs1 unchanged

Anti-vacuity is built into the operand draw as well as the checks. The seeded
vectors exclude an all-zero state with an all-zero byte (which every reflected
CRC maps to zero, and so passes against a dead engine), words whose four bytes
are not all distinct (which cannot separate little-endian consumption from
big-endian), and operands that sit on a FIXED POINT of their mode, which the
engine correctly maps back onto their own input state. A fixed point is legal
hardware behaviour, not a defect -- in CRC-8/ROHC one byte in 256 is a fixed
point for any given state -- so it is screened out of the draw with the
independent golden rather than tolerated by CHK-MOVE. CHK-XCHAIN and CHK-POLY
need no golden at all, so they still hold if the golden itself is wrong.
"""

from __future__ import annotations

import pyuvm
from env.sep_crc_golden import MODE_8_ROHC, MODE_32C_BYTE, MODE_32C_WORD, update
from sep_base_test import sep_base_test
from seq_lib.sep_km_crc_seq import (
    CRC_MODE_8_ROHC,
    CRC_MODE_32C_BYTE,
    CRC_MODE_32C_WORD,
    SepKmCrc,
    SepKmCrcCfg,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq


@pyuvm.test()
class sep_km_crc_pcpi_kat_test(sep_base_test):
    """All three KM CRC PCPI modes match the golden and the hardware cross-checks."""

    async def run_scenario(self) -> None:
        cfg = SepKmCrcCfg(self.random_seed())
        self.logger.info("km crc: %s", cfg.summary())

        await self.bring_up_no_cpu()
        await self.start_seq(sep_km_release_seq("km_crc_release"))
        crc = SepKmCrc(self)

        # --- CHK-WORD / CHK-BYTE / CHK-ROHC: value KATs -----------------------
        results: list[tuple[str, int, int, int]] = []
        for tag, hw_mode, gold_mode, vectors in (
            ("CHK-WORD", CRC_MODE_32C_WORD, MODE_32C_WORD, cfg.word_vectors),
            ("CHK-BYTE", CRC_MODE_32C_BYTE, MODE_32C_BYTE, cfg.byte_vectors),
            ("CHK-ROHC", CRC_MODE_8_ROHC, MODE_8_ROHC, cfg.rohc_vectors),
        ):
            for state, data in vectors:
                got = await crc.update(hw_mode, state, data)
                exp = update(gold_mode, state, data)
                assert got == exp, (
                    f"{tag} FAIL: mode={hw_mode} state=0x{state:08x} data=0x{data:08x} "
                    f"-> 0x{got:08x}, golden 0x{exp:08x}"
                )
                results.append((tag, state, data, got))
            self.logger.info(
                "%s PASS: %d seeded vectors match the independent golden", tag, len(vectors)
            )

        # --- CHK-MOVE: the engine moved the state -----------------------------
        # A co-processor stubbed to hand rs1 straight back would satisfy every
        # cross-check that compares two hardware results against each other.
        for tag, state, data, got in results:
            assert got != state, (
                f"CHK-MOVE FAIL [{tag}]: result 0x{got:08x} equals the input state for "
                f"data=0x{data:08x} -- the engine returned rs1 unchanged"
            )
        self.logger.info(
            "CHK-MOVE PASS: all %d results differ from their own input state", len(results)
        )

        # --- CHK-XCHAIN: word mode is four byte steps, proven in hardware -----
        # No golden on either side of this compare, so it holds independently of
        # env/sep_crc_golden.py being right.
        one_shot = await crc.update(CRC_MODE_32C_WORD, cfg.chain_state, cfg.chain_word)
        chained = cfg.chain_state
        for shift in (0, 8, 16, 24):
            chained = await crc.update(CRC_MODE_32C_BYTE, chained, (cfg.chain_word >> shift) & 0xFF)
        assert one_shot == chained, (
            "CHK-XCHAIN FAIL: one word instruction gave 0x{:08x} but the same four "
            "bytes chained through the byte instruction gave 0x{:08x} "
            "(state=0x{:08x} word=0x{:08x})".format(
                one_shot, chained, cfg.chain_state, cfg.chain_word
            )
        )
        self.logger.info(
            "CHK-XCHAIN PASS: word instruction == four chained byte instructions (0x%08x)",
            one_shot,
        )

        # --- CHK-POLY: the two polynomial families are not the same -----------
        # Compared over the low byte only. CRC-8/ROHC returns eight bits and
        # CRC-32C thirty-two, so a full-width compare would be satisfied by the
        # widths alone and would say nothing about the polynomials.
        # Its own screened operand, not a reused KAT vector: the two families
        # agree in the low byte for roughly one operand in 256, which is correct
        # hardware and would otherwise fail a small fraction of seeds.
        poly_state, poly_data = cfg.poly_state, cfg.poly_data
        r_32c = await crc.update(CRC_MODE_32C_BYTE, poly_state, poly_data)
        r_rohc = await crc.update(CRC_MODE_8_ROHC, poly_state, poly_data)
        assert (r_32c & 0xFF) != (r_rohc & 0xFF), (
            f"CHK-POLY FAIL: CRC-32C byte and CRC-8/ROHC agree in the low byte "
            f"(0x{r_32c & 0xFF:02x}) for state=0x{poly_state:02x} "
            f"data=0x{poly_data:08x}, an operand screened to make them differ -- "
            "one polynomial is being used for both modes"
        )
        self.logger.info(
            "CHK-POLY PASS: low byte differs, CRC-32C 0x%02x vs CRC-8/ROHC 0x%02x",
            r_32c & 0xFF,
            r_rohc & 0xFF,
        )

        # --- CHK-NARROW: CRC-8/ROHC zero-extends ------------------------------
        for state, data in cfg.rohc_vectors:
            got = await crc.update(CRC_MODE_8_ROHC, state, data)
            assert (got >> 8) == 0, (
                f"CHK-NARROW FAIL: CRC-8/ROHC returned 0x{got:08x}, upper bits not clear "
                f"(state=0x{state:02x} data=0x{data:08x})"
            )
        self.logger.info("CHK-NARROW PASS: every CRC-8/ROHC result has rd[31:8] == 0")

        # --- CHK-UPPER: byte modes ignore the operand's upper bytes -----------
        up_state, up_data = cfg.byte_vectors[1]
        low = up_data & 0xFF
        for hw_mode, name in ((CRC_MODE_32C_BYTE, "CRC-32C byte"), (CRC_MODE_8_ROHC, "ROHC")):
            state = up_state if hw_mode == CRC_MODE_32C_BYTE else (up_state & 0xFF)
            clean = await crc.update(hw_mode, state, low)
            dirty = await crc.update(hw_mode, state, 0xFFFF_FF00 | low)
            assert clean == dirty, (
                f"CHK-UPPER FAIL: {name} consumed the operand's upper bytes -- "
                f"0x{low:02x} gave 0x{clean:08x} but 0x{0xFFFF_FF00 | low:08x} gave "
                f"0x{dirty:08x}"
            )
        self.logger.info("CHK-UPPER PASS: both byte modes ignore data[31:8] (low byte 0x%02x)", low)

        await crc.halt()
