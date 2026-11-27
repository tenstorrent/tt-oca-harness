# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet secure boot in PROD and PROD_END: one seeded lifecycle x image cell per run.

Each seed draws the lifecycle (``prod``, ``prod_end``) and the image scenario (``signed``,
``unsigned``, ``corrupt_signature``) independently. The testcase writes one image into SMC SRAM at
the default published offset 0x1000 and grades the drawn cell. The image is the ROM-key-0 signed
SPI image ``oca_secure_boot.bin``, whose manifest at 0x1000 and payload at 0x2000 are the layout
the secondary arm reads from SMC SRAM.

* ``signed``: the shipped image. The validator runs the hash, secure-boot decision, identity,
  lifecycle, version-range and demotion checks before key authorization, so ``PUBK_SEL=`` places
  the run past them. ``FUSE_VER=`` is the security-version check and ``RSA_VERIFY_OK`` the
  signature; ``MANIFEST_OK``, ``PAYLOAD_OK`` and the BL1 handoff follow.
* ``unsigned``: the packer's ``secure_boot: 0`` form of the same manifest. PROD and PROD_END
  enforce secure boot with no signature class named, so the slot fails with
  ``OCA_FAIL_SIGNATURE_CLASS_CONTROL`` before key selection.
  ``sep_firmware_secondary_chiplet_bootcode_test`` boots the packer's unsigned image in TEST_DEV.
* ``corrupt_signature``: one seeded bit of the signature flipped, with the signature integer kept
  below the modulus. The verifier runs and rejects it with ``RSA_PKCS1_FAIL`` and
  ``OCA_FAIL_SIGNATURE``.

The signed manifest sets its own secure-boot request, so only the unsigned cell attributes
enforcement to the lifecycle. Terminal halt is graded on cold_scratch[1] and a silent console after
the verdict, not on the CPU PC. One seed proves one cell; closure is the union of the per-seed
artifacts (``env/sep_rom_functional_coverage.py merge``). Needs ``+esrc_noise_force``: OTBN waits
for EDN entropy before the RSA-3072 modexp.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env.sep_efuse_image import LC_PROD, LC_PROD_END, SepEfuseImage
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_functional_coverage import write_feature_cell
from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    MANIFEST_BACKUP,
    MANIFEST_MAGIC,
    RECOVERY_MARKER,
    SECONDARY_MARKER,
    SMC_SRAM_BASE,
    SPI_INIT_MARKERS,
    SPI_MARKER,
    sep_secondary_chiplet_base,
)

FEATURE_KEY = "SEP-ROM-SECONDARY-SECURE"
LIFECYCLES = ("prod", "prod_end")
SCENARIOS = ("signed", "unsigned", "corrupt_signature")
REQUIRED_CELLS = tuple(f"lc={lc},image={image}" for lc in LIFECYCLES for image in SCENARIOS)

# Raw LC_STATE code and the line lifecycle.c prints for it.
_LC = {"prod": (LC_PROD, "LC=PROD"), "prod_end": (LC_PROD_END, "LC=PROD_END")}
_SLOT = "primary"
_KEY_SLOT = 0

_ERR_CLASS_CONTROL = mm.boot_err("OCA_FAIL_SIGNATURE_CLASS_CONTROL")
_ERR_SIGNATURE = mm.boot_err("OCA_FAIL_SIGNATURE")
# rom_manifest_boot() reports this after the refused slot's own ERROR status.
_ERROR_LOAD_FAILED = mm.rom_status_word("ERROR", "SEP_MSG_MANIFEST_LOAD_FAILED")

