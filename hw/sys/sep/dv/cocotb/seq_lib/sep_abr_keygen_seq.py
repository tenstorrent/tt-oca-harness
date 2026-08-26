# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-DSA-87 keyGen driver (sep_abr_mldsa_keygen_kat_test).

Aperture base is the ``sep_crypto_pkg`` localparam (not a generated map
symbol). Register offsets are the ``abr_reg_uvm.sv`` add_reg/add_submap
addresses. Identity words come from ``abr_params_pkg::MLDSA_CORE_NAME``.
32-bit beats (size=2) on the 64-bit port; STATUS at +0x14 is an odd-word
offset with no width converter.
"""

from __future__ import annotations

import re
from pathlib import Path

from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

_SEP_RTL = Path(__file__).resolve().parents[3] / "rtl"
_REPO = Path(__file__).resolve().parents[6]
_PKG = _SEP_RTL / "sep_crypto_pkg.sv"
_UVM = (
    _REPO / "vendor" / "chipsalliance" / "adams-bridge" / "upstream"
    / "src" / "abr_top" / "rtl" / "abr_reg_uvm.sv"
)
_PARAMS = (
    _REPO / "vendor" / "chipsalliance" / "adams-bridge" / "upstream"
    / "src" / "abr_top" / "rtl" / "abr_params_pkg.sv"
)


def _pkg_u32(name: str) -> int:
    text = _PKG.read_text()
    m = re.search(rf"localparam logic \[31:0\] {name} = 32'h([0-9A-Fa-f_]+);", text)
    if not m:
        raise RuntimeError(f"{name} not found in {_PKG}")
    return int(m.group(1).replace("_", ""), 16)


def _uvm_reg_off(name: str) -> int:
    text = _UVM.read_text()
    m = re.search(rf"add_reg\(this\.{name}, 'h([0-9a-fA-F]+)\)", text)
    if not m:
        raise RuntimeError(f"{name} add_reg not found in {_UVM}")
    return int(m.group(1), 16)


def _uvm_array_base(name: str) -> int:
    text = _UVM.read_text()
    m = re.search(
        rf"add_reg\(this\.{name}\[i0\], 'h([0-9a-fA-F]+) \+ i0\*'h4\)",
        text,
    )
    if not m:
        raise RuntimeError(f"{name}[i0] add_reg not found in {_UVM}")
    return int(m.group(1), 16)


def _uvm_submap_off(name: str) -> int:
    text = _UVM.read_text()
    m = re.search(
        rf"add_submap\(this\.{name}\.default_map, 'h([0-9a-fA-F]+)\)",
        text,
    )
    if not m:
        raise RuntimeError(f"{name} add_submap not found in {_UVM}")
    return int(m.group(1), 16)


def _mldsa_core_name() -> tuple[int, int]:
    text = _PARAMS.read_text()
    m = re.search(
        r"MLDSA_CORE_NAME\s*=\s*64'h([0-9A-Fa-f]+)_([0-9A-Fa-f]+);",
        text,
    )
    if not m:
        raise RuntimeError(f"MLDSA_CORE_NAME not found in {_PARAMS}")
    hi = int(m.group(1), 16)
    lo = int(m.group(2), 16)
    return lo, hi


ABR_BASE = _pkg_u32("ABR_REG_MAP_BASE_ADDR")
ABR_NAME0 = ABR_BASE + _uvm_array_base("MLDSA_NAME")
ABR_NAME1 = ABR_NAME0 + 4
ABR_CTRL = ABR_BASE + _uvm_reg_off("MLDSA_CTRL")
ABR_STATUS = ABR_BASE + _uvm_reg_off("MLDSA_STATUS")
ABR_ENTROPY = ABR_BASE + _uvm_array_base("ABR_ENTROPY")
ABR_SEED = ABR_BASE + _uvm_array_base("MLDSA_SEED")
ABR_PUBKEY = ABR_BASE + _uvm_submap_off("MLDSA_PUBKEY")
ABR_INTR = ABR_BASE + _uvm_submap_off("intr_block_rf")
ABR_GLOBAL_INTR_EN = ABR_INTR + 0x0
ABR_ERROR_INTR_EN = ABR_INTR + 0x4
ABR_NOTIF_INTR_EN = ABR_INTR + 0x8
ABR_ERROR_INTR = ABR_INTR + _uvm_reg_off("error_internal_intr_r")
ABR_ERROR_TRIG = ABR_INTR + _uvm_reg_off("error_intr_trig_r")
ABR_NOTIF_INTR = ABR_INTR + _uvm_reg_off("notif_internal_intr_r")

NAME0_EXP, NAME1_EXP = _mldsa_core_name()

CMD_KEYGEN = 0x1
CTRL_ZEROIZE = 1 << 3
ST_READY = 1 << 0
ST_VALID = 1 << 1
ST_ERROR = 1 << 3

SEED_WORDS = 8
ENTROPY_WORDS = 16
PK_WORDS = 648

IRQ_ABR_ERROR = 34
IRQ_ABR_NOTIF = 35

# global_intr_en_r: error_en[0] + notif_en[1]; per-event enables at +4/+8 bit 0.
INTR_GLOBAL_BOTH = 0x3
INTR_EVENT_EN = 0x1


class SepAbrKeygenCfg:
    """RANDCFG: masking entropy words, and which seed word/bit the sensitivity flips."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        if not any(w != 0 for w in self.entropy):
            self.entropy[0] = 0xA5A5A5A5
        self.flip_word = rng.randrange(SEED_WORDS)
        self.flip_bit = rng.randrange(32)

    def flipped_seed(self, seed_words: list[int]) -> list[int]:
        out = list(seed_words)
        out[self.flip_word] ^= 1 << self.flip_bit
        return out

    def summary(self) -> str:
        return (
            f"seed={self.seed} flip_word={self.flip_word} flip_bit={self.flip_bit} "
            f"entropy[0]=0x{self.entropy[0]:08x}"
        )


