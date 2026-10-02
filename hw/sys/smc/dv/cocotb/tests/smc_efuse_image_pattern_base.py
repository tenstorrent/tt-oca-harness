# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared testcase body of the eFuse image-pattern leaves.

Each leaf names one ``pattern_efuse.py`` pattern. The image is written into the
run directory, at the relative path the leaf's ``+smc_efuse_hex`` names, during
``build_phase``: the bank model reads that file when its reset releases, which
is after ``_bring_up`` starts, so the image is in place before the first sense.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cocotb
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_efuse_image_pattern_test_seq import (
    EFUSE_MAP_WORDS,
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    load_image,
    region_of,
    smc_efuse_image_pattern_test_seq,
)
from smc_base_test import smc_base_test

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"
_PATTERN_WORD = {"alt55": 0x5555_5555, "altaa": 0xAAAA_AAAA}


def write_image(pattern: str, seed: int) -> Path:
    """Generate the leaf's image at the path ``+smc_efuse_hex`` names."""
    plusarg = cocotb.plusargs.get("smc_efuse_hex")
    assert plusarg is not None, "the leaf's testlist entry must name +smc_efuse_hex"
    hex_path = Path(str(plusarg))
    assert not hex_path.is_absolute(), (
        f"+smc_efuse_hex={plusarg} is absolute; this leaf writes the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    hex_path = Path.cwd() / hex_path
    config = hex_path.with_suffix(".toml")
    commands = [
        [
            sys.executable,
            str(_EFUSE_DIR / "pattern_efuse.py"),
            "--pattern",
            pattern,
            "--seed",
            str(seed),
            "--output_file",
            str(config),
        ],
        [
            sys.executable,
            str(_EFUSE_DIR / "generate_efuse_preload.py"),
            str(config),
            "--output_file",
            str(hex_path),
        ],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise AssertionError(
                f"eFuse image generation failed:\n  {exc.cmd}\n"
                f"  stdout: {exc.stdout}\n  stderr: {exc.stderr}"
            ) from exc
        cocotb.log.info("%s", result.stdout.strip())
    return hex_path


class smc_efuse_image_pattern_base(smc_base_test):
    """Sense a full-width pattern image; sweep, write, lock and re-sense the map."""

    pattern = ""

    required_evidence = (
        "CHK-EFUSE-IMG-IMAGE",
        "CHK-EFUSE-IMG-LOCKS-SET-ONLY",
        "CHK-EFUSE-IMG-RESENSE",
        "CHK-EFUSE-IMG-SCOREBOARD",
        "CHK-EFUSE-IMG-SENSE",
        "CHK-EFUSE-IMG-WRITE",
    )
    min_evidence = 6

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        self.image = load_image(write_image(self.pattern, self.random_seed()))

    def _check_image(self) -> None:
        image = self.image
        data = range(2, EFUSE_MAP_WORDS)
        nonzero = sum(1 for w in data if image.words[w])
        assert nonzero, f"{image.path.name} has no non-zero data word; the sweep proves nothing"
        read_locked = [w for w in range(EFUSE_MAP_WORDS) if image.read_locked(w)]
        assert not read_locked, (
            f"{image.path.name} read-locks {len(read_locked)} words; the content sweep "
            "needs every word readable"
        )
        expected_word = _PATTERN_WORD.get(self.pattern)
        if expected_word is not None:
            off = [w for w in data if image.words[w] != expected_word]
            assert not off, (
                f"{image.path.name}: {len(off)} data words differ from 0x{expected_word:08x}, "
                f"first at word {off[0] if off else '-'}"
            )
        otp0 = int(cocotb.top.tb_efuse_otp_word0.value)
        assert otp0 == image.words[0], (
            f"bank-model word 0 is 0x{otp0:08x} but {image.path.name} word 0 is "
            f"0x{image.words[0]:08x}; the generated image did not reach the model"
        )
        write_locked_regions = sorted(
            {region_of(w).name for w in data if image.write_locked(w)}, key=str
        )
        cocotb.log.info(
            "CHK-EFUSE-IMG-IMAGE: %s pattern=%s seed=%d LOCKS=0x%016x, %d of %d data "
            "words non-zero, no read lock, bank-model word 0 matches; write-locked "
            "regions: %s",
            image.path.name,
            self.pattern,
            self.random_seed(),
            image.locks,
            nonzero,
            len(data),
            ", ".join(write_locked_regions) or "none",
        )

    async def run_scenario(self) -> None:
        self._check_image()
        sb = self.env.scoreboard
        before = sb.sys_axi_value_checks_seen
        seq = smc_efuse_image_pattern_test_seq(f"efuse_image_{self.pattern}_seq")
        seq.image = self.image

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

        assert seq.content_compares == [EFUSE_MAP_WORDS, EFUSE_MAP_WORDS], (
            f"content sweeps compared {seq.content_compares} words, expected "
            f"{EFUSE_MAP_WORDS} after sense and again after the cold reset"
        )
        measured = sb.sys_axi_value_checks_seen - before
        assert measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {measured} exact-value SEP_IN AXI compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-EFUSE-IMG-SCOREBOARD: %d >= %d exact-value compares booked by the "
            "scoreboard; %d words compared against the image in each of the two "
            "content sweeps",
            measured,
            EXPECTED_VALUE_CHECKS,
            EFUSE_MAP_WORDS,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"SMC_EFUSE_MAP full sweep over a {self.pattern} image: sense, complement "
                "write, LOCKS set-only and cold-reset re-sense (eFuse bank is the DV model)"
            ),
        )