_SEL_ECHO = f"PUBK_SEL=0x{_KEY_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"
_SBOOT_DIS_CLEAR = "FUSE: SBOOT_DIS: 0"
# Every refusal plat_is_key_authorized() prints; any one ends the slot before the verifier.
_KEY_REFUSALS = (
    "PUBK_NO_SIGNATURE",
    "PUBK_ALGO_UNSUPPORTED",
    "PUBK_ENCODING_UNSUPPORTED",
    "PUBK_FIELD_TOO_SMALL",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_SEL_EMPTY",
    "PUBK_SLOT_RESERVED",
    "PUBK_SLOT_PQC_UNSUPPORTED",
    "PUBK_SLOT_UNPROVISIONED",
    "PUBK_OTP_EMPTY",
    "PUBK_UNAUTHORIZED",
    "PUBK_HASH_TIMEOUT",
)
# OTBN engine faults: the signature was never judged.
_RSA_FAULTS = ("RSA_OTBN_INIT_FAIL", "RSA_OTBN_LOAD_FAIL", "RSA_EXEC_FAIL", "RSA_INOUT_UNCHANGED")
_KEY_CHAIN = ("OCA_BODY=", "MFST_VER=", _SEL_ECHO, "PUBK_AUTHORIZED", _REVOKE_ECHO, "FUSE_VER=")
_VERIFIER = ("RSA_EXEC", "RSA_CMP1", "RSA_CMP2")
_HANDOFF = ("BL1_COPIED", "BL1_JUMP=", "PRE_JUMP")
# Printed by BL1 after the handoff and by nothing in the ROM.
_BL1_MARKER = "FUSE_CHK"
_BOOT_PROGRESS = ("MANIFEST_OK", "PAYLOAD_OK", "FUSE_SECRETS_LOCKED") + _HANDOFF + (_BL1_MARKER,)
_SPI_PATH = (
    SPI_MARKER,
    RECOVERY_MARKER,
    MANIFEST_BACKUP,
    "SPI_ROTATE=",
    "SPI init failed, using backup manifest",
) + SPI_INIT_MARKERS


@dataclass(frozen=True)
class _Outcome:
    boots: bool
    error: int
    # Markers of the single attempt, in order, and markers it must not print.
    ordered: tuple[str, ...]
    absent: tuple[str, ...]
    check_id: str


_OUTCOMES = {
    "signed": _Outcome(
        True,
        0,
        _KEY_CHAIN
        + _VERIFIER
        + ("RSA_VERIFY_OK", "MANIFEST_OK", "PAYLOAD_OK")
        + _HANDOFF
        + (_BL1_MARKER,),
        ("MANIFEST_ERR=", "RSA_PKCS1_FAIL", "SBOOT_OFF") + _RSA_FAULTS + _KEY_REFUSALS,
        "CHK-SECONDARY-SECURE-SIGNED",
    ),
    "unsigned": _Outcome(
        False,
        _ERR_CLASS_CONTROL,
        ("OCA_BODY=", "MFST_VER=", f"MANIFEST_ERR=0x{_ERR_CLASS_CONTROL:08x}"),
        ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "RSA_EXEC", "RSA_VERIFY_OK")
        + _BOOT_PROGRESS,
        "CHK-SECONDARY-SECURE-UNSIGNED",
    ),
    "corrupt_signature": _Outcome(
        False,
        _ERR_SIGNATURE,
        _KEY_CHAIN + _VERIFIER + ("RSA_PKCS1_FAIL", f"MANIFEST_ERR=0x{_ERR_SIGNATURE:08x}"),
        ("RSA_VERIFY_OK",) + _RSA_FAULTS + _KEY_REFUSALS + _BOOT_PROGRESS,
        "CHK-SECONDARY-SECURE-CORRUPT-SIGNATURE",
    ),
}

oc.assert_known(
    tuple(m for o in _OUTCOMES.values() for m in o.ordered + o.absent)
    + tuple(echo for _raw, echo in _LC.values())
    + _SPI_PATH
    + (ALL_FAILED, "MANIFEST_BOOT_FAIL="),
    __name__,
)


def _public_key(buf: bytes) -> tuple[int, int]:
    # A raw RSA-3072 key field is the big-endian modulus then a 4-byte big-endian exponent.
    base = mm.slot_base(_SLOT) + mm.OFF_PUBLIC_KEY
    exp = bytes(buf[base + mm.MODULUS_LEN : base + mm.MODULUS_LEN + 4])
    return int.from_bytes(mm.public_key_modulus(buf, _SLOT), "big"), int.from_bytes(exp, "big")


def _signature_valid(buf: bytes) -> bool:
    base = mm.slot_base(_SLOT)
    n, e = _public_key(buf)
    sig = buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + mm.signature_size(buf, _SLOT)]
    return pm.verify_pkcs1v15_sha256(bytes(buf[base : base + mm.SIGNED_REGION_END]), sig, n, e)


