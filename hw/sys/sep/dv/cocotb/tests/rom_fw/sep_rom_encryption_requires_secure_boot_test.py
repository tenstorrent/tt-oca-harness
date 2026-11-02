# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An encrypted payload on a boot without secure boot is refused, and nothing is decrypted.

rom.adoc, Payload Validation, Check Order:

    [SEP-ROM-PL-050] Payload encryption shall require secure boot: a manifest marking its
    payload encrypted while the secure-boot decision is *off* shall be rejected (the
    `secure-boot invariant` check).

rom.adoc, Security inventory, which names the check and its code:

    |Secure-boot invariant |encryption bit, SB decision |encrypted ⇒ SB active
    |`OCA_FAIL_SECURE_BOOT_INVARIANT` |Structural stage. PL-050

rom.adoc, Fatal ROM Error Codes and tbl:bl0_state, which say where the code is recorded:

    Fatal errors reported through `rom_err_fail()` are recorded in `bl0_state.error_code`.
    ... `0x0003xxxx` for the manifest module (<<tbl:oca_boot_err>>) -- and reach only
    `bl0_state.error_code`, since every such path has already reported its own status.

    The manifest module's codes are `OCA_BOOT_ERR_*` in `include/oca_boot.h`. `0x000300xx` carries
    a validation-library verdict (`oca_result_t`) in the low byte

    |`error_code` |u32 |0, or the fatal error recorded by `rom_err_fail()`.

status-errors.adoc: "Manifest failures use the `MANIFEST_ERR_*` namespace, formed as
`OCA_BOOT_ERR_BASE | oca_result_t` ... The enumeration is
`tools/tt-oca-manifest/validators/oca/lib/oca_validator.h`".

The spec disagrees with itself on the refusal code. PL-050 and the security inventory name
`OCA_FAIL_SECURE_BOOT_INVARIANT`. The MAN-030 flow lists ":secure-boot invariant;" and
":payload-encryption precondition;" as separate steps, and the payload pipeline figure rejects
with "(encryption requires secure boot)". The registry that status-errors.adoc designates,
`oca_validator.h`, defines `OCA_FAIL_SECURE_BOOT_INVARIANT` as "Signing fields left non-zero on a
manifest declaring secure_boot = 0" and gives the encrypted-without-secure-boot refusal its own
code, `OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT`. Both readings agree that the code is one of
these two, so the leaf grades that set and logs which one it saw.

rom.adoc, Secure-Boot Decision, which says when the decision is off:

    [SEP-ROM-SB-020] In `TEST_DEV` and `RMA_SiP` with chiplet debug enabled, and in
    `RMA_CHIPLET` whatever the debug lock, secure boot shall be enabled when *either* trigger is
    set, and disabled otherwise: the *signed* `secure_boot_control` bit 0 (`secure_boot_enforced`,
    offset 182) ... or the *unauthenticated* escalation flag, `unauthenticated_flags` bit 0
    (offset 3756).

    |TEST_DEV / RMA_SiP (debug open) / RMA_CHIPLET |0 |0 |0 |off

rom.adoc, Retry and Backup Bank, which says what a refused slot and a refused boot are:

    [SEP-ROM-RETRY-030] ... A failure anywhere in that chain fails the *slot*, not the boot,
    until no slot remains.

    [SEP-ROM-RETRY-050] Every fatal path in the ROM shall converge in a single failure routine
    (`rom_err_fail`) that (a) records the error code in `bl0_state.error_code`, (b) writes the
    encoded `ERROR` status to `cold_scratch[1]`, (c) writes the FAIL verdict (`0xDEADBEEF`) to
    `cold_scratch[0]`, and (d) parks in `wfi`.

rom.adoc, tbl:ip_inventory: "|AES |`0x10910000` |AES-256-CBC in-place payload decryption";
memory map: "|AES |`0x10910000` |4 KiB |Payload decryption." Stage trace: "[S11] lifecycle |
`FUSE_LC_STATE` → `INFO_EXT` (state)", "[S18] SBOOT_DIS |`FUSE_SBOOT_DIS` → `INFO_EXT` (value)",
"[S18] CHIPLET_DBG |`SBOOT_DBG_LOCK` when the debug lock is what makes a `TEST_DEV` or `RMA_SiP`
part enforce secure boot", "[S23] manifest | ... `MANIFEST_VALIDATED` | ... `MANIFEST_LOAD_FAILED`
(all slots exhausted)". Status words are STATUS_ENCODE(type, 1 = BL0, code), codes from
hw/sys/sep/doc/gen/status_values.adoc.