class SepAbr(SepAxiRegDriver):
    """32-bit ABR CSR / memory-window driver on the CPU-LSU bus."""

    _DRIVER_TAG = "ABR"

    async def wr32(self, addr: int, data: int) -> None:
        await self._wr(addr, data & 0xFFFF_FFFF)

    async def rd32(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_words(self, base: int, words: list[int]) -> None:
        for i, w in enumerate(words):
            await self.wr32(base + 4 * i, w)

    async def read_words(self, base: int, n: int) -> list[int]:
        return [await self.rd32(base + 4 * i) for i in range(n)]

    async def enable_notif(self) -> None:
        await self.wr32(ABR_GLOBAL_INTR_EN, INTR_GLOBAL_BOTH)
        await self.wr32(ABR_ERROR_INTR_EN, INTR_EVENT_EN)
        await self.wr32(ABR_NOTIF_INTR_EN, INTR_EVENT_EN)

    async def trigger_error(self) -> None:
        """Pulse error_intr_trig (single-cycle W1S) to set error_internal_sts."""
        await self.wr32(ABR_ERROR_TRIG, INTR_EVENT_EN)

    async def error_state(self) -> int:
        return await self.rd32(ABR_ERROR_INTR)

    async def w1c_error(self) -> int:
        """W1C error_internal_sts; return the post-clear readback."""
        await self.wr32(ABR_ERROR_INTR, INTR_EVENT_EN)
        return await self.rd32(ABR_ERROR_INTR)

    async def notif_state(self) -> int:
        return await self.rd32(ABR_NOTIF_INTR)

    async def w1c_notif(self) -> int:
        """W1C notif_cmd_done_sts; return the post-clear readback."""
        await self.wr32(ABR_NOTIF_INTR, INTR_EVENT_EN)
        return await self.rd32(ABR_NOTIF_INTR)


def _selftest() -> None:
    assert ABR_BASE == 0x1094_0000
    assert ABR_CTRL - ABR_BASE == 0x10
    assert ABR_STATUS - ABR_BASE == 0x14
    assert ABR_ENTROPY - ABR_BASE == 0x18
    assert ABR_SEED - ABR_BASE == 0x58
    assert ABR_PUBKEY - ABR_BASE == 0x1000
    assert ABR_ERROR_INTR - ABR_INTR == 0x14
    assert ABR_ERROR_TRIG - ABR_INTR == 0x1c
    assert ABR_NOTIF_INTR - ABR_INTR == 0x18
    assert NAME0_EXP == 0x44534D4C
    assert NAME1_EXP == 0x3837412D
    cfg = SepAbrKeygenCfg(1)
    assert len(cfg.entropy) == ENTROPY_WORDS
    flipped = cfg.flipped_seed([0] * SEED_WORDS)
    assert flipped[cfg.flip_word] == (1 << cfg.flip_bit)


_selftest()
