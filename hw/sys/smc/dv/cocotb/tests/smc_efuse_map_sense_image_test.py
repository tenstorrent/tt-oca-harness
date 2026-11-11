# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense of the default asset and of five generated images after a deliberate cold reset.

Sources: smu-smc.adoc (eFuse Interface), port_table.adoc (smc_fuse_sense_done_o, shadow_regs_o).

One module, six testlist entries. Without ``+smc_efuse_image`` the bench default asset is sensed;
``+smc_efuse_image=<zero|ones|walking|random|unique>`` writes that image into the run directory
during ``build_phase``: word 0 (the low HARNESS_LOCKS word) carries write-lock bits only and
words 1..63 carry the pattern. Words 1..3 are the upper HARNESS_LOCKS word and the two
SUPPLEMENTARY_LOCKS words: the shadow file stores and returns them like every other word, and
the supplementary locks a pattern sets there gate only the supplementary window, which this
leaf never accesses.
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_efuse_image_pattern_test_seq import EFUSE_MAP_WORDS, REGIONS, load_image
from seq_lib.smc_efuse_map_sense_image_test_seq import smc_efuse_map_sense_image_test_seq
from seq_lib.smc_efuse_vip_utils import EFUSE_DEFAULT_HEX
from smc_base_test import smc_base_test

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"
_MASK32 = 0xFFFF_FFFF
_KINDS = ("zero", "ones", "walking", "random", "unique")
_COMMON = ("CHK-EMAP-SENSE-FIRST-DONE", "CHK-EMAP-SENSE-DONE-ONCE")
_TAIL = ("CHK-EMAP-SHADOW-OUT-SENSED", "CHK-NONVAC", "CHK-TIMEOUT-PATHS")
_SENSE_CHK = {
    "default": "CHK-EMAP-SENSE-DEFAULT",
    "unique": "CHK-EMAP-SENSE-UNIQUE",
}
#: Schema blocks after LOCKS: (block, field, first map word, word count); LOCKS is words 0..3.
_FIELDS = (
    ("JTAG_PUBLIC_IDENTITY", "value", 4, 8),
    ("I2C_I3C_ID", "interface_id", 12, 18),
    ("SMC_CONFIG", "smc_config", 30, 2),
    ("OCCP_TRANSPORT_TIMEOUT", "transport_timeout", 32, 2),
    ("SPARE", "spare_data", 34, 30),
)
_LOCKS_WORDS = _FIELDS[0][2]


_WRITE_LOCKS = tuple(sorted({region.write_lock for region in REGIONS}))


def _or_bits(bits) -> int:
    value = 0
    for bit in bits:
        value |= bit
    return value


_READ_LOCKS = _or_bits(region.read_lock for region in REGIONS)
assert all(bit <= _MASK32 for bit in _WRITE_LOCKS), "a HARNESS_LOCKS write lock is above word 0"


def _lock_word(kind: str, rnd: random.Random) -> int:
    """Word 0 of the kind: HARNESS_LOCKS write-lock bits only."""
    if kind in ("zero", "walking"):
        return min(_WRITE_LOCKS)
    if kind in ("ones", "unique"):
        return _or_bits(_WRITE_LOCKS)
    return _or_bits(bit for bit in _WRITE_LOCKS if rnd.getrandbits(1))


def _image_words(kind: str, seed: int) -> list[int]:
    """Words 0..63 of the kind: word 0 holds the write locks, words 1..63 carry the pattern."""
    rnd = random.Random(seed)
    pattern = {
        "zero": lambda n: 0,
        "ones": lambda n: 0xFFFF_FFFF,
        "walking": lambda n: 1 << (n % 32),
        "random": lambda n: rnd.getrandbits(32),
        "unique": lambda n: 0x5A5A0000 | (n << 8) | (0xA5 ^ n),
    }[kind]
    return [_lock_word(kind, rnd)] + [pattern(n) for n in range(1, EFUSE_MAP_WORDS)]


def _config_text(words: list[int]) -> str:
    lines = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "[LOCKS]",
        '    write_locked = "False"',
        '    read_locked = "False"',
        "    [LOCKS.fields.lock_entries]",
        f"    value = 0x{sum(words[k] << (32 * k) for k in range(_LOCKS_WORDS)):x}",
    ]
    for block, field, first, count in _FIELDS:
        value = sum(words[first + k] << (32 * k) for k in range(count))
        lines += [
            "",
            f"[{block}]",
            '    write_locked = "False"',
            '    read_locked = "False"',
            f"    [{block}.fields.{field}]",
            f"    value = 0x{value:x}",
        ]
    return "\n".join(lines) + "\n"