Both slots carry the signed encrypted image (`oca_encrypted_boot.bin`) made validly unsigned with
`clear_secure_boot`: `secure_boot_control` 0, every signing field zero, the manifest hash
resealed, the payload and its encryption fields untouched. The part is TEST_DEV with debug open,
`SBOOT_DIS` 0 and the golden CLASS_KEY, so a ROM that ignored the rule would decrypt and boot.

* CHK-ENCRYPTED-REFUSED: the flash device serves the primary manifest and then the backup
  manifest, and no MANIFEST_VALIDATED or PAYLOAD_VALIDATED word is reported.
* CHK-REFUSAL-CAUSE: `bl0_state.error_code`, as held on the PR-TCM DCCM write port at the
  verdict, is `OCA_BOOT_ERR_BASE | OCA_FAIL_SECURE_BOOT_INVARIANT` or
  `OCA_BOOT_ERR_BASE | OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT`, values from the two headers
  above. A signature or key-authorization refusal falls outside the set. OBS-REFUSAL-CODE names
  the code seen and logs each slot's console `MANIFEST_ERR=` word and the WARN status words.
* CHK-NO-DECRYPTION: over the whole run no DECRYPTION_START, DECRYPTION_END or
  DECRYPTION_FAILED word and no DECRYPT_OK console line; from the first MANIFEST_LOAD_START word
  to the MANIFEST_LOAD_FAILED word (a span that holds HMAC beats) no retirement at the entry of
  the ROM decrypt callback, KDF or AES functions and no CPU access (PR-LSU-XBAR AW or AR) to the
  4 KiB AES aperture.
* CHK-TERMINAL: an ERROR MANIFEST_LOAD_FAILED word (0x0F010213; the ERROR type is inferred from
  tbl:status_types, "Fatal; last word before the ROM parks") follows the last SPI chip-select
  assertion and precedes the last verdict word, which is 0xDEADBEEF; no retirement leaves the ROM
  aperture; for 20,000 clk after the verdict the retired PCs span at most 64 bytes and
  cold_scratch[1], cold_scratch[0] and the console do not change.
* CTRL-STIMULUS: offline, before the mutation each slot passes `verify_sealed` (sealed, the
  ciphertext decrypts under the golden key, TOC and chain valid); after the mutation
  `secure_boot_control` is 0, `unauthenticated_flags` bit 0 is 0, the payload is still marked
  encrypted, the manifest hash holds, the payload bytes and chain are unchanged and the
  ciphertext still decrypts under the golden key.
* CTRL-EFUSE: the OTP image is TEST_DEV, SBOOT_DIS 0, CHIPLET_DBG clear in SIP_DIS and SYS_DIS,
  neither vector read-locked, CLASS_KEY the golden key.
* CTRL-NON-SECURE: the ROM reports FUSE_LC_STATE with INFO_EXT 0 (TEST_DEV) and FUSE_SBOOT_DIS
  with INFO_EXT 0, and no SBOOT_DBG_LOCK; the word holding `bl0_state.secure_boot` and
  `sboot_dis` was written and holds 0 in both bytes at the verdict; the flash served each slot
  with `secure_boot_control` 0, `unauthenticated_flags` bit 0 clear and
  `payload_encryption_control` bit 0 set.
* CTRL-TAP-LIVE / CTRL-PC-WATCH-LIVE / CTRL-HALT-WINDOW: the PR-LSU-XBAR tap records HMAC and
  eFuse-map beats with known addresses; the PC watch records `rom_main` and the library
  manifest-validation entry; the record runs 20,000 clk past the verdict.
* CTRL-TCM-LIVE / CTRL-BL0-BLOCK: the PR-TCM tap records DCCM writes with known lanes; the
  `bl0_state` block found from `size` and `end_magic` at the DCCM end starts with `start_magic`.

