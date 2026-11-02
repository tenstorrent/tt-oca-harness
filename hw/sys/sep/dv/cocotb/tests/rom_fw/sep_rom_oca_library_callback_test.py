# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCA library validates the booting manifest and calls the ROM's table callbacks.

rom.adoc, Validation Library Integration:

    [SEP-ROM-MAN-020] The ROM shall validate manifests with the
    freestanding OCA validation library (`validators/oca/lib/`, `oca_validator.h`),
    supplying its hardware bindings through the `oca_callbacks_t` table (SHA-256 via the HMAC
    block, RSA-3072 via OTBN, payload decryption via KDF+AES, identity/lifecycle/version reads
    from fuses, device revocation and security-version state from the efuse map). The library
    holds no static state and performs no device mutation; state commit is a separate explicit
    call (<<sec:secure_boot>>).

rom.adoc, Security inventory, which says which roles the library must call for this manifest:

    |Manifest hash |bytes `[0,3172)`, `manifest_hash` |SHA-256 match (const-time)
    |`OCA_FAIL_MANIFEST_HASH` |*Every boot*, before crypto. MAN-010
    |Key revocation |manifest revoke ∪ device fuse |selected slot not revoked
    |Signature |signed region `[0,3172)`, RSA-3072 via OTBN |PKCS#1 v1.5 verify OK
    |Anti-rollback |`manifest_security_version` vs device flags |bit-superset

rom.adoc, Failure Convergence ([S30]), which names the library entry the ROM uses:

    The whole per-slot sequence runs inside the retry loop: `try_manifest_slot()` performs the
    load, header checks, `oca_validate_manifest()` (including signature verification) and
    `oca_check_payload_at()`, so a slot failing crypto or a payload hash rotates to the backup
    bank like any other slot failure, per SEP-ROM-RETRY-030.

`oca_validator.h`, `oca_validate_manifest()`: "oca_validate() is exactly this followed by
oca_check_payload(), so the canonical order lives in one place and the two entry points cannot
drift." `oca_commit_security_state` is not linked: [SEP-ROM-SB-080] says "*the ROM burns no
fuses*", and the Implementation-Status Matrix lists the device security-state commit as
"*by design*".

The spec roles are the `oca_callbacks_t` members `sha256`, `verify_signature`,
`decrypt_payload`, `get_identity_bytes`, `get_lifecycle_state`, `get_version`,
`get_root_key_revocation` and `get_security_version`. The ROM function for each role is the
pointer in that member of the ROM's callback table, read from the loaded ROM image; the
library text is the address ranges of the `validators/oca/lib/` compile units in the ROM
ELF. The signed image boots under TEST_DEV with `secure_boot_control[0]` set, `selector_bits`
zero and an unencrypted payload, so secure boot is on and no identity, lifecycle, version or
decryption check is selected.

* CHK-TABLE-WIRED: each of the eight role members of the ROM's table holds the entry of a
  ROM function outside the library text (static check of the loaded image).
* CHK-LIBRARY-ENTERED: a library manifest-validation entry (`oca_validate` or
  `oca_validate_manifest`) retires before the `MANIFEST_VALIDATED` status word.
* CHK-CALLBACKS-FROM-LIBRARY: the `sha256`, `verify_signature`, `get_root_key_revocation`
  and `get_security_version` functions are each entered at least once between the last
  library entry and `MANIFEST_VALIDATED`, by a jump that retired from library text.

Partial coverage. Not graded: "via the HMAC block", "via OTBN", "via KDF+AES", "from fuses"
and "from the efuse map" (no bus access is attributed to a callback); the `decrypt_payload`,
`get_identity_bytes`, `get_lifecycle_state` and `get_version` calls, which this manifest
does not select (table wiring only); that the ROM's verdict equals the library's return
value; "holds no static state"; "performs no device mutation"; "state commit is a separate
explicit call". The leaf runs `sep_rom_ot_secure_boot_test` and keeps its checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from elftools.dwarf.ranges import BaseAddressEntry, RangeEntry
from elftools.elf.elffile import ELFFile
from env.sep_chk_log import SepChkLog
from env.sep_manifest_mutate import PRIMARY_MANIFEST_OFFSET
from env.sep_rom_observer import SepRomObserver, load_rom_syms
from env.sep_rv32_trace_decode import OP_JAL, OP_JALR, opcode
from rom_fw.sep_rom_observe_base import ROM_BASE
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test as _Base
from sep_reg_meta import sym