@pyuvm.test()
class sep_secondary_secure_boot_rand_test(sep_secondary_chiplet_base):
    """Seeded {PROD, PROD_END} x {signed, unsigned, corrupt_signature} on the SMC-SRAM source."""

    extra_required = (_SBOOT_DIS_CLEAR,)
    extra_forbidden = ("FUSE: SBOOT_DIS: 1", "SBOOT_OFF", "SPI_ROTATE=")

    # --- stimulus ----------------------------------------------------------
    def _draw(self) -> None:
        self._seed = self.random_seed()
        rng = random.Random(f"sep-secondary-secure-{self._seed}")
        self.lifecycle = rng.choice(LIFECYCLES)
        self.image_scenario = rng.choice(SCENARIOS)
        self.cell = f"lc={self.lifecycle},image={self.image_scenario}"
        self.sig_byte = self.sig_bit = None
        if self.image_scenario == "corrupt_signature":
            self.sig_byte, self.sig_bit = self._draw_signature_flip(rng)

    def _draw_signature_flip(self, rng: random.Random) -> tuple[int, int]:
        buf = mm.rom_key_image(_KEY_SLOT).read_bytes()
        base = mm.slot_base(_SLOT) + mm.OFF_SIGNATURE
        size = mm.signature_size(buf, _SLOT)
        n, _e = _public_key(buf)
        sig = int.from_bytes(buf[base : base + size], "big")
        # A representative at or above the modulus is out of RSAVP1 range, not a wrong signature.
        while True:
            byte, bit = rng.randrange(size), rng.randrange(8)
            if sig ^ (1 << (8 * (size - 1 - byte) + bit)) < n:
                return byte, bit

    def _build_image(self) -> bytearray:
        self.log_image_identity("key_slot_image", str(mm.rom_key_image(_KEY_SLOT)))
        self.log_image_identity("unsigned_ref", str(mm.BUILD_DIR / "oca_non_secure_boot.bin"))
        buf = bytearray(mm.rom_key_image(_KEY_SLOT).read_bytes())
        base = mm.slot_base(_SLOT)
        mm.verify_layout(buf, _SLOT)
        assert mm.can_anchor_public_key(buf, _SLOT), (
            f"{mm.describe(buf, _SLOT)} carries no ROM-anchored RSA-3072 raw key, so the signed "
            f"cell would not be verified against a trust anchor in this tree"
        )
        assert mm.verify_public_key(buf, _SLOT) == _KEY_SLOT, (
            f"the signed image selects a key other than ROM slot {_KEY_SLOT}; regenerate it "
            f"with `make oca-images`"
        )
        assert _signature_valid(buf), (
            "the shipped primary signature does not verify against its own anchored key, so no "
            "outcome of this run is attributable to the drawn scenario"
        )
        self.payload_offset = pm.payload_base(buf, _SLOT)
        assert base < self.payload_offset < mm.BACKUP_MANIFEST_OFFSET <= len(buf), (
            f"payload at 0x{self.payload_offset:x} is not inside the primary slot before the "
            f"backup manifest at 0x{mm.BACKUP_MANIFEST_OFFSET:x}; the layout no longer matches "
            f"the SMC SRAM image the secondary arm reads"
        )

        if self.image_scenario == "unsigned":
            mm.clear_secure_boot(buf, _SLOT)
            mm.remove_signature(buf, _SLOT, keep_size=False)
            mm.remove_public_key(buf, _SLOT, keep_size=False)
            mm.verify_layout(buf, _SLOT)
            self._assert_packer_unsigned_form(buf)
        elif self.image_scenario == "corrupt_signature":
            mm.flip_signature_byte(buf, _SLOT, byte_index=self.sig_byte, xor_mask=1 << self.sig_bit)
            # The flip is outside the signed region, so the hash still matches and RSA runs.
            mm.verify_layout(buf, _SLOT)
            mm.verify_public_key(buf, _SLOT)
            assert not _signature_valid(buf), (
                f"flipping bit {self.sig_bit} of signature byte {self.sig_byte} left a valid "
                f"signature, so the rejection this cell grades cannot happen"
            )
        return buf

    def _assert_packer_unsigned_form(self, buf: bytes) -> None:
        # Byte-equal to the packer's unsigned manifest except its description and hash.
        ref = (mm.BUILD_DIR / "oca_non_secure_boot.bin").read_bytes()
        base = mm.slot_base(_SLOT)
        skip = (
            (mm.K.OFF_MANIFEST_DESCRIPTION, mm.K.MANIFEST_DESCRIPTION_SIZE),
            (mm.OFF_MANIFEST_HASH, mm.HASH_FIELD_SIZE),
        )
        diff = [
            off
            for off in range(mm.BODY_SIZE)
            if buf[base + off] != ref[base + off] and not any(lo <= off < lo + n for lo, n in skip)
        ]
        assert not diff and len(ref) == len(buf), (
            f"the unsigned manifest differs from the packer's secure_boot: 0 manifest at body "
            f"offsets {diff[:16]}; it would be refused for a malformed field, not for lacking a "
            f"signature"
        )
        assert (
            buf[self.payload_offset : mm.BACKUP_MANIFEST_OFFSET]
            == ref[self.payload_offset : mm.BACKUP_MANIFEST_OFFSET]
        ), "the unsigned image's payload is not the packer's unsigned payload"

    def build_efuse_image(self):
        raw, _echo = _LC[self.lifecycle]
        image = SepEfuseImage().set_lc_state(raw)
        # Each would decide the slot before the lifecycle or the signature does.
        for field in ("SBOOT_DIS", "CHIPLET_PUBK_REVOKE", "BL1_VERSION", "SIP_DIS", "SYS_DIS"):
            assert image.field_int(field) == 0, f"eFuse {field} is not clean in the {self.cell} run"
        assert image.lc_raw() == raw, f"eFuse LC_STATE raw is 0x{image.lc_raw():x}, not 0x{raw:x}"
        return image

    def prepare_smc_mem(self) -> None:
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "the rom_boot target did not bind its SMC responder"
        smc_mem.write(SMC_SRAM_BASE, bytes(self._image))

    def check_smc_image(self) -> None:
        assert "sep_smc_mem_hex" not in cocotb.plusargs, (
            "+sep_smc_mem_hex preloads a second SMC image; remove it from the testlist entry, "
            "this testcase writes the only image the ROM may read"
        )
        got = bytearray(self.cfg.smc_mem.read(SMC_SRAM_BASE, len(self._image)))
        assert got == self._image, (
            f"SMC SRAM at 0x{SMC_SRAM_BASE:08x} does not hold the {len(self._image)}-byte image "
            f"this run built"
        )
        magic = bytes(got[self.manifest_offset : self.manifest_offset + 4])
        assert magic == MANIFEST_MAGIC, (
            f"SMC SRAM offset 0x{self.manifest_offset:x} holds {magic!r}, not {MANIFEST_MAGIC!r}"
        )
        assert mm.slot_base(_SLOT) == self.manifest_offset, (
            f"the image's primary manifest is at 0x{mm.slot_base(_SLOT):x}, not at the published "
            f"offset 0x{self.manifest_offset:x}"
        )
        self.logger.info(
            "CHK-SMC-IMAGE: 0x%x bytes at 0x%08x, published manifest %s, payload at 0x%08x, "
            "secure_boot_control=0x%02x signature_type=%d",
            len(got),
            SMC_SRAM_BASE,
            mm.describe(got, _SLOT),
            SMC_SRAM_BASE + self.payload_offset,
            mm.secure_boot_control(got, _SLOT),
            mm.signature_type(got, _SLOT),
        )

    async def _watch_smc_image_reads(self) -> None:
        bus = cocotb.top.u_smc_axi_if
        lo, hi = SMC_SRAM_BASE, SMC_SRAM_BASE + len(self._image)
        while True:
            await RisingEdge(cocotb.top.clk_i)
            accepted = self.rd(bus.arvalid, allow_unknown=True) & self.rd(
                bus.arready, allow_unknown=True
            )
            if accepted:
                addr = self.rd(bus.araddr)
                if lo <= addr < hi:
                    nbytes = (self.rd(bus.arlen) + 1) << self.rd(bus.arsize)
                    self._image_reads.append((addr, nbytes))

    async def run_scenario(self) -> None:
        self._draw()
        self._image = self._build_image()
        self._outcome = outcome = _OUTCOMES[self.image_scenario]
        self.expect_boot = outcome.boots
        self.expected_error = outcome.error
        if outcome.boots:
            self.extra_required = (_SBOOT_DIS_CLEAR, "MANIFEST_OK", _BL1_MARKER)
            self.extra_forbidden += ("MANIFEST_ERR=", ALL_FAILED, "MANIFEST_BOOT_FAIL=")
        else:
            boot_fail = f"MANIFEST_BOOT_FAIL=0x{outcome.error:08x}"
            self.extra_required = (_SBOOT_DIS_CLEAR, ALL_FAILED, boot_fail)
            self.extra_forbidden += _BOOT_PROGRESS
        self.required_evidence = (
            "CHK-SECONDARY-SECURE-STIMULUS",
            "CHK-SECONDARY-SECURE-SOURCE",
            "CHK-SINGLE-ATTEMPT",
            "CHK-SECONDARY-NO-SPI",
            outcome.check_id,
        )
        self._measurements = None
        self._image_reads: list[tuple[int, int]] = []
        watcher = cocotb.start_soon(self._watch_smc_image_reads())
        # +esrc_noise_force only routes this port to the entropy source; without a driver the
        # repetition health test trips before key authorization can reach RSA.
        cocotb.start_soon(esrc_noise_task(cocotb.top, logger=self.logger))
        try:
            await super().run_scenario()
        finally:
            watcher.cancel()

    # --- checks ------------------------------------------------------------
    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        self._check_stimulus(console)
        attempt = self._check_source(console)
        self._check_no_spi(console)
        if self._outcome.boots:
            self._check_signed(console, attempt, fw_done, fw_pass)
        else:
            self._check_rejected(console, attempt, status_seq, fw_done, fw_pass)
        self._measurements = {
            "lifecycle": self.lifecycle,
            "lc_raw": _LC[self.lifecycle][0],
            "image_scenario": self.image_scenario,
            "signature_byte": self.sig_byte,
            "signature_bit": self.sig_bit,
            "manifest_src": f"0x{SMC_SRAM_BASE + self.manifest_offset:08x}",
            "smc_image_reads": len(self._image_reads),
            "expected_error": f"0x{self._outcome.error:08x}",
            "verdict_pass": bool(fw_pass),
            "final_status": f"0x{status_seq[-1]:08x}" if status_seq else None,
        }

    def _check_stimulus(self, console: list[str]) -> None:
        raw, echo = _LC[self.lifecycle]
        lc_lines = [line.strip() for line in console if line.strip().startswith("LC=")]
        assert lc_lines == [echo], (
            f"the ROM resolved the lifecycle as {lc_lines}, expected exactly [{echo!r}] for the "
            f"drawn {self.lifecycle}; the cell would be credited to a lifecycle that did not run. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-SECONDARY-SECURE-STIMULUS PASS: seed=%d cell=%s lifecycle=%s (LC raw 0x%x, ROM "
            "printed %s) image=%s signature_byte=%s signature_bit=%s",
            self._seed,
            self.cell,
            self.lifecycle,
            raw,
            echo,
            self.image_scenario,
            self.sig_byte,
            self.sig_bit,
        )

    def _check_source(self, console: list[str]):
        src = SMC_SRAM_BASE + self.manifest_offset
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [src], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected one at the published "
            f"SMC SRAM address 0x{src:08x}. Console: {console}"
        )
        reads = list(self._image_reads)

        def covering(addr: int) -> list[tuple[int, int]]:
            return [r for r in reads if r[0] <= addr < r[0] + r[1]]

        def overlapping(lo: int, hi: int) -> list[tuple[int, int]]:
            return [r for r in reads if r[0] < hi and r[0] + r[1] > lo]

        assert covering(src), (
            f"no SMC-port read covered the published manifest at 0x{src:08x}; reads into the "
            f"image: {[(hex(a), n) for a, n in reads]}"
        )
        payload = SMC_SRAM_BASE + self.payload_offset
        backup = SMC_SRAM_BASE + mm.BACKUP_MANIFEST_OFFSET
        end = SMC_SRAM_BASE + len(self._image)
        stray = overlapping(backup, end)
        assert not stray, (
            f"SMC-port reads {[(hex(a), n) for a, n in stray]} reached the signed backup slot at "
            f"0x{backup:08x}; the SMC path has one slot and must not read a second manifest"
        )
        if self._outcome.boots:
            assert covering(payload), (
                f"no SMC-port read covered the payload at 0x{payload:08x}, so BL1 did not come "
                f"from the published image"
            )
        else:
            early = overlapping(payload, backup)
            assert not early, (
                f"SMC-port reads {[(hex(a), n) for a, n in early]} reached the payload at "
                f"0x{payload:08x}; a manifest the ROM refuses must not have its payload read"
            )
        self.logger.info(
            "CHK-SECONDARY-SECURE-SOURCE PASS: one attempt at 0x%08x; %d SMC-port read(s) into the "
            "image, %d covering the manifest, payload 0x%08x %s, none in the backup slot from "
            "0x%08x",
            src,
            len(reads),
            len(covering(src)),
            payload,
            "read" if self._outcome.boots else "not read",
            backup,
        )
        return attempts[0]

    def _check_no_spi(self, console: list[str]) -> None:
        seen = {m: oc.count(console, m) for m in _SPI_PATH if oc.count(console, m)}
        assert not seen, (
            f"the secondary run printed SPI or backup markers {seen}. Console: {console}"
        )
        n_secondary = oc.count(console, SECONDARY_MARKER)
        assert n_secondary == 1, (
            f"{SECONDARY_MARKER} appeared {n_secondary} times, expected once. Console: {console}"
        )
        self.logger.info(
            "CHK-SECONDARY-NO-SPI PASS: %s once; none of %s; no SMC-port read in the backup slot",
            SECONDARY_MARKER,
            ", ".join(_SPI_PATH),
        )

    def _check_signed(self, console, attempt, fw_done, fw_pass) -> None:
        o = self._outcome
        oc.assert_attempt(attempt, error=None, stage="accepted", ordered=o.ordered, absent=o.absent)
        for marker in (_SEL_ECHO, "RSA_EXEC", "RSA_VERIFY_OK"):
            n = oc.count(console, marker)
            assert n == 1, f"{marker} appeared {n} times, expected once. Console: {console}"
        assert fw_done and fw_pass, (
            f"the signed image passed every ROM check but BL1 did not report PASS on "
            f"cold_scratch[0] (done={fw_done}, pass={fw_pass})"
        )
        self.logger.info(
            "CHK-SECONDARY-SECURE-SIGNED PASS: %s; %s; verdict PASS",
            self.cell,
            " -> ".join(o.ordered),
        )

    def _check_rejected(self, console, attempt, status_seq, fw_done, fw_pass) -> None:
        o = self._outcome
        status_hex = [hex(v) for v in status_seq]
        oc.assert_attempt(
            attempt, error=o.error, stage="manifest", ordered=o.ordered, absent=o.absent
        )
        n_err = oc.count(console, "MANIFEST_ERR=")
        assert n_err == 1, (
            f"MANIFEST_ERR= appeared {n_err} times, expected once. Console: {console}"
        )
        if self.image_scenario == "corrupt_signature":
            n_rsa = oc.count(console, "RSA_EXEC")
            assert n_rsa == 1, f"RSA_EXEC appeared {n_rsa} times, expected once. Console: {console}"
        boot_fail = f"MANIFEST_BOOT_FAIL=0x{o.error:08x}"
        i_err, i_all, i_fail = (
            self._index_of(console, m) for m in (o.ordered[-1], ALL_FAILED, boot_fail)
        )
        assert 0 <= i_err < i_all < i_fail, (
            f"rejection out of order: {o.ordered[-1]}@{i_err} -> {ALL_FAILED}@{i_all} -> "
            f"{boot_fail}@{i_fail}. Console: {console}"
        )
        specific = mm.rom_status_word("ERROR", mm.rom_status_name_for_result(o.error))
        # Not the last word: an unusable status ring makes the ROM write a ring error after each.
        i_specific = status_seq.index(specific) if specific in status_seq else -1
        i_load = max((i for i, v in enumerate(status_seq) if v == _ERROR_LOAD_FAILED), default=-1)
        assert 0 <= i_specific < i_load, (
            f"cold_scratch[1] must hold 0x{specific:08x} ({mm.rom_status_name_for_result(o.error)})"
            f" and then 0x{_ERROR_LOAD_FAILED:08x}; observed {status_hex}"
        )
        assert fw_done and not fw_pass, (
            f"the ROM did not converge on a FAIL verdict for the {self.image_scenario} image "
            f"(done={fw_done}, pass={fw_pass}); cold_scratch[1]: {status_hex}"
        )
        self.logger.info(
            "%s PASS: %s; %s@%d -> %s@%d -> %s@%d; cold_scratch[1] 0x%08x then 0x%08x; "
            "verdict FAIL",
            o.check_id,
            self.cell,
            o.ordered[-1],
            i_err,
            ALL_FAILED,
            i_all,
            boot_fail,
            i_fail,
            specific,
            _ERROR_LOAD_FAILED,
        )

    def report_phase(self) -> None:
        super().report_phase()
        # Runs only after every check, the quiesce check and the evidence gate passed.
        if not getattr(self, "_evidence_passed", False) or self._measurements is None:
            return
        path = write_feature_cell(
            FEATURE_KEY, REQUIRED_CELLS, self.cell, self._measurements, seed=self._seed
        )
        self.logger.info("FCOV-CELL: %s %s -> %s", FEATURE_KEY, self.cell, path)
