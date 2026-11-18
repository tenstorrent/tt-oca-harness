# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse image the JTAG lifecycle leaves sense.

A read of a read-locked shadow register completes with SLVERR and 0xBADCAB1E for
the lock, the same response the lifecycle gate's error slave gives, so a JTAG
read of a read-locked JTAG_PUBLIC_IDENTITY can never show the identity
exception. Each JTAG lifecycle leaf therefore writes its own image into the run
directory, at the relative path its ``+smc_efuse_hex`` names, with every lock
clear, a distinct word in every JTAG_PUBLIC_IDENTITY address and a distinct
non-zero word in every I2C_I3C_ID and SPARE address, none of them 0, all-ones
or the blocked signature: an allowed read is OKAY with the word the image holds
at that address, a blocked one SLVERR with 0xBADCAB1E. LOCKS, SMC_CONFIG and
OCCP_TRANSPORT_TIMEOUT stay 0, because the boot path consumes them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cocotb
from seq_lib.smc_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smc_efuse_image_pattern_test_seq import EfuseImage, load_image
from seq_lib.smc_efuse_vip_utils import EFUSE_BLOCKED_READ_DATA, EFUSE_MAP_BASE

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"

#: Base of the per-word pattern across the sensed JTAG_PUBLIC_IDENTITY window.
IDENTITY_WORD = 0x1D5A9C3E
#: Base of the per-word pattern across the sensed I2C_I3C_ID and SPARE fields.
FILL_WORD = 0x3C5AA5C3
_WORD_MASK = 0xFFFF_FFFF
# 32-bit words per field, from the generated map (efuse_schema.toml regwidth / 32).
_IDENTITY_WORDS = 8
_I2C_I3C_ID_WORDS = 18
_SPARE_WORDS = 224


def identity_word(i: int) -> int:
    """Word ``i`` of the sensed JTAG_PUBLIC_IDENTITY window."""
    return (IDENTITY_WORD ^ (i * 0x0101_0101)) & _WORD_MASK


def fill_word(i: int) -> int:
    """Word ``i`` of the sensed I2C_I3C_ID or SPARE field."""
    return (FILL_WORD ^ (i * 0x0001_0001)) & _WORD_MASK


def _pack(word_of, count: int) -> int:
    value = 0
    for i in range(count):
        w = word_of(i)
        assert w not in (0, _WORD_MASK, EFUSE_BLOCKED_READ_DATA), f"word {i} 0x{w:08x}"
        value |= w << (32 * i)
    return value


_IDENTITY_VALUE = _pack(identity_word, _IDENTITY_WORDS)
_I2C_I3C_ID_VALUE = _pack(fill_word, _I2C_I3C_ID_WORDS)
_SPARE_VALUE = _pack(fill_word, _SPARE_WORDS)

_CONFIG_TEMPLATE = f"""\
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

[LOCKS]
    write_locked = "False"
    read_locked = "False"
    [LOCKS.fields.lock_entries]
    value = 0x0

[JTAG_PUBLIC_IDENTITY]
    write_locked = "False"
    read_locked = "False"
    [JTAG_PUBLIC_IDENTITY.fields.value]
    value = "{_IDENTITY_VALUE:#066x}"

[I2C_I3C_ID]
    write_locked = "False"
    read_locked = "False"
    [I2C_I3C_ID.fields.interface_id]
    value = "{_I2C_I3C_ID_VALUE:#0146x}"

[SMC_CONFIG]
    write_locked = "False"
    read_locked = "False"
    [SMC_CONFIG.fields.smc_config]
    value = 0x0

[OCCP_TRANSPORT_TIMEOUT]
    write_locked = "False"
    read_locked = "False"
    [OCCP_TRANSPORT_TIMEOUT.fields.transport_timeout]
    value = 0x0

[SPARE]
    write_locked = "False"
    read_locked = "False"
    [SPARE.fields.spare_data]
    value = "{_SPARE_VALUE:#01794x}"
"""


def word_index(addr: int) -> int:
    """Index of the SMC_EFUSE_MAP word at ``addr`` in the sensed image."""
    assert addr >= EFUSE_MAP_BASE and addr % 4 == 0, f"0x{addr:08x} is not a map word"
    return (addr - EFUSE_MAP_BASE) // 4


def write_unlocked_image() -> EfuseImage:
    """Render the leaf's image at the path ``+smc_efuse_hex`` names and load its model."""
    plusarg = cocotb.plusargs.get("smc_efuse_hex")
    assert plusarg is not None, "the leaf's testlist entry must name +smc_efuse_hex"
    hex_path = Path(str(plusarg))
    assert not hex_path.is_absolute(), (
        f"+smc_efuse_hex={plusarg} is absolute; this leaf writes the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    hex_path = Path.cwd() / hex_path
    config = hex_path.with_suffix(".toml")
    config.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    cmd = [
        sys.executable,
        str(_EFUSE_DIR / "generate_efuse_preload.py"),
        str(config),
        "--output_file",
        str(hex_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise AssertionError(
            f"eFuse image generation failed:\n  {exc.cmd}\n"
            f"  stdout: {exc.stdout}\n  stderr: {exc.stderr}"
        ) from exc
    cocotb.log.info("%s", result.stdout.strip())
    image = load_image(hex_path)
    assert image.locks == 0, (
        f"{hex_path.name} senses LOCKS = 0x{image.locks:016x}; a lock would answer "
        "SLVERR for the lock and hide the lifecycle gate"
    )
    for name, base, count, word_of in (
        (
            "JTAG_PUBLIC_IDENTITY",
            smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR"),
            _IDENTITY_WORDS,
            identity_word,
        ),
        (
            "I2C_I3C_ID",
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", 0),
            _I2C_I3C_ID_WORDS,
            fill_word,
        ),
        (
            "SPARE",
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0),
            _SPARE_WORDS,
            fill_word,
        ),
    ):
        first = word_index(base)
        for i in range(count):
            got = image.words[first + i]
            assert got == word_of(i), (
                f"{hex_path.name} {name} word {i} (map word {first + i}) is 0x{got:08x}, "
                f"not 0x{word_of(i):08x}"
            )
    assert EFUSE_BLOCKED_READ_DATA not in image.words, (
        f"{hex_path.name} holds the blocked signature as a data word"
    )
    return image
