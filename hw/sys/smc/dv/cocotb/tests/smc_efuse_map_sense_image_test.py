# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense of the default asset and of five generated images after a deliberate cold reset.

Sources: smu-smc.adoc (eFuse Interface), port_table.adoc (smc_fuse_sense_done_o, shadow_regs_o).

The image kind is the bench default asset or one of zero, ones, walking, random and unique. The
``+smc_efuse_image`` run argument or a subclass ``KIND`` pins it; otherwise build_phase draws it
uniformly from the seed. A generated kind is written into the run directory at the relative
``+smc_efuse_hex`` path during ``build_phase``: words 2..255 carry the pattern and the LOCKS words
0 and 1 carry write-lock bits only. A drawn default kind copies the asset's bytes to that path.
The random kind's words and lock bits come from ``random.Random(seed ^ _WORDS_STREAM)``, a stream
separate from the kind draw.
"""

from __future__ import annotations

import hashlib
import random
import shutil
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
# Seeds the image words apart from the kind draw, which uses the run seed itself.
_WORDS_STREAM = 0x9E37_79B9
_COMMON = ("CHK-EMAP-SENSE-FIRST-DONE", "CHK-EMAP-SENSE-DONE-ONCE")
_TAIL = ("CHK-EMAP-SHADOW-OUT-SENSED", "CHK-NONVAC", "CHK-TIMEOUT-PATHS")
_SENSE_CHK = {
    "default": "CHK-EMAP-SENSE-DEFAULT",
    "unique": "CHK-EMAP-SENSE-UNIQUE",
}
_FIELDS = (
    ("JTAG_PUBLIC_IDENTITY", "value", 2, 8),
    ("I2C_I3C_ID", "interface_id", 10, 18),
    ("SMC_CONFIG", "smc_config", 28, 2),
    ("OCCP_TRANSPORT_TIMEOUT", "transport_timeout", 30, 2),
    ("SPARE", "spare_data", 32, 224),
)


_WRITE_LOCKS = tuple(region.write_lock for region in REGIONS)
_WRITE_LOCKS_LO = tuple(bit for bit in _WRITE_LOCKS if bit <= _MASK32)
_WRITE_LOCKS_HI = tuple(bit >> 32 for bit in _WRITE_LOCKS if bit > _MASK32)
_READ_LOCKS = sum(region.read_lock for region in REGIONS)


def _or_bits(bits) -> int:
    value = 0
    for bit in bits:
        value |= bit
    return value


def _lock_words(kind: str, rnd: random.Random) -> list[int]:
    """LOCKS words 0 and 1 of the kind, write-lock bits only."""
    if kind == "zero":
        return [min(_WRITE_LOCKS_LO), 0]
    if kind == "ones":
        return [_or_bits(_WRITE_LOCKS_LO), _or_bits(_WRITE_LOCKS_HI)]
    if kind == "unique":
        return [_or_bits(_WRITE_LOCKS_LO), _or_bits(_WRITE_LOCKS_HI[::2])]
    if kind == "walking":
        return [min(_WRITE_LOCKS_LO), min(_WRITE_LOCKS_HI)]
    return [
        _or_bits(bit for bit in _WRITE_LOCKS_LO if rnd.getrandbits(1)),
        _or_bits(bit for bit in _WRITE_LOCKS_HI if rnd.getrandbits(1)),
    ]


def _image_words(kind: str, seed: int) -> list[int]:
    """Words 0..255 of the kind: words 0 and 1 hold LOCKS, words 2..255 carry the pattern."""
    rnd = random.Random(seed)
    pattern = {
        "zero": lambda n: 0,
        "ones": lambda n: 0xFFFF_FFFF,
        "walking": lambda n: 1 << (n % 32),
        "random": lambda n: rnd.getrandbits(32),
        "unique": lambda n: 0x5A5A0000 | (n << 8) | (0xA5 ^ n),
    }[kind]
    fields = [pattern(n) for n in range(2, EFUSE_MAP_WORDS)]
    return _lock_words(kind, rnd) + fields


def _config_text(words: list[int]) -> str:
    lines = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "[LOCKS]",
        '    write_locked = "False"',
        '    read_locked = "False"',
        "    [LOCKS.fields.lock_entries]",
        f"    value = 0x{words[0] | (words[1] << 32):x}",
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
    # Every kind's checkers; build_phase narrows the tuple to the selected kind's.
    required_evidence = (
        "CHK-EMAP-SENSE-DEFAULT",
        "CHK-EMAP-SENSE-DONE-ONCE",
        "CHK-EMAP-SENSE-FIRST-DONE",
        "CHK-EMAP-SENSE-PATTERNS",
        "CHK-EMAP-SENSE-UNIQUE",
        "CHK-EMAP-SHADOW-OUT-SENSED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    # None draws the kind from the seed; a variant subclass pins one.
    KIND: str | None = None
    min_evidence = 5

    def build_phase(self) -> None:
        # The kind is drawn before super().build_phase(): a written kind must exempt
        # +smc_efuse_hex from the base's time-0 file check.
        seed = self.random_seed()
        pinned = cocotb.plusargs.get("smc_efuse_image", self.KIND)
        self.kind = (
            str(pinned)
            if pinned is not None
            else random.Random(seed).choice(sorted(("default", *_KINDS)))
        )
        assert self.kind == "default" or self.kind in _KINDS, (
            f"image kind {self.kind} is not default or one of {_KINDS}"
        )
        if pinned is None:
            source = "drawn"
        elif "smc_efuse_image" in cocotb.plusargs:
            source = "pinned by +smc_efuse_image"
        else:
            source = "pinned by the class"
        words_seed = seed ^ _WORDS_STREAM
        self.words_seed = words_seed
        if self.kind == "random":
            words_note = f"image words seed 0x{words_seed:x} (seed ^ 0x{_WORDS_STREAM:x})"
        else:
            words_note = f"image words seed unused for {self.kind}"
        self.logger.info(
            "RAND-SEED: %d; RAND-DRAW: cell=%s (%s); %s", seed, self.kind, source, words_note
        )
        sense = _SENSE_CHK.get(self.kind, "CHK-EMAP-SENSE-PATTERNS")
        self.required_evidence = (_COMMON[0], sense, _COMMON[1], *_TAIL)
        self.min_evidence = len(self.required_evidence)
        named = cocotb.plusargs.get("smc_efuse_hex")
        copy_default = (
            self.kind == "default" and named is not None and not Path(str(named)).is_absolute()
        )
        if self.kind != "default" or copy_default:
            self.run_written_file_plusargs = ("smc_efuse_hex",)
        super().build_phase()
        if copy_default:
            # The bank model opens the relative +smc_efuse_hex path; it must hold the asset.
            path = Path.cwd() / str(named)
            shutil.copyfile(EFUSE_DEFAULT_HEX, path)
            asset_sha = hashlib.sha256(EFUSE_DEFAULT_HEX.read_bytes()).hexdigest()
            copy_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            assert copy_sha == asset_sha, (
                f"{path.name} sha256 {copy_sha} differs from the asset's {asset_sha}"
            )
            self.logger.info(
                "eFuse default asset %s copied to %s sha256=%s",
                EFUSE_DEFAULT_HEX.name,
                path.name,
                copy_sha,
            )
            self.image = load_image(path)
        elif self.kind == "default":
            assert named is None or Path(str(named)).resolve() == EFUSE_DEFAULT_HEX.resolve(), (
                f"+smc_efuse_hex={named} is not the bench default asset {EFUSE_DEFAULT_HEX}"
            )
            self.image = load_image(EFUSE_DEFAULT_HEX)
        else:
            path, words = write_image(self.kind, words_seed)
            self.image = load_image(path)
            assert list(self.image.words) == words, (
                f"{path.name} words differ from the requested {self.kind} pattern at word "
                f"{next(n for n in range(EFUSE_MAP_WORDS) if self.image.words[n] != words[n])}"
            )
            assert self.image.words[0] == words[0] and self.image.words[1] == words[1], (
                f"{path.name} LOCKS words 0x{self.image.words[0]:08x}/"
                f"0x{self.image.words[1]:08x} differ from the intended "
                f"0x{words[0]:08x}/0x{words[1]:08x}"
            )
            assert self.image.locks & _READ_LOCKS == 0, (
                f"{path.name} LOCKS 0x{self.image.locks:x} sets a read-lock bit"
            )
            assert self.image.locks & ~_or_bits(_WRITE_LOCKS) == 0, (
                f"{path.name} LOCKS 0x{self.image.locks:x} sets a bit outside the write locks"
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
        seq.words_seed = self.words_seed

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