`bl0_state.secure_boot` is at byte 16 and `error_code` at byte 32 of the block, by the
tbl:bl0_state field order under ilp32 alignment; the order holds up to `error_code`. Partial
coverage. Not graded: the `wfi` instruction itself; the primary slot's refusal cause (only the
terminal code reaches `bl0_state.error_code`); RETRY-050 (b), which conflicts with "0x0003xxxx
... reach only `bl0_state.error_code`" in Fatal ROM Error Codes; the `OCA_FAIL_*` code that
follows MANIFEST_LOAD_FAILED in [S23]; the security inventory's "Structural stage" placement
against the payload pipeline figure; the status ring (the bench ring is invalid, so each insert
reports STATUS_REPORTING_INVALID); RETRY-040 (SRAM zeroing and transport re-init between
attempts); the other lifecycle postures in which the decision is off; the escalation flag set.
The decrypt-path PCs are ROM symbols. The leaf runs `sep_rom_ot_dma_boot_test` and keeps its
transport markers.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_TEST_DEV, SBOOT_DIS_MASK
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver, load_rom_syms
from env.sep_tcm_flip import DATA_BITS, DCCM_BASE, DCCM_BYTES
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test as _Base
from sep_reg_meta import RegBlock, sym

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_class_key.toml"
)

_BL0 = 1 << 16
_ERROR = 0x0F
_INFO_EXT = 0x81
_MSG_FUSE_LC_STATE = 0x0020
_MSG_FUSE_SBOOT_DIS = 0x0058
_MSG_SBOOT_DBG_LOCK = 0x0228
_MSG_MANIFEST_VALIDATED = 0x0053
_MSG_PAYLOAD_VALIDATED = 0x0055
_MSG_DECRYPT = {"DECRYPTION_START": 0x0040, "DECRYPTION_END": 0x0042, "DECRYPTION_FAILED": 0x001A}
_MSG_MANIFEST_LOAD_START = 0x0212
_MSG_MANIFEST_LOAD_FAILED = 0x0213
_RING_INVALID = (_ERROR << 24) | _BL0 | 0x0079
_TERMINAL = (_ERROR << 24) | _BL0 | _MSG_MANIFEST_LOAD_FAILED
_VERDICT_FAIL = 0xDEADBEEF
_REFUSALS = {
    mm.boot_err(n): n
    for n in ("OCA_FAIL_SECURE_BOOT_INVARIANT", "OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT")
}
_WARN = 0x08
_MANIFEST_ERR = "MANIFEST_ERR="

# PR-TCM DCCM geometry: 2 banks, bank = byte offset bit 2, row = byte offset bits 16:3.
_BANKS = 2
_AW = 14
_DCCM_END = DCCM_BASE + DCCM_BYTES
_BL0_MAGIC = 0x5330_4C42
# Spec field order under ilp32: seven u32-sized slots and two bools padded to one u32.
_SECURE_BOOT_OFFSET = 16
_ERROR_CODE_OFFSET = 32

_OFF_UNAUTH_FLAGS = mm.K.OFF_UNAUTHENTICATED_FLAGS
_OFF_ENC_CONTROL = pm.OFF_PAYLOAD_ENCRYPTION_CONTROL
# Signed-region fields that tie the ciphertext to the manifest.
_PAYLOAD_FIELDS = (
    (pm.OFF_PAYLOAD_OFFSET, 8),
    (pm.OFF_PAYLOAD_LENGTH, 8),
    (pm.OFF_PAYLOAD_HASHED_LENGTH, 8),
    (pm.OFF_PAYLOAD_HASH, mm.HASH_FIELD_SIZE),
    (pm.OFF_PAYLOAD_HASH_CHAIN, mm.HASH_FIELD_SIZE),
    (_OFF_ENC_CONTROL, 2),
    (mm.K.OFF_ENCRYPTION_KDF, 2),
    (mm.OFF_ENCRYPTION_IV, 32),
    (mm.OFF_ENCRYPTION_KDF_INPUT, pm.OCA_KDF_INPUT_BYTES),
    (mm.K.OFF_ENCRYPTION_TYPE, 1),
)

_EFUSE = RegBlock("SEP_EFUSE_MAP")
_READ_LOCKS = _EFUSE.field_mask("LOCKS", "sip_dis_read_lock") | _EFUSE.field_mask(
    "LOCKS", "sys_dis_read_lock"
)
# SIP_DIS and SYS_DIS share the LC_DISABLE field layout.
_CHIPLET_DBG = _EFUSE.field_mask("LC_DISABLE", "chiplet_dbg")

