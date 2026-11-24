# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The supplementary fuse region: sense, window, shadow writes, program, locks and errors.

Sources: architecture.adoc (Supplementary Fuse Region), memmap.adoc (the supplementary fuse
window), smc_efuse_map.rdl (SUPPLEMENTARY_LOCKS), efuse_interface_ctrl.rdl (the address registers
and the error bits).

The image is written into the run directory during ``build_phase``: every harness word is 0 and
the 128 supplementary words carry a seeded pattern (one 32-bit hex word per line, word N on line
N) with the bit the sequence programs cleared.
"""

from __future__ import annotations

import random
from pathlib import Path

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_supplementary_region_test_seq import (
    IMAGE_WORDS,
    MAP_WORDS,
    PROG_BIT,
    PROG_WORD,
    SUPP_WORDS,
    smc_efuse_supplementary_region_test_seq,
    supp_addr,
)
from smc_base_test import smc_base_test

_MASK32 = 0xFFFF_FFFF


def image_words(seed: int) -> list[int]:
    """Words 0..63 zero; words 64..191 seeded, pairwise distinct, neither 0 nor all ones."""
    rnd = random.Random(seed)
    words: list[int] = [0] * MAP_WORDS
    seen: set[int] = set()
    while len(words) < IMAGE_WORDS:
        value = rnd.getrandbits(32)
        if value in (0, _MASK32, 0xBADC_AB1E) or value in seen:
            continue
        seen.add(value)
        words.append(value)
    words[MAP_WORDS + PROG_WORD] &= ~(1 << PROG_BIT) & _MASK32
    return words


def write_image(seed: int) -> tuple[Path, list[int]]:
    """Render the image at the path ``+smc_efuse_hex`` names."""
    plusarg = cocotb.plusargs.get("smc_efuse_hex")
    assert plusarg is not None, "the leaf's testlist entry must name +smc_efuse_hex"
    hex_path = Path(str(plusarg))
    assert not hex_path.is_absolute(), (
        f"+smc_efuse_hex={plusarg} is absolute; this leaf writes the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    hex_path = Path.cwd() / hex_path
    words = image_words(seed)
    hex_path.write_text("".join(f"{w:08x}\n" for w in words), encoding="utf-8")
    return hex_path, words


@pyuvm.test()
class smc_efuse_supplementary_region_test(smc_base_test):
    """Sense, window, shadow writes, program and read, lock pairs, guard and address errors."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SUPP-ADDR-ERROR",
        "CHK-SUPP-GUARD",
        "CHK-SUPP-LOCK-IRQ",
        "CHK-SUPP-PROGRAM-READ",
        "CHK-SUPP-READ-LOCK",
        "CHK-SUPP-SENSE-WORDS",
        "CHK-SUPP-SHADOW-WRITE",
        "CHK-SUPP-WINDOW-END",
        "CHK-SUPP-WRITE-LOCK",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        path, words = write_image(self.random_seed())
        self.image = tuple(words)
        cocotb.log.info(
            "eFuse image %s: %d words, seed %d", path.name, len(words), self.random_seed()
        )

    async def run_scenario(self) -> None:
        seq = smc_efuse_supplementary_region_test_seq("smc_efuse_supplementary_region_test_seq")
        seq.image = self.image
        seq.seed = self.random_seed()
        # The first word past the window leaves on smc_external_req_o and the reference
        # integration's terminator answers DECERR; the monitor must not count it as a fault.
        self.env.axi_monitor.expected_decerr_addrs.add(supp_addr(SUPP_WORDS))
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.access_floor > 0 and seq.accesses >= seq.access_floor, (
            f"{seq.accesses} SEP_IN accesses, the sequence computed a floor of {seq.access_floor}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=seq.access_floor,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "supplementary fuse region: window reads, shadow writes, program and read, "
                "SUPPLEMENTARY_LOCKS pairs, guard and address errors (eFuse bank is the DV model)"
            ),
        )
