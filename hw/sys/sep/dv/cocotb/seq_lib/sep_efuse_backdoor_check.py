# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backdoor shadow-readout checker for the SEP eFuse OSS flow.

Reads the sensed shadow-register array directly via the top-level
``efuse_shadow_probe_o`` (a top-level port driven by an XMR in tb_top) and
compares each word against the golden ``SepEfuseImage``. This is the default,
fast (no-AXI) data-comparison path -- it catches sense-load bugs. The AXI front-door checker
(``sep_efuse_shadow_check_seq``) additionally exercises the real read datapath
and runs in the eFuse frontdoor tests.
"""

from __future__ import annotations

from typing import List, Optional

import cocotb
from env.sep_efuse_field_map import spec_secret_regs
from env.sep_efuse_image import WORD_BITS, WORD_MASK, SepEfuseImage


def check_efuse_shadow_backdoor(
    logger,
    image: SepEfuseImage,
    *,
    fields: Optional[List[str]] = None,
    dut=None,
    secure_tm: int = 0,
) -> None:
    """Compare the backdoor-read shadow array against the golden image.

    Raises AssertionError (failing the test) if any word mismatches, mirroring
    the front-door scoreboard's fail-on-error semantics.

    ``secure_tm`` must match the strap the DUT actually latched. With it
    asserted the four KM-secret fields must not read back their staged
    values; other words still match the golden.
    """
    if dut is None:
        dut = cocotb.top
    # Fast path: fully-resolved array -> one int. If any bit is X/Z, fall back to
    # a per-word read so a mismatch names the *word* that is unresolved instead
    # of collapsing the whole 8192-bit vector into one opaque failure.
    try:
        sensed = int(dut.efuse_shadow_probe_o.value)

        def read_word(i: int):
            return (sensed >> (WORD_BITS * i)) & WORD_MASK
    except ValueError:
        bits = str(dut.efuse_shadow_probe_o.value)  # MSB-first, NumEfuseBits chars
        nbits = len(bits)

        def read_word(i: int):
            chunk = bits[nbits - WORD_BITS * (i + 1) : nbits - WORD_BITS * i]
            if "x" in chunk.lower() or "z" in chunk.lower():
                return None  # unresolved
            return int(chunk, 2)

    field_names = fields if fields is not None else image.check_fields()
    secret_regs = frozenset(spec_secret_regs())
    errors: List[str] = []
    checked = 0
    for name in field_names:
        fld = SepEfuseImage.field(name)
        for k in range(fld.n_words):
            widx = fld.word + k
            got = read_word(widx)
            staged = image.words[widx] & WORD_MASK
            checked += 1
            if secure_tm and name in secret_regs:
                if got is None:
                    errors.append(f"{name}[{k}] word{widx}: sensed X/Z under secure_tm")
                elif staged == 0:
                    errors.append(
                        f"{name}[{k}] word{widx}: staged 0, so a disconnect check cannot fail"
                    )
                elif got == staged:
                    errors.append(
                        f"{name}[{k}] word{widx}: still presents staged "
                        f"0x{staged:08x} under secure_tm"
                    )
                continue
            exp = image.shadow_word(widx)
            if got is None:
                errors.append(f"{name}[{k}] word{widx}: sensed X/Z (expected 0x{exp:08x})")
            elif got != exp:
                errors.append(f"{name}[{k}] word{widx}: sensed 0x{got:08x} != expected 0x{exp:08x}")
    for e in errors:
        logger.error("EFUSE BACKDOOR FAIL: %s", e)
    logger.info(
        "eFuse backdoor check: %d words, %d error(s), secure_tm=%d", checked, len(errors), secure_tm
    )
    # Guard against a vacuous "0 words, 0 error(s)" pass. Only meaningful for a
    # whole-image compare: a caller that asked for a subset via fields= is not
    # expected to span the image, and asserting the full count there would fail
    # every such call.
    if fields is None:
        assert checked == len(image.words), (
            f"eFuse backdoor check covered {checked} words, expected all "
            f"{len(image.words)}: the field table does not span the image"
        )
    assert not errors, (
        f"eFuse backdoor shadow check found {len(errors)} mismatch(es): " + "; ".join(errors[:8])
    )