_ROM_SIZE = sym("SEP_BOOT_ROM_MEM_SIZE")
_VMEM_ARG = "sep_boot_rom_hex"
_LIB_DIR = "/validators/oca/lib/"
_TABLE = "sep_callbacks"
_ROLES = (
    "sha256",
    "verify_signature",
    "decrypt_payload",
    "get_identity_bytes",
    "get_lifecycle_state",
    "get_version",
    "get_root_key_revocation",
    "get_security_version",
)
# Roles the library must call for a secure-boot manifest with no selector and no encryption.
_REQUIRED = ("sha256", "verify_signature", "get_root_key_revocation", "get_security_version")
_MANIFEST_ENTRIES = ("oca_validate", "oca_validate_manifest")
_PAYLOAD_ENTRIES = ("oca_check_payload", "oca_check_payload_at")
# STATUS_ENCODE(INFO, BL0, code); codes from hw/sys/sep/doc/gen/status_values.adoc.
_MANIFEST_VALIDATED = 0x0101_0053
_PAYLOAD_VALIDATED = 0x0101_0055
# Manifest byte offsets from rom.adoc tbl:manifest_fields.
_OFF_SELECTOR, _LEN_SELECTOR = 24, 16
_OFF_SB_CONTROL = 182
_OFF_PAYLOAD_ENC = 201


@dataclass(frozen=True)
class _RomLayout:
    syms: dict[str, int]
    units: dict[str, list[tuple[int, int]]]
    lib: list[tuple[int, int]]
    table: int | None
    slots: dict[str, int]

    def in_lib(self, addr: int | None) -> bool:
        return addr is not None and any(lo <= addr < hi for lo, hi in self.lib)

    def name_at(self, addr: int | None) -> str:
        """Nearest symbol at or below addr, for the log."""
        if addr is None:
            return "none"
        best = max(
            ((a, n) for n, a in self.syms.items() if a <= addr),
            default=(0, "?"),
        )
        off = addr - best[0]
        return f"{best[1]}+0x{off:x}" if off else best[1]


def _unit_ranges(elf_path: Path) -> tuple[dict[str, list[tuple[int, int]]], dict[str, int]]:
    """ROM text ranges of every compile unit, and the oca_callbacks member offsets."""
    units: dict[str, list[tuple[int, int]]] = {}
    members: dict[str, int] = {}
    with open(elf_path, "rb") as fh:
        dw = ELFFile(fh).get_dwarf_info()
        lists = dw.range_lists()
        for cu in dw.iter_CUs():
            attrs = cu.get_top_DIE().attributes
            base = attrs["DW_AT_low_pc"].value if "DW_AT_low_pc" in attrs else 0
            out = []
            if "DW_AT_ranges" in attrs:
                for e in lists.get_range_list_at_offset(attrs["DW_AT_ranges"].value, cu=cu):
                    if isinstance(e, BaseAddressEntry):
                        base = e.base_address
                    elif isinstance(e, RangeEntry):
                        rel = 0 if getattr(e, "is_absolute", False) else base
                        out.append((rel + e.begin_offset, rel + e.end_offset))
            elif "DW_AT_high_pc" in attrs:
                hi = attrs["DW_AT_high_pc"]
                out.append((base, hi.value if hi.form == "DW_FORM_addr" else base + hi.value))
            # Sections the linker discarded keep a placeholder address outside the ROM.
            name = attrs["DW_AT_name"].value.decode()
            units[name] = [
                (lo, hi) for lo, hi in out if ROM_BASE <= lo < hi <= ROM_BASE + _ROM_SIZE
            ]
            if members:
                continue
            for die in cu.iter_DIEs():
                a = die.attributes
                if (
                    die.tag == "DW_TAG_structure_type"
                    and die.has_children
                    and a.get("DW_AT_name") is not None
                    and a["DW_AT_name"].value == b"oca_callbacks"
                ):
                    members = {
                        c.attributes["DW_AT_name"].value.decode(): c.attributes[
                            "DW_AT_data_member_location"
                        ].value
                        for c in die.iter_children()
                        if c.tag == "DW_TAG_member"
                    }
                    break
    return units, members


