# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A MANIFEST stamp from a failed SPI slot attempt does not count for the backup attempt.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger):

* "Every manifest slot attempt ([S23]) starts the ledger again: `gate_ok = 0`,
  `gate_inv = 0xFFFF_FFFF` and the recorded manifest length 0, so a stamp from a failed
  attempt never carries into a later one."
* SEP-ROM-HOFF-040: "the ROM shall require `gate_ok == BOOT_GATE_EXPECT` *and*
  `gate_inv == ~BOOT_GATE_EXPECT`".
* SEP-ROM-HOFF-050: "Any shortfall or disagreement is fatal
  (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."

The boot reads an SPI image whose primary payload digest is zeroed without resealing, so the
primary attempt validates its manifest (MANIFEST stamped) and then fails the payload hash
(MANIFEST_ERR = OCA_FAIL_PAYLOAD_HASH); failover is SPI-only, as the code decides. Once the
primary's MANIFEST stamp has retired, the call of the MANIFEST stamp is replaced by a nop, so
the backup attempt stamps CRYPTO and HASH but not MANIFEST.

Checks: CHK-PRIMARY-STAMPED (the primary's MANIFEST stores retired between the first and the
second ledger reset), CHK-BACKUP-UNSTAMPED (the nop retired after the second reset and the
DCCM read-back shows CRYPTO, HASH and FUSELOCK only), and the halt contract with the halt at
the ledger evaluation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_rom_gate_ledger_base import GATE_BIT, INSN_NOP, sep_rom_gate_ledger_base

_BUILD = Path(__file__).resolve().parents[4] / "bootrom" / "prod" / "build"
ERR_PAYLOAD_HASH = mm.boot_err("OCA_FAIL_PAYLOAD_HASH")


@pyuvm.test()
class sep_rom_gate_failover_reset_test(sep_rom_gate_ledger_base):
    flash_image = os.fspath(_BUILD / "oca_non_secure_boot.bin")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert not pm.is_encrypted(buf, "primary"), "the primary payload must be cleartext"
        planted = pm.corrupt_toc_entry_hash(buf, "primary", 0, value=b"\x00" * 32, reseal=False)
        self.chk.info("PRIMARY-DIGEST-ZEROED", digest=planted.hex())
        return buf

    def site(self) -> int:
        sites = self.img.calls("gate_stamp_manifest")
        assert len(sites) == 1, f"gate_stamp_manifest is called from {sites}"
        return sites[0]

    def extra_watch(self) -> set[int]:
        return {self.site()}

    async def inject(self, obs) -> None:
        ok, _ = self.stamp_stores("manifest")
        await self.wait_hit(obs, ok)
        await self.patch({self.site(): INSN_NOP})

    def grade(self, obs, chk) -> None:
        reset = [r.t_ps for r in obs.at(self.img.func("gate_ledger_reset")[0])]
        chk.ctrl("TWO-ATTEMPTS", len(reset) == 2, resets=reset)
        lines = obs.lines()
        err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_HASH:08x}"
        chk.ctrl(
            "PRIMARY-FAILED-ON-HASH",
            any("MANIFEST_PRIMARY" in s for s in lines)
            and any(err in s for s in lines)
            and any("MANIFEST_BACKUP" in s for s in lines),
            want=err,
        )
        ok, inv = self.stamp_stores("manifest")
        second = reset[1] if len(reset) == 2 else None
        primary = [
            r.t_ps
            for r in obs.at(ok) + obs.at(inv)
            if second is not None and reset[0] < r.t_ps < second
        ]
        chk.ok("PRIMARY-STAMPED", len(primary) == 2, primary_stamp_stores_ps=primary)
        nop = [r for r in self.retired_as(obs, self.site(), INSN_NOP) if second and r.t_ps > second]
        gate_ok, gate_inv = self.ledger_readback()
        want = GATE_BIT["crypto"] | GATE_BIT["hash"] | GATE_BIT["fuselock"]
        chk.ok(
            "BACKUP-UNSTAMPED",
            bool(nop) and gate_ok == want and gate_inv == (~want) & 0xFFFF_FFFF,
            site=f"0x{self.site():08x}",
            nop_after_second_reset=len(nop),
            gate_ok=f"0x{gate_ok:08x}",
            gate_inv=f"0x{gate_inv:08x}",
        )
        self.grade_halt(obs, chk, kind="eval", check="check_ledger")