_AES_BASE = sym("AES_REG_MAP_BASE_ADDR")
_AES_END = _AES_BASE + 0x1000
_HMAC_BASE = sym("HMAC_REG_MAP_BASE_ADDR")
_HMAC_END = sym("HMAC_MSG_FIFO_MEM_BASE_ADDR") + sym("HMAC_MSG_FIFO_MEM_SIZE")
_EFUSE_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_END = _EFUSE_BASE + sym("SEP_EFUSE_MAP_REG_MAP_SIZE")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_ROM_END = _ROM_BASE + sym("SEP_BOOT_ROM_MEM_SIZE")

_DECRYPT_FNS = (
    "plat_decrypt_payload",
    "oca_derive_payload_key",
    "aes_init",
    "aes_cbc_decrypt",
    "aes_pkcs7_strip",
)
_LIVE_FNS = ("rom_main", "oca_validate_manifest")
_DECRYPT_OK = "DECRYPT_OK"

_CS = "spi_cs_n_o"
_HALT_CYCLES = 20_000
_HALT_PC_SPAN = 64


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _code_words(status: list[tuple[int, int]], code: int) -> list[tuple[int, int]]:
    """Every BL0 status record with this code, any type."""
    return [(t, w) for t, w in status if w & 0x00FF_FFFF == _BL0 | code]


def _ext_after(status: list[tuple[int, int]], code: int) -> int | None:
    """The first status word after the first report of ``code``, ring-invalid words skipped."""
    hits = [i for i, (_, w) in enumerate(status) if w & 0x00FF_FFFF == _BL0 | code]
    if not hits:
        return None
    return next((w for _, w in status[hits[0] + 1 :] if w != _RING_INVALID), None)


def _slot(addr: int) -> tuple[int, int]:
    off = addr - DCCM_BASE
    return (off >> 2) & (_BANKS - 1), off >> 3


def _dccm_writes(tcm: SepFabricTap, end_t: int) -> tuple[dict, int, int]:
    """DCCM writes per (bank, row) as (time, data) up to end_t, with write and unknown counts."""
    writes: dict[tuple[int, int], list[tuple[int, int | None]]] = {}
    n = unknown = 0
    for b in tcm.beats:
        if b.ch != "dccm" or b.t_ps > end_t:
            continue
        for bank in range(_BANKS):
            en = b.lane("clken", bank, 1)
            if not en:
                unknown += en is None
                continue
            we = b.lane("wren", bank, 1)
            row = b.lane("addr", bank, _AW)
            if we is None or row is None:
                unknown += 1
                continue
            if we:
                writes.setdefault((bank, row), []).append(
                    (b.t_ps, b.lane("wdata", bank, DATA_BITS))
                )
                n += 1
    return writes, n, unknown


def _held(writes: list[tuple[int, int | None]]) -> int | None:
    return writes[-1][1] if writes else None


def _served(rds: list, addr: int, n: int) -> bytes | None:
    """The bytes the flash device returned for [addr, addr + n), from the first read of each."""
    out = bytearray()
    for a in range(addr, addr + n):
        hit = ev.covering_read(rds, a)
        if hit is None:
            return None
        out += ev.bytes_at(hit[1], a, 1)
    return bytes(out)


class _Observer(SepRomObserver):
    """Also counts retirements outside the ROM (keeps the first 32) and PCs after the verdict."""

    def __init__(self, test, pc_watch: frozenset[int]) -> None:
        super().__init__(
            test, keep=lambda _insn: False, tracker=False, watch=(_CS,), pc_watch=pc_watch
        )
        self.off_rom: list[tuple[int, int]] = []
        self.off_rom_count = 0
        self.after_verdict: list[tuple[int, int]] = []
        self.last_before_verdict: int | None = None

    def record(self, t: int, pc: int, insn: int, exc: bool, ecause: int, interrupt: bool):
        if not _ROM_BASE <= pc < _ROM_END:
            self.off_rom_count += 1
            if len(self.off_rom) < 32:
                self.off_rom.append((t, pc))
        if self.verdict and self.verdict[-1][1] == _VERDICT_FAIL:
            self.after_verdict.append((t, pc))
        else:
            self.last_before_verdict = t
        return super().record(t, pc, insn, exc, ecause, interrupt)