def _vmem_bytes(path: Path) -> bytes:
    """The ROM aperture bytes of a $readmemh image of 64-bit little-endian words."""
    words: dict[int, int] = {}
    addr = 0
    for tok in path.read_text().split():
        if tok.startswith("@"):
            addr = int(tok[1:], 16)
            continue
        words[addr] = int(tok, 16)
        addr += 1
    out = bytearray(8 * (max(words) + 1))
    for i, w in words.items():
        out[8 * i : 8 * i + 8] = w.to_bytes(8, "little")
    return bytes(out)


def _rom_layout(vmem: Path) -> _RomLayout:
    syms = load_rom_syms(vmem.with_name("boot_rom.sym"))
    units, members = _unit_ranges(vmem.with_name("boot_rom.elf"))
    lib = sorted(r for name, rs in units.items() if _LIB_DIR in name for r in rs)
    image = _vmem_bytes(vmem)
    table = syms.get(_TABLE)
    slots = {}
    for role, off in members.items():
        at = None if table is None else table - ROM_BASE + off
        if at is not None and 0 <= at and at + 4 <= len(image):
            slots[role] = int.from_bytes(image[at : at + 4], "little")
    return _RomLayout(syms, units, lib, table, slots)


class _CallObserver(SepRomObserver):
    """Also keeps the PC and instruction retired just before each watched-PC hit."""

    def __init__(self, test, pc_watch: frozenset[int], **kwargs) -> None:
        super().__init__(test, pc_watch=pc_watch, **kwargs)
        self._watch_pcs = pc_watch
        self.hit_from: list[tuple[int, int] | None] = []
        self._last: tuple[int, int] | None = None

    def record(self, t: int, pc: int, insn: int, exc: bool, ecause: int, interrupt: bool):
        if pc in self._watch_pcs:
            self.hit_from.append(self._last)
        self._last = (pc, insn)
        return super().record(t, pc, insn, exc, ecause, interrupt)


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


