# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An authorized key whose public exponent is not 65537 is refused; the backup boots.

rom.adoc, Secure Boot, Signature Verification:

    [SEP-ROM-SB-100] The public exponent shall be e = 65537 (F4). SEP secure boot accepts F4 RSA
    keys only, and a public key carrying any other exponent shall be rejected. This is a permanent
    property of the design rather than a consequence of how the OTBN program happens to be built,
    and signing infrastructure shall not issue SEP secure-boot keys with any other exponent.

    Consistent with that, the exponent is *not* taken from the manifest: the OTBN program is the
    F4 variant, built for e = 65537 and never reading the value the manifest carries. Rejecting a
    mismatching exponent is therefore the only sound response -- the alternative is to verify
    against an exponent the verifier will not use.

The primary manifest keeps the ROM key 0 modulus and selector and carries exponent 5 in the raw
key. The raw layout (big-endian modulus, then a 4-byte big-endian exponent) comes from the OCA
implementation, not from rom.adoc. The ROM key digests are SHA-256 over the public modulus only
(rom.adoc, Root Key Model, tbl:key_slots; memory-security.adoc, Manifest authentication: "binds
the manifest RSA modulus to the selected digest"), so the key stays authorized. SB-050 says
"presented public key".
Exponent 3 is not usable: it shares a factor with lambda(n) of ROM key 0, so no exponent-3
private exponent exists for key 0.
The plusarg ``+sep_rsa_signed_exponent`` selects the exponent the signature is made for:

* 5 (default, entry ``sep_rom_rsa_exponent_non_f4_refuse_test``): valid under the presented key
  (n, 5). A ROM that verified under the key's own exponent would accept it.
* 65537 (entry ``sep_rom_rsa_exponent_non_f4_refuse_test_f4_signed``): valid under (n, 65537),
  which is what the F4 OTBN program computes. A ROM that ignored the exponent would accept it.

* CHK-NON-F4-REFUSED: the primary attempt ends with a ``MANIFEST_ERR=`` code and the ROM then
  tries the backup. The spec names no code, so any code passes.
* CTRL-STIMULUS: offline, the primary carries exponent 5 inside ``public_key_size``, the modulus
  hashes to the selected ROM slot digest, the manifest revocation bitmap is clear, the manifest
  hash is intact, and the signature verifies under the intended exponent and not the other.
* CTRL-EFUSE: ``BL1_VERSION`` and ``CHIPLET_PUBK_REVOKE`` are 0, so rollback and revocation
  cannot refuse the primary.
* CTRL-PRIMARY-SERVED: the flash device served the mutated exponent and signature to the ROM.
* CTRL-PRIMARY-KEY-AUTHORIZED: the primary attempt prints ``PUBK_AUTHORIZED``, no ``PUBK_*``
  refusal, and no key-unauthorized or key-revoked code.
* CTRL-NO-OTHER-CAUSE: the primary code is not ``OCA_FAIL_SECURITY_VERSION`` and the primary
  attempt has no ``RSA_EXEC_FAIL`` engine fault.
* CTRL-BACKUP-BOOTED: the backup attempt is accepted after a verified signature and BL1 reports
  PASS; a refused slot fails the slot, not the boot (SEP-ROM-RETRY-030).
* CTRL-FAILOVER-ADDR: the device served the primary manifest, then the backup manifest, then the
  backup payload.

Partial coverage. Not graded: when the refusal happens relative to the modular exponentiation
(the spec does not say), logged as OBS-PRIMARY-RSA; the shall on signing infrastructure; the
refusal code; exponents other than 5. For the first entry a ROM that ignores the exponent also refuses the primary,
because the F4 modexp of an exponent-5 signature fails PKCS#1; only the second entry fails
on that defect.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cocotb
import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base as _Base

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_F4 = 65537
_NON_F4 = 5
_EXPONENT_LEN = 4
_RAW_KEY_LEN = mm.MODULUS_LEN + _EXPONENT_LEN
_OFF_EXPONENT = mm.OFF_PUBLIC_KEY + mm.MODULUS_LEN
_OFF_REVOKE = mm.K.OFF_PUBLIC_KEY_CLASSIC_REVOKE
_SIG_LEN = pm.RSA_KEY_BYTES

_KEY_OK = "PUBK_AUTHORIZED"
_KEY_REFUSALS = (
    "PUBK_ALGO_UNSUPPORTED",
    "PUBK_ENCODING_UNSUPPORTED",
    "PUBK_FIELD_TOO_SMALL",
    "PUBK_NO_SIGNATURE",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_SEL_EMPTY",
    "PUBK_SLOT_RESERVED",
    "PUBK_SLOT_PQC_UNSUPPORTED",
    "PUBK_SLOT_UNPROVISIONED",
    "PUBK_OTP_EMPTY",
    "PUBK_UNAUTHORIZED",
    "PUBK_HASH_TIMEOUT",
)
_KEY_CODES = (
    mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED"),
    mm.boot_err("OCA_FAIL_ROOT_KEY_REVOKED"),
)
_ROLLBACK_CODE = mm.boot_err("OCA_FAIL_SECURITY_VERSION")
_BACKUP_ORDER = (_KEY_OK, "RSA_EXEC", "RSA_VERIFY_OK", "MANIFEST_OK", "PAYLOAD_OK")


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _served(rds: list, addr: int, n: int) -> bytes | None:
    """The bytes the flash device returned for [addr, addr + n), from the first read of each."""
    out = bytearray()
    for a in range(addr, addr + n):
        hit = ev.covering_read(rds, a)
        if hit is None:
            return None
        out += ev.bytes_at(hit[1], a, 1)
    return bytes(out)


def _index(rds: list, addr: int) -> int:
    hit = ev.covering_read(rds, addr)
    return -1 if hit is None else hit[0]


@pyuvm.test()
class sep_rom_rsa_exponent_non_f4_refuse_test(_Base):
    """Primary key carries e=5 and a signature for the selected exponent; the backup boots."""

    required_evidence = ("CHK-NON-F4-REFUSED", "CHK-ROM-PATH")
    efuse_preload = _EFUSE_PRELOAD

    @staticmethod
    def _check_contract(obj) -> None:
        # The spec names no refusal code or marker, so check_transport grades any refusal.
        _Base._check_contract(obj if isinstance(obj, type) else type(obj))

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self._loaded = None
        self._primary_sig = None
        arg = cocotb.plusargs.get("sep_rsa_signed_exponent", str(_NON_F4))
        self.signed_exponent = int(arg, 0)
        assert self.signed_exponent in (_NON_F4, _F4), (
            f"+sep_rsa_signed_exponent={arg} is not {_NON_F4} or {_F4}; set one of them"
        )
        await super().run_scenario()
        self.chk.finish()

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        self.chk.ctrl(
            "EFUSE",
            bl1_ver == 0 and revoke == 0,
            bl1_version=f"0x{bl1_ver:x}",
            pubk_revoke=f"0x{revoke:x}",
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        slot = "primary"
        base = mm.slot_base(slot)
        pm.verify_sealed(buf, slot)
        key_slot = pm.verify_signing_key(buf, slot)
        n, e, d = pm.load_rsa_private_key(pm.rom_signing_key(key_slot))
        assert e == _F4, (
            f"rom_key{key_slot}.pem has e={e}, not 65537: the F4-signed entry signs with its d "
            f"directly; use an F4 signing key"
        )
        # e*d - 1 is a multiple of lambda(n), so an inverse modulo it is a private exponent.
        sign_d = d if self.signed_exponent == _F4 else pow(self.signed_exponent, -1, e * d - 1)
        buf[base + _OFF_EXPONENT : base + _OFF_EXPONENT + _EXPONENT_LEN] = _NON_F4.to_bytes(
            _EXPONENT_LEN, "big"
        )
        mm.rehash(buf, slot)
        signed = bytes(buf[base : base + mm.SIGNED_REGION_END])
        sig = pm.sign_pkcs1v15_sha256(signed, n, sign_d)
        buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + _SIG_LEN] = sig
        mm.verify_layout(buf, slot)

        other = _F4 if self.signed_exponent == _NON_F4 else _NON_F4
        key_size = int.from_bytes(
            buf[base + mm.OFF_PUBLIC_KEY_SIZE : base + mm.OFF_PUBLIC_KEY_SIZE + 2], "little"
        )
        exponent = int.from_bytes(buf[base + _OFF_EXPONENT : base + _OFF_EXPONENT + 4], "big")
        revoke = int.from_bytes(buf[base + _OFF_REVOKE : base + _OFF_REVOKE + 16], "little")
        digest_ok = hashlib.sha256(mm.public_key_modulus(buf, slot)).digest() == mm.rom_key_digest(
            key_slot
        )
        valid = pm.verify_pkcs1v15_sha256(signed, sig, n, self.signed_exponent)
        valid_other = pm.verify_pkcs1v15_sha256(signed, sig, n, other)
        self._primary_sig = sig
        self.chk.ctrl(
            "STIMULUS",
            exponent == _NON_F4
            and key_size >= _RAW_KEY_LEN
            and mm.public_key_encoding(buf, slot) == mm.ENCODING_RAW
            and mm.get_public_key_sel(buf, slot) == key_slot
            and digest_ok
            and not revoke >> key_slot & 1
            and valid
            and not valid_other,
            key_slot=key_slot,
            exponent=exponent,
            key_size=key_size,
            modulus_digest_matches_slot=digest_ok,
            manifest_revoke=f"0x{revoke:032x}",
            signed_exponent=self.signed_exponent,
            valid_under_signed_exponent=valid,
            valid_under_other_exponent=valid_other,
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        buf = super().mutate_flash_image(buf)
        self._loaded = bytes(buf)
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        chk = self.chk
        attempts = oc.split_attempts(console)
        srcs = [a.src for a in attempts]
        primary = next((a for a in attempts if a.src == mm.PRIMARY_MANIFEST_OFFSET), None)
        backup = next((a for a in attempts if a.src == mm.BACKUP_MANIFEST_OFFSET), None)
        p_lines = [line for _, line in primary.markers] if primary else []
        b_lines = [line for _, line in backup.markers] if backup else []
        p_err = primary.error if primary else None

        chk.ok(
            "NON-F4-REFUSED",
            srcs == [mm.PRIMARY_MANIFEST_OFFSET, mm.BACKUP_MANIFEST_OFFSET] and p_err is not None,
            attempts=[_hex(s) for s in srcs],
            primary_error=_hex(p_err),
            primary_stage=primary.stage if primary else "none",
        )

        rds = ev.reads(flash.get_transactions())
        p_base = mm.PRIMARY_MANIFEST_OFFSET
        exp = _served(rds, p_base + _OFF_EXPONENT, _EXPONENT_LEN)
        sig = _served(rds, p_base + mm.OFF_SIGNATURE, _SIG_LEN)
        chk.ctrl(
            "PRIMARY-SERVED",
            exp == _NON_F4.to_bytes(_EXPONENT_LEN, "big") and sig == self._primary_sig,
            served_exponent="none" if exp is None else exp.hex(),
            served_signature_matches=sig == self._primary_sig,
        )

        refusals = [m for m in _KEY_REFUSALS if oc.count(p_lines, m)]
        chk.ctrl(
            "PRIMARY-KEY-AUTHORIZED",
            oc.count(p_lines, _KEY_OK) == 1 and not refusals and p_err not in _KEY_CODES,
            authorized=oc.count(p_lines, _KEY_OK),
            refusals=refusals or "none",
            primary_error=_hex(p_err),
        )
        chk.ctrl(
            "NO-OTHER-CAUSE",
            primary is not None
            and p_err != _ROLLBACK_CODE
            and not oc.count(p_lines, "RSA_EXEC_FAIL"),
            primary_error=_hex(p_err),
            rsa_exec_fail=oc.count(p_lines, "RSA_EXEC_FAIL"),
        )

        backup_err = "none"
        if backup is None:
            backup_err = "no backup attempt"
        else:
            try:
                oc.assert_attempt(backup, error=None, stage="accepted", ordered=_BACKUP_ORDER)
            except AssertionError as exc:
                backup_err = str(exc)
        chk.ctrl(
            "BACKUP-BOOTED",
            backup_err == "none" and bool(self.sb.fw_done and self.sb.fw_pass),
            backup_markers=b_lines,
            attempt_error=backup_err,
            fw_done=bool(self.sb.fw_done),
            fw_pass=bool(self.sb.fw_pass),
        )

        loaded = self._loaded
        b_payload = pm.payload_base(loaded, "backup") if loaded is not None else -1
        p_payload = pm.payload_base(loaded, "primary") if loaded is not None else -1
        i_pm = _index(rds, mm.PRIMARY_MANIFEST_OFFSET)
        i_bm = _index(rds, mm.BACKUP_MANIFEST_OFFSET)
        i_bp = _index(rds, b_payload) if b_payload >= 0 else -1
        chk.ctrl(
            "FAILOVER-ADDR",
            0 <= i_pm < i_bm < i_bp,
            primary_manifest_read=i_pm,
            backup_manifest_read=i_bm,
            backup_payload_read=i_bp,
            backup_payload=f"0x{b_payload:x}",
            reads=len(rds),
        )

        chk.obs(
            "PRIMARY-RSA",
            rsa_exec=oc.count(p_lines, "RSA_EXEC"),
            rsa_verify_ok=oc.count(p_lines, "RSA_VERIFY_OK"),
            rsa_pkcs1_fail=oc.count(p_lines, "RSA_PKCS1_FAIL"),
            primary_payload_read=_index(rds, p_payload) if p_payload >= 0 else -1,
            primary_markers=p_lines,
        )
