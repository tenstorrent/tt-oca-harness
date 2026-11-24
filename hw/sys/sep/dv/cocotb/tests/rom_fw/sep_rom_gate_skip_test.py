# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One gate stamp, or one half of it, is skipped after [S17]; the self-check halts with 0xF004.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger):

* "Four acceptance gates each record a bit in a `gate_ok` word *and* clear the same bit in a
  complement word `gate_inv` as they pass".
* SEP-ROM-HOFF-040: "the ROM shall require `gate_ok == BOOT_GATE_EXPECT` *and*
  `gate_inv == ~BOOT_GATE_EXPECT` (`0xFFFF_FFF0`). A skipped gate leaves both words wrong".
* SEP-ROM-HOFF-050: "Any shortfall or disagreement is fatal
  (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."
* "A boot that does not enforce secure boot therefore stamps CRYPTO at that point too."

Each leaf replaces one ROM instruction once DMA_INIT_OK ([S20], after the [S17] self-hash)
is on the console: the call of one gate's stamp function (the whole stamp), or one of the two
stores inside it. CRYPTO runs once on a secure-boot PROD image over SPI, where the signature
is verified (RSA_VERIFY_OK), and once on the SMC-SRAM image that does not enforce secure boot
(SBOOT_OFF).

Checks: CHK-STAMP-WITHHELD (the replaced instruction retired as the replacement, and the DCCM
read-back of gate_ok/gate_inv shows exactly the withheld half or both halves of that gate
missing), CHK-OTHER-STAMPS (every other gate's two stores retired), and the halt contract of
sep_rom_gate_ledger_base.grade_halt with the halt at the ledger evaluation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import (
    AFTER_S17_LINE,
    GATE_BIT,
    GATES,
    INSN_NOP,
    sep_rom_gate_ledger_base,
)

_BUILD = Path(__file__).resolve().parents[4] / "bootrom" / "prod" / "build"
SECURE_FLASH_IMAGE = os.fspath(_BUILD / "oca_secure_boot.bin")


class sep_rom_gate_withheld_base(sep_rom_gate_ledger_base):
    """Withholds ``part`` (call, gate_ok or gate_inv) of one gate's stamp."""

    gate = "manifest"
    part = "call"
    premise_line: str | None = None

    def site(self) -> int:
        if self.part == "call":
            sites = self.img.calls(f"gate_stamp_{self.gate}")
            assert len(sites) == 1, f"gate_stamp_{self.gate} is called from {sites}"
            return sites[0]
        ok, inv = self.stamp_stores(self.gate)
        return ok if self.part == "gate_ok" else inv

    def extra_watch(self) -> set[int]:
        return {self.site()}

    async def inject(self, obs) -> None:
        await self.wait_line(obs, AFTER_S17_LINE)
        await self.patch({self.site(): INSN_NOP})

    def grade(self, obs, chk) -> None:
        if self.premise_line is not None:
            t = obs.line_t(self.premise_line)
            chk.ctrl("BOOT-MODE", t is not None, line=self.premise_line, line_ps=t if t else -1)
        site = self.site()
        nop = self.retired_as(obs, site, INSN_NOP)
        bit = GATE_BIT[self.gate]
        gate_ok, gate_inv = self.ledger_readback()
        want_ok = 0 if self.part in ("call", "gate_ok") else bit
        want_inv = bit if self.part in ("call", "gate_inv") else 0
        ok_store, inv_store = self.stamp_stores(self.gate)
        kept = {"gate_ok": inv_store, "gate_inv": ok_store}.get(self.part)
        chk.ok(
            "STAMP-WITHHELD",
            bool(nop)
            and gate_ok & bit == want_ok
            and gate_inv & bit == want_inv
            and (kept is None or bool(obs.at(kept))),
            gate=self.gate,
            part=self.part,
            site=f"0x{site:08x}",
            site_retired_as_nop=len(nop),
            other_half_retired=None if kept is None else len(obs.at(kept)),
            gate_ok=f"0x{gate_ok:08x}",
            gate_inv=f"0x{gate_inv:08x}",
        )
        reset_t = self.last_reset_t(obs)
        others = {g: self.stamps_retired(obs, g, reset_t) for g in GATES if g != self.gate}
        chk.ok("OTHER-STAMPS", all(others.values()), **others)
        self.grade_halt(obs, chk, kind="eval", check="check_ledger")


@pyuvm.test()
class sep_rom_gate_skip_manifest_test(sep_rom_gate_withheld_base):
    gate = "manifest"


@pyuvm.test()
class sep_rom_gate_skip_crypto_secure_test(sep_rom_gate_withheld_base):
    gate = "crypto"
    flash_image = SECURE_FLASH_IMAGE
    efuse_from_preload = True
    premise_line = "RSA_VERIFY_OK"


@pyuvm.test()
class sep_rom_gate_skip_crypto_nonsecure_test(sep_rom_gate_withheld_base):
    gate = "crypto"
    premise_line = "SBOOT_OFF"


@pyuvm.test()
class sep_rom_gate_skip_hash_test(sep_rom_gate_withheld_base):
    gate = "hash"


@pyuvm.test()
class sep_rom_gate_skip_fuselock_test(sep_rom_gate_withheld_base):
    gate = "fuselock"


@pyuvm.test()
class sep_rom_gate_ok_withheld_test(sep_rom_gate_withheld_base):
    gate = "hash"
    part = "gate_ok"


@pyuvm.test()
class sep_rom_gate_inv_withheld_test(sep_rom_gate_withheld_base):
    gate = "hash"
    part = "gate_inv"