@pyuvm.test()
class sep_rom_encryption_requires_secure_boot_test(_Base):
    """TEST_DEV, debug open, both slots encrypted and unsigned: refused, nothing decrypted."""

    flash_image = _ENCRYPTED_IMAGE
    max_run_cycles = 4_000_000
    # Transport markers stay; the parent's success markers cannot appear on a refused boot.
    required_markers = ("BOOT_SPI", "MANIFEST_SRC=0x00001000")
    required_evidence = (
        "CHK-ENCRYPTED-REFUSED",
        "CHK-REFUSAL-CAUSE",
        "CHK-NO-DECRYPTION",
        "CHK-TERMINAL",
        "CHK-ROM-PATH",
    )

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.sb.expect_fw_pass = False
        self._flash_txns: list = []
        self._payload_at: dict[str, int] = {}
        syms = load_rom_syms()
        self._syms = {n: syms.get(n) for n in _DECRYPT_FNS + _LIVE_FNS}
        watch = frozenset(a for a in self._syms.values() if a is not None)
        obs = _Observer(self, watch).start()
        xbar = SepFabricTap("PR-LSU-XBAR").start()
        tcm = SepFabricTap("PR-TCM").start()
        t_start = int(get_sim_time("ps"))
        base_failed = True
        try:
            await super().run_scenario()
            base_failed = False
        finally:
            await ClockCycles(cocotb.top.clk_i, _HALT_CYCLES + 2 * STORE_LAG_MAX_CYCLES)
            t_end = int(get_sim_time("ps"))
            await obs.stop()
            await xbar.stop()
            await tcm.stop()
            try:
                self._grade(obs, xbar, tcm, t_start, t_end)
            except Exception:
                if not base_failed:
                    raise
                # The base failure is the one to report; this only keeps its traceback on top.
                self.logger.exception("grading after the failed base run also raised")
        self.chk.finish()

    # --- stimulus ------------------------------------------------------------
    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), (
            f"eFuse preload missing: {_EFUSE_PRELOAD}; restore it from git, it is the TEST_DEV "
            f"image that carries the golden CLASS_KEY"
        )
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS")
        locks = image.field_int("LOCKS")
        sip, sys_dis = image.field_int("SIP_DIS"), image.field_int("SYS_DIS")
        key = image.field_int("CLASS_KEY").to_bytes(pm.OCA_AES_KEY_BYTES, "little")
        self.chk.ctrl(
            "EFUSE",
            lc == LC_TEST_DEV
            and sboot_dis & SBOOT_DIS_MASK == 0
            and not locks & _READ_LOCKS
            and not (sip | sys_dis) & _CHIPLET_DBG
            and key == pm.OCA_TEST_CLASS_KEY,
            lc_raw=f"0x{lc:x}",
            sboot_dis=f"0x{sboot_dis:x}",
            locks=f"0x{locks:x}",
            sip_dis=f"0x{sip:x}",
            sys_dis=f"0x{sys_dis:x}",
            class_key_golden=key == pm.OCA_TEST_CLASS_KEY,
        )
        return image

    def _mutate_slot(self, buf: bytearray, slot: str) -> dict:
        base = mm.slot_base(slot)
        pm.verify_sealed(buf, slot)
        sb_before = mm.secure_boot_control(buf, slot)
        p, p_len = pm.payload_base(buf, slot), pm.manifest_payload_length(buf, slot)
        payload = bytes(buf[p : p + p_len])
        fields = [bytes(buf[base + o : base + o + n]) for o, n in _PAYLOAD_FIELDS]
        mm.clear_secure_boot(buf, slot)
        mm.verify_layout(buf, slot)
        decrypts, _plain = pm.rom_view_decrypt(buf, slot, class_key=pm.OCA_TEST_CLASS_KEY)
        unauth = int.from_bytes(
            buf[base + _OFF_UNAUTH_FLAGS : base + _OFF_UNAUTH_FLAGS + 8], "little"
        )
        return {
            "sb_before": f"0x{sb_before:02x}",
            "sb_after": mm.secure_boot_control(buf, slot),
            "unauth_bit0": unauth & 1,
            "encrypted": int(pm.is_encrypted(buf, slot)),
            "payload_same": int(bytes(buf[p : p + p_len]) == payload),
            "fields_same": int(
                [bytes(buf[base + o : base + o + n]) for o, n in _PAYLOAD_FIELDS] == fields
            ),
            "decrypts": int(decrypts),
            "sb_was_set": int(sb_before & mm.SECURE_BOOT_ENFORCED_BIT != 0),
        }

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        res = {s: self._mutate_slot(buf, s) for s in ("primary", "backup")}
        self._payload_at = {s: pm.payload_base(buf, s) for s in res}
        self.chk.ctrl(
            "STIMULUS",
            all(
                r["sb_was_set"]
                and r["sb_after"] == 0
                and r["unauth_bit0"] == 0
                and r["encrypted"]
                and r["payload_same"]
                and r["fields_same"]
                and r["decrypts"]
                for r in res.values()
            ),
            **{f"{s}_{k}": v for s, r in res.items() for k, v in r.items()},
        )
        return buf

    def log_transport(self, flash) -> None:
        self._flash_txns = list(flash.get_transactions())
        self.logger.info("flash transport: %s", ev.summarize(self._flash_txns, self._image_len))

    # --- grading -------------------------------------------------------------
    def _grade(
        self, obs: _Observer, xbar: SepFabricTap, tcm: SepFabricTap, t_start: int, t_end: int
    ) -> None:
        chk = self.chk
        status = obs.status
        rds = ev.reads(self._flash_txns)

        served = {}
        for slot in ("primary", "backup"):
            base = mm.slot_base(slot)
            sb = _served(rds, base + mm.OFF_SECURE_BOOT_CONTROL, 1)
            unauth = _served(rds, base + _OFF_UNAUTH_FLAGS, 8)
            enc = _served(rds, base + _OFF_ENC_CONTROL, 2)
            served[slot] = (
                None if sb is None else sb[0],
                None if unauth is None else int.from_bytes(unauth, "little") & 1,
                None if enc is None else int.from_bytes(enc, "little") & 1,
            )
        verdict = obs.verdict[-1] if obs.verdict else (None, None)
        t_v = verdict[0]
        writes, base = self._bl0_block(obs, tcm, t_start, t_end, t_v)
        sb_writes = writes.get(_slot(base + _SECURE_BOOT_OFFSET), []) if base is not None else []
        sb_word = _held(sb_writes)
        lc_ext = _ext_after(status, _MSG_FUSE_LC_STATE)
        sboot_ext = _ext_after(status, _MSG_FUSE_SBOOT_DIS)
        dbg_lock = _code_words(status, _MSG_SBOOT_DBG_LOCK)
        ext0 = (_INFO_EXT << 24) | _BL0
        chk.ctrl(
            "NON-SECURE",
            lc_ext == ext0
            and sboot_ext == ext0
            and not dbg_lock
            and sb_word is not None
            and sb_word & 0xFFFF == 0
            and all(v == (0, 0, 1) for v in served.values()),
            fuse_lc_state_ext=_hex(lc_ext),
            fuse_sboot_dis_ext=_hex(sboot_ext),
            sboot_dbg_lock=len(dbg_lock),
            bl0_secure_boot=-1 if sb_word is None else sb_word & 0xFF,
            bl0_sboot_dis=-1 if sb_word is None else (sb_word >> 8) & 0xFF,
            bl0_secure_boot_word_writes=len(sb_writes),
            **{
                f"{s}_served_{k}": -1 if x is None else x
                for s, v in served.items()
                for k, x in zip(("sb_control", "unauth_bit0", "encrypted_bit0"), v)
            },
        )

        aw_ar = [b for b in xbar.beats if b.ch in ("aw", "ar")]
        unknown = [b for b in aw_ar if b.addr is None]
        hmac = [b for b in aw_ar if b.addr is not None and _HMAC_BASE <= b.addr < _HMAC_END]
        efuse = [b for b in aw_ar if b.addr is not None and _EFUSE_BASE <= b.addr < _EFUSE_END]
        aes = [b for b in aw_ar if b.addr is not None and _AES_BASE <= b.addr < _AES_END]
        chk.ctrl(
            "TAP-LIVE",
            bool(hmac) and bool(efuse) and not unknown,
            beats=len(aw_ar),
            hmac_beats=len(hmac),
            efuse_beats=len(efuse),
            unknown_addr=len(unknown),
        )

        hit_names = {a: n for n, a in self._syms.items() if a is not None}
        hits = [(t, hit_names[pc]) for t, pc in obs.pc_hits]
        live = {n: sum(1 for _, h in hits if h == n) for n in _LIVE_FNS}
        missing = [n for n, a in self._syms.items() if a is None]
        chk.ctrl(
            "PC-WATCH-LIVE",
            not missing and all(live.values()),
            missing_symbols=missing or "none",
            **{f"{n}_hits": c for n, c in live.items()},
        )

        i_pm = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        i_bm = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        validated = _code_words(status, _MSG_MANIFEST_VALIDATED) + _code_words(
            status, _MSG_PAYLOAD_VALIDATED
        )
        chk.ok(
            "ENCRYPTED-REFUSED",
            i_pm is not None and i_bm is not None and i_pm[0] < i_bm[0] and not validated,
            primary_manifest_read=-1 if i_pm is None else i_pm[0],
            backup_manifest_read=-1 if i_bm is None else i_bm[0],
            reads=len(rds),
            validated_words=[_hex(w) for _, w in validated],
        )

        self._grade_cause(obs, writes, base)

        # Decryption absence is graded from the first MANIFEST_LOAD_START to MANIFEST_LOAD_FAILED.
        starts = _code_words(status, _MSG_MANIFEST_LOAD_START)
        t_term = next((t for t, w in status if w == _TERMINAL), None)
        t_lo = starts[0][0] if starts else None
        span_ok = None not in (t_lo, t_term) and t_lo < t_term

        def in_span(t: int) -> bool:
            return span_ok and t_lo <= t <= t_term

        dec_words = {n: len(_code_words(status, c)) for n, c in _MSG_DECRYPT.items()}
        dec_lines = [line for _, line in obs.console if _DECRYPT_OK in line]
        dec_hits = [(t, n) for t, n in hits if n in _DECRYPT_FNS and in_span(t)]
        aes_in = [b for b in aes if in_span(b.t_ps)]
        hmac_in = [b for b in hmac if in_span(b.t_ps)]
        chk.ok(
            "NO-DECRYPTION",
            span_ok
            and bool(hmac_in)
            and not any(dec_words.values())
            and not dec_lines
            and not dec_hits
            and not aes_in,
            **dec_words,
            attempt_span_ps=f"{_ps(t_lo)}..{_ps(t_term)}",
            hmac_beats_in_span=len(hmac_in),
            aes_beats_outside_span=len(aes) - len(aes_in),
            decrypt_ok_lines=len(dec_lines),
            decrypt_path_entries=[f"{n}@{t}" for t, n in dec_hits[:4]] or "none",
            aes_aperture=f"0x{_AES_BASE:08x}..0x{_AES_END:08x}",
            aes_beats=len(aes_in),
            first_aes_beat=_hex(aes_in[0].addr) if aes_in else "none",
        )

        clk_ps = (
            (obs.first[-1].t_ps - obs.first[0].t_ps) // (obs.first[-1].cycle - obs.first[0].cycle)
            if len(obs.first) > 1
            else 0
        )
        cs = obs.watched[_CS]
        cs_low = [t for (t, v), (_, prev) in zip(cs[1:], cs) if v == 0 and prev == 1]
        w_end = None if t_v is None or not clk_ps else t_v + _HALT_CYCLES * clk_ps
        chk.ctrl(
            "HALT-WINDOW",
            w_end is not None
            and t_end >= w_end
            and obs.last_before_verdict is not None
            and t_v - obs.last_before_verdict <= STORE_LAG_MAX_CYCLES * clk_ps,
            verdict_ps=_ps(t_v),
            window_end_ps=_ps(w_end),
            observed_to_ps=t_end,
            last_retire_before_verdict_ps=_ps(obs.last_before_verdict),
            clk_ps=clk_ps,
        )
        in_win = [pc for t, pc in obs.after_verdict if w_end is not None and t <= w_end]
        span = max(in_win) - min(in_win) if in_win else 0
        moved = [_hex(w) for t, w in status if t_v is not None and t > t_v]
        v_moved = [_hex(w) for t, w in obs.verdict if t_v is not None and t > t_v]
        printed = [line for t, line in obs.console if t_v is not None and t > t_v]
        chk.ok(
            "TERMINAL",
            None not in (t_term, t_v)
            and bool(cs_low)
            and cs_low[-1] < t_term <= t_v
            and verdict[1] == _VERDICT_FAIL
            and obs.off_rom_count == 0
            and w_end is not None
            and span <= _HALT_PC_SPAN
            and not moved
            and not v_moved
            and not printed,
            manifest_load_failed_ps=_ps(t_term),
            last_cs_assert_ps=_ps(cs_low[-1] if cs_low else None),
            verdict=_hex(verdict[1]),
            verdict_ps=_ps(t_v),
            off_rom_retirements=obs.off_rom_count,
            first_off_rom=[f"0x{pc:08x}" for _, pc in obs.off_rom[:4]] or "none",
            pc_span=span,
            status_changes=moved[:4],
            verdict_changes=v_moved[:4],
            console_after=printed[:4],
        )
        chk.obs(
            "STATUS-TAIL",
            words=[_hex(w) for _, w in status[-8:]],
            all_failed_line=int(any("MANIFEST_ALL_FAILED" in line for _, line in obs.console)),
            **{
                f"{s}_payload_read": -1 if (hit := ev.covering_read(rds, a)) is None else hit[0]
                for s, a in self._payload_at.items()
            },
        )

    def _bl0_block(
        self, obs: _Observer, tcm: SepFabricTap, t_start: int, t_end: int, t_v: int | None
    ) -> tuple[dict, int | None]:
        """DCCM writes up to the verdict and the bl0_state base, found from size and end_magic."""
        chk = self.chk
        clk_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        end_t = t_end if t_v is None else t_v + STORE_LAG_MAX_CYCLES * clk_ps
        writes, n_writes, unknown = _dccm_writes(tcm, end_t)
        first_t = obs.first[0].t_ps if obs.first else None
        chk.ctrl(
            "TCM-LIVE",
            t_v is not None
            and first_t is not None
            and t_start <= first_t
            and t_end >= end_t
            and n_writes > 0
            and unknown == 0,
            tap_ps=f"{t_start}..{t_end}",
            writes=n_writes,
            unknown=unknown,
        )
        size = _held(writes.get(_slot(_DCCM_END - 8), []))
        end_magic = _held(writes.get(_slot(_DCCM_END - 4), []))
        base = _DCCM_END - size if size and size % 4 == 0 and size > _ERROR_CODE_OFFSET else None
        ok_base = base is not None and base >= DCCM_BASE
        start_magic = _held(writes.get(_slot(base), [])) if ok_base else None
        block_ok = start_magic == _BL0_MAGIC and end_magic == _BL0_MAGIC
        chk.ctrl(
            "BL0-BLOCK",
            block_ok,
            base=_hex(base),
            size=_hex(size),
            start_magic=_hex(start_magic),
            end_magic=_hex(end_magic),
        )
        return writes, base if block_ok else None

    def _grade_cause(self, obs: _Observer, writes: dict, base: int | None) -> None:
        """The recorded fatal code against the two codes the spec names for this refusal."""
        chk = self.chk
        field = base + _ERROR_CODE_OFFSET if base is not None else None
        ec_writes = writes.get(_slot(field), []) if field is not None else []
        held = _held(ec_writes)
        chk.ok(
            "REFUSAL-CAUSE",
            held in _REFUSALS,
            expect=[_hex(c) for c in _REFUSALS],
            error_code_field=_hex(field),
            error_code_at_verdict=_hex(held),
            error_code_writes=[_hex(d) for _, d in ec_writes],
        )
        slot_codes = [
            int(line.split(_MANIFEST_ERR, 1)[1].split()[0], 16)
            for _, line in obs.console
            if _MANIFEST_ERR in line
        ]
        chk.obs(
            "REFUSAL-CODE",
            error_code=_REFUSALS.get(held, "other"),
            slot_console=[_hex(c) for c in slot_codes],
            warn_words=[_hex(w) for _, w in obs.status if w >> 24 == _WARN],
        )