@pyuvm.test()
class sep_rom_oca_library_callback_test(_Base):
    required_evidence = (
        "CHK-TABLE-WIRED",
        "CHK-LIBRARY-ENTERED",
        "CHK-CALLBACKS-FROM-LIBRARY",
        "CHK-ROM-PATH",
        "CHK-OTBN-EDN",
    )

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        lay = _rom_layout(Path(cocotb.plusargs[_VMEM_ARG]))
        entries = _MANIFEST_ENTRIES + _PAYLOAD_ENTRIES + ("rom_main",)
        watch = {lay.syms[n] for n in entries if n in lay.syms} | {
            a for a in lay.slots.values() if a
        }
        obs = _CallObserver(self, frozenset(watch), keep=lambda _insn: False, tracker=False).start()
        try:
            await super().run_scenario()
        finally:
            await obs.stop()
            self._grade(obs, lay)
        self.chk.finish()

    def _manifest_fields(self) -> dict[str, int]:
        with open(self.flash_image, "rb") as fh:
            fh.seek(PRIMARY_MANIFEST_OFFSET)
            body = fh.read(4096)
        return {
            "magic_ok": int(body[:4] == b"OCAC"),
            "selector_bits": int.from_bytes(
                body[_OFF_SELECTOR : _OFF_SELECTOR + _LEN_SELECTOR], "little"
            ),
            "secure_boot_enforced": body[_OFF_SB_CONTROL] & 1,
            "payload_encrypted": body[_OFF_PAYLOAD_ENC] & 1,
        }

    def _grade(self, obs: _CallObserver, lay: _RomLayout) -> None:
        chk = self.chk
        hits = [(t, pc, frm) for (t, pc), frm in zip(obs.pc_hits, obs.hit_from)]
        role_of = {a: r for r, a in lay.slots.items() if a}
        man_entry = {lay.syms[n]: n for n in _MANIFEST_ENTRIES if n in lay.syms}
        pay_entry = {lay.syms[n]: n for n in _PAYLOAD_ENTRIES if n in lay.syms}

        chk.ctrl(
            "ROM-LAYOUT",
            bool(lay.lib)
            and lay.table is not None
            and all(r in lay.slots for r in _ROLES)
            and bool(man_entry)
            and all(lay.in_lib(a) for a in man_entry),
            lib=[f"0x{lo:08x}..0x{hi:08x}" for lo, hi in lay.lib[:1] + lay.lib[-1:]],
            lib_ranges=len(lay.lib),
            table=f"0x{lay.table:08x}" if lay.table is not None else "none",
            entries=sorted(man_entry.values()),
        )
        fields = self._manifest_fields()
        chk.ctrl(
            "MANIFEST-FIELDS",
            fields["magic_ok"] == 1
            and fields["selector_bits"] == 0
            and fields["secure_boot_enforced"] == 1
            and fields["payload_encrypted"] == 0,
            **fields,
        )

        rom_main = lay.syms.get("rom_main")
        main_t = [t for t, pc, _ in hits if pc == rom_main]
        entry_t = [t for t, pc, _ in hits if pc in man_entry]
        chk.ctrl(
            "PC-HITS-LIVE",
            bool(main_t) and bool(entry_t) and main_t[0] < entry_t[0],
            rom_main_hits=len(main_t),
            rom_main_ps=_ps(main_t[0] if main_t else None),
            first_entry_ps=_ps(entry_t[0] if entry_t else None),
            hits=len(hits),
        )
        # A function is entered by a jump; anything else means the predecessor is not the caller.
        not_jump = [
            (pc, frm)
            for _, pc, frm in hits
            if frm is None or opcode(frm[1]) not in (OP_JAL, OP_JALR)
        ]
        chk.ctrl(
            "CALLER-LIVE",
            bool(hits) and not not_jump,
            hits=len(hits),
            not_jump=len(not_jump),
            first_bad=lay.name_at(not_jump[0][0]) if not_jump else "none",
        )

        wired = {}
        for role in _ROLES:
            addr = lay.slots.get(role, 0)
            ok = bool(addr) and addr in lay.syms.values() and not lay.in_lib(addr)
            ok = ok and ROM_BASE <= addr < ROM_BASE + _ROM_SIZE
            wired[role] = (ok, addr)
        chk.ok(
            "TABLE-WIRED",
            all(ok for ok, _ in wired.values()),
            **{r: f"{lay.name_at(a)}@0x{a:08x}" for r, (_, a) in wired.items()},
            unwired=[r for r, (ok, _) in wired.items() if not ok],
        )

        t_verdict = obs.status_t(_MANIFEST_VALIDATED)
        before = [(t, pc) for t, pc, _ in hits if pc in man_entry and t_verdict and t < t_verdict]
        t_entry = before[-1][0] if before else None
        chk.ok(
            "LIBRARY-ENTERED",
            t_entry is not None,
            entry=man_entry[before[-1][1]] if before else "none",
            entry_ps=_ps(t_entry),
            entries_before_verdict=len(before),
            manifest_validated_ps=_ps(t_verdict),
        )

        from_lib = {r: 0 for r in _REQUIRED}
        for t, pc, frm in hits:
            role = role_of.get(pc)
            if (
                role in from_lib
                and t_entry is not None
                and t_entry < t < t_verdict
                and frm is not None
                and lay.in_lib(frm[0])
            ):
                from_lib[role] += 1
        chk.ok(
            "CALLBACKS-FROM-LIBRARY",
            t_entry is not None and all(from_lib.values()),
            **from_lib,
            span_ps=f"{_ps(t_entry)}..{_ps(t_verdict)}",
        )

        for role, addr in sorted(lay.slots.items()):
            if not addr:
                continue
            mine = [(t, frm) for t, pc, frm in hits if pc == addr]
            callers = sorted({lay.name_at(frm[0]) for _, frm in mine if frm is not None})
            chk.obs(
                "ROLE-HITS",
                role=role,
                fn=lay.name_at(addr),
                hits=len(mine),
                lib_caller=sum(1 for _, frm in mine if frm is not None and lay.in_lib(frm[0])),
                callers=callers[:6],
            )
        t_payload = obs.status_t(_PAYLOAD_VALIDATED)
        pay_t = [t for t, pc, _ in hits if pc in pay_entry]
        sha = lay.slots.get("sha256")
        chk.obs(
            "PAYLOAD-STAGE",
            entries=sorted(pay_entry.values()),
            entry_ps=_ps(pay_t[-1] if pay_t else None),
            payload_validated_ps=_ps(t_payload),
            sha256_from_lib=sum(
                1
                for t, pc, frm in hits
                if pc == sha
                and t_verdict is not None
                and t_payload is not None
                and t_verdict < t < t_payload
                and frm is not None
                and lay.in_lib(frm[0])
            ),
        )
        chk.obs(
            "CONSOLE-ORDER",
            manifest_ok_ps=_ps(obs.line_t("MANIFEST_OK")),
            payload_ok_ps=_ps(obs.line_t("PAYLOAD_OK")),
            commit_linked=int("oca_commit_security_state" in lay.syms),
        )