def write_image(kind: str, seed: int) -> tuple[Path, list[int]]:
    """Render the kind's image at the path ``+smc_efuse_hex`` names."""
    plusarg = cocotb.plusargs.get("smc_efuse_hex")
    assert plusarg is not None, "the leaf's testlist entry must name +smc_efuse_hex"
    hex_path = Path(str(plusarg))
    assert not hex_path.is_absolute(), (
        f"+smc_efuse_hex={plusarg} is absolute; this leaf writes the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    hex_path = Path.cwd() / hex_path
    words = _image_words(kind, seed)
    config = hex_path.with_suffix(".toml")
    config.write_text(_config_text(words), encoding="utf-8")
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
    return hex_path, words


@pyuvm.test()
class smc_efuse_map_sense_image_test(smc_base_test):
    """Sense an image after a cold reset; compare the probe, SEP_IN reads and the shadow port."""

    auto_protocol_vip = False

    run_written_file_plusargs: tuple[str, ...] = ()
    # The default image; build_phase replaces the sense checker with the selected image's.
    required_evidence = (
        "CHK-EMAP-SENSE-DEFAULT",
        "CHK-EMAP-SENSE-DONE-ONCE",
        "CHK-EMAP-SENSE-FIRST-DONE",
        "CHK-EMAP-SHADOW-OUT-SENSED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    KIND = "default"
    min_evidence = 5

    def build_phase(self) -> None:
        self.kind = str(cocotb.plusargs.get("smc_efuse_image", self.KIND))
        assert self.kind == "default" or self.kind in _KINDS, (
            f"+smc_efuse_image={self.kind} is not one of {_KINDS}"
        )
        sense = _SENSE_CHK.get(self.kind, "CHK-EMAP-SENSE-PATTERNS")
        self.required_evidence = (_COMMON[0], sense, _COMMON[1], *_TAIL)
        self.min_evidence = len(self.required_evidence)
        if self.kind != "default":
            self.run_written_file_plusargs = ("smc_efuse_hex",)
        super().build_phase()
        if self.kind == "default":
            named = cocotb.plusargs.get("smc_efuse_hex")
            assert named is None or Path(str(named)).resolve() == EFUSE_DEFAULT_HEX.resolve(), (
                f"+smc_efuse_hex={named} is not the bench default asset {EFUSE_DEFAULT_HEX}"
            )
            self.image = load_image(EFUSE_DEFAULT_HEX)
        else:
            path, words = write_image(self.kind, self.random_seed())
            self.image = load_image(path)
            assert list(self.image.words) == words, (
                f"{path.name} words differ from the requested {self.kind} pattern at word "
                f"{next(n for n in range(EFUSE_MAP_WORDS) if self.image.words[n] != words[n])}"
            )
            assert list(self.image.words[:_LOCKS_WORDS]) == words[:_LOCKS_WORDS], (
                f"{path.name} LOCKS words {[hex(w) for w in self.image.words[:_LOCKS_WORDS]]} "
                f"differ from the intended {[hex(w) for w in words[:_LOCKS_WORDS]]}"
            )
            assert self.image.locks & _READ_LOCKS == 0, (
                f"{path.name} LOCKS 0x{self.image.locks:x} sets a HARNESS_LOCKS read-lock bit"
            )
            assert self.image.words[0] & ~_or_bits(_WRITE_LOCKS) == 0, (
                f"{path.name} word 0 0x{self.image.words[0]:08x} sets a bit outside the "
                "HARNESS_LOCKS write locks"
            )
            if self.kind == "unique":
                assert len(set(self.image.words)) == EFUSE_MAP_WORDS, (
                    f"{path.name} is not pairwise distinct over {EFUSE_MAP_WORDS} words"
                )
            readlocked = [w for w in range(EFUSE_MAP_WORDS) if self.image.read_locked(w)]
            assert not readlocked, f"{path.name} read-locks words {readlocked}"

    async def run_scenario(self) -> None:
        seq = smc_efuse_map_sense_image_test_seq("smc_efuse_map_sense_image_test_seq")
        seq.image = self.image
        seq.kind = self.kind
        seq.seed = self.random_seed()

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.access_floor > 0 and seq.accesses >= seq.access_floor, (
            f"{seq.accesses} SEP_IN accesses, the sequence computed a floor of {seq.access_floor}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=seq.access_floor,
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                f"eFuse sense of the {self.kind} image after a cold reset with SEP_IN reads "
                "(eFuse bank is the DV model)"
            ),
        )
