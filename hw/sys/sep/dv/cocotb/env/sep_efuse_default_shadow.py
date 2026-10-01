# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Expected sensed eFuse shadow of the committed default preload, as a file.

The SV-UVM ``sep_efuse_sense_test`` compares the post-sense shadow probe
(``tb_vif.efuse_shadow``, NumEfuseBits wide) against a committed file and holds
no mapping logic of its own. This module writes that file from the cocotb
image code: ``SepEfuseImage().load(<default preload>)`` and
``SepEfuseImage.shadow_word()`` for every word, the same golden the cocotb
backdoor check (``seq_lib/sep_efuse_backdoor_check.py``) grades against.

File form: comment lines, then one ``$readmemh`` word of NumEfuseBits bits,
most-significant hex digit first. Bits ``[32*i+31:32*i]`` hold shadow word
``i``, the layout of ``efuse_shadow_probe_o`` in ``tb/tb_top.sv``.

Usage (no simulator needed):
    python3 hw/sys/sep/dv/cocotb/env/sep_efuse_default_shadow.py --write
        regenerate the committed file;
    python3 hw/sys/sep/dv/cocotb/env/sep_efuse_default_shadow.py
        self-test: exit 1 if the committed file differs from a fresh copy
        (run by ``run_golden_selftests.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sep_efuse_image import NUM_FUSE_WORDS, WORD_BITS, WORD_MASK, SepEfuseImage

_PRELOAD_DIR = Path(__file__).resolve().parents[2] / "tb" / "efuse_preloads"
DEFAULT_PRELOAD = _PRELOAD_DIR / "sep_efuse_default.hex"
DEFAULT_SHADOW = _PRELOAD_DIR / "sep_efuse_default.shadow.hex"

_HEADER = (
    "// Expected sensed eFuse shadow of sep_efuse_default.hex (secure_tm=0): one\n"
    "// NumEfuseBits-wide $readmemh word, most-significant hex digit first;\n"
    "// bits [32*i+31:32*i] hold shadow word i. Do not edit. Regenerate with\n"
    "//   python3 hw/sys/sep/dv/cocotb/env/sep_efuse_default_shadow.py --write\n"
    "// cocotb/env/run_golden_selftests.py fails when this file is stale.\n"
)


def shadow_text(preload: Path = DEFAULT_PRELOAD) -> str:
    """Return the expected-shadow file text for ``preload``."""
    image = SepEfuseImage().load(preload)
    value = 0
    for i in range(NUM_FUSE_WORDS):
        value |= (image.shadow_word(i) & WORD_MASK) << (WORD_BITS * i)
    digits = NUM_FUSE_WORDS * WORD_BITS // 4
    return f"{_HEADER}{value:0{digits}x}\n"


def main(argv: list[str]) -> int:
    expected = shadow_text()
    if argv[1:] == ["--write"]:
        DEFAULT_SHADOW.write_text(expected, encoding="utf-8")
        print(f"wrote {DEFAULT_SHADOW}")
        return 0
    if argv[1:]:
        print(f"usage: {argv[0]} [--write]", file=sys.stderr)
        return 2
    if not DEFAULT_SHADOW.is_file():
        print(f"FAIL: {DEFAULT_SHADOW} is missing", file=sys.stderr)
        return 1
    if DEFAULT_SHADOW.read_text(encoding="utf-8") != expected:
        print(
            f"FAIL: {DEFAULT_SHADOW.name} differs from the shadow of {DEFAULT_PRELOAD.name}; "
            f"regenerate with: python3 {Path(__file__).name} --write",
            file=sys.stderr,
        )
        return 1
    print(f"PASS: {DEFAULT_SHADOW.name} matches the shadow of {DEFAULT_PRELOAD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
