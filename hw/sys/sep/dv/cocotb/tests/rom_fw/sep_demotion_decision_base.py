# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the BL0 demotion-decision testcases.

Each member boots to completion, then checks one row of the outcome table below on the
console, the DEMOTE_1/DEMOTE_2 register probes, FEAT_CTRL and the boot measurement.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_lcc_golden import LC_PROD, LC_PROD_END, feat_ctrl_expected
from rom_fw import sep_measurement_golden as mg
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Outcomes: sel/auth = BL1_DEMOTION_VALID/ENABLE, bl2 = both BL2 bits.
# DEMOTE_1 / DEMOTE_2 as (demote, lock); (0,0) = never written.
#   O1   PROD_END, manifest ignored  DEMOTE: PROD_END lock                   (0,1)  (0,1)
#   O2a  sel=1 auth=1 bl2=0          BL1_DEMOTE=1 BL2_DEMOTE_DEC=0           (1,1)  (0,0)
#   O2b  sel=1 auth=1 bl2=1          BL1_DEMOTE=1 BL2_DEMOTE_DEC=1           (1,1)  (0,0)
#   O3a  sel=1 auth=0 bl2=0          BL1_DEMOTE=0 BL2_DEMOTE_DEC=0           (0,1)  (0,0)
#   O3b  sel=1 auth=0 bl2=1          BL1_DEMOTE=0 BL2_DEMOTE_DEC=1           (0,1)  (0,0)
#   O4   sel=0 bl2=1                 DEMOTE: BL2 deferred, unlocked          (0,0)  (0,0)
#   O5   sel=0 bl2=0                 DEMOTE: BL2 deferred, lock non-demoted  (0,1)  (0,0)

# demotion_control pairs (VALID = the directive applies, ENABLE = the demote value):
#   bits 1:0 "BL1" pair -> DEMOTE_1 (local debug DBG_1), written and locked by the ROM
#   bits 3:2 "BL2" pair -> DEMOTE_2 (inter-chiplet debug DBG_2), recorded for BL1 to write
# DEMOTE_1 stays unlocked only for BL1_VALID=0 with both BL2 bits set; PROD_END locks both.
DEMOTION_TOKENS = (
    "DEMOTE: PROD_END lock",
    "BL1_DEMOTE=",
    "DEMOTE: BL2 deferred, unlocked",
    "DEMOTE: BL2 deferred, lock non-demoted",
    "BL2_DEMOTE_DEC=",
    "DEMOTE_LOCKED",
    "DEMOTE_NOT_LOCKED",
)

# Signed-path markers, in console order.
SIGNED_PATH_REQUIRED = ("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_VERIFY_OK")
SIGNED_PATH_FORBIDDEN = (
    "SBOOT_OFF",
    "FUSE: SBOOT_DIS: 1",
    "MANIFEST_ERR=",
    "MANIFEST_ALL_FAILED",
    "RSA_PKCS1_FAIL",
    "PUBK_ALGO_UNSUPPORTED",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_SLOT_RESERVED",
    "PUBK_SLOT_UNPROVISIONED",
    "PUBK_OTP_EMPTY",
    "PUBK_UNAUTHORIZED",
)

_SAMPLE_EVERY = 1

_LC_STATE_RE = re.compile(r"LC_STATE=0x([0-9a-fA-F]{8})")


def secure_boot_decision(requested: int, sboot_dis: int, lc_raw: int) -> int:
    if requested:
        return 1
    if sboot_dis:
        return 0
    return int(lc_raw in (LC_PROD, LC_PROD_END))


def _decode_demote(state: int) -> int:
    if state not in (0b01, 0b10):
        raise AssertionError(
            f"demote rails read 0b{state:02b}, which is neither 0b10 (demote=0) nor "
            f"0b01 (demote=1). prim_diff_encode_multi drives {{~d, d}}, so an equal "
            f"pair is a broken encoder rather than a demotion verdict"
        )
    return state & 0x1


class sep_demotion_decision_base(sep_rom_ot_dma_boot_test):
    flash_image = SECURE_FLASH_IMAGE

    efuse_preload: Path | None = None
    expected_lc_raw: int = -1
    expected_sboot_dis: int = 0
    # End-of-run (demote, lock), not the register word; (0, 0) = never written (both W1S).
    expect_demote_1: tuple[int, int] = (-1, -1)
    expect_demote_2: tuple[int, int] = (-1, -1)
    demotion_required: tuple[str, ...] = ()
    demotion_values: tuple[str, ...] = ()
    # Inclusive DEMOTE sample bounds; only an outcome that writes nothing may pin (1, 1).
    demote_changes_min: int = 2
    demote_changes_max: int | None = None

    @staticmethod
    def _check_contract(obj) -> None:
        name = type(obj).__name__ if not isinstance(obj, type) else obj.__name__
        oc.assert_known(
            tuple(obj.required_markers)
            + tuple(obj.forbidden_markers)
            + tuple(obj.demotion_required)
            + tuple(obj.demotion_values),
            name,
        )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._check_contract(cls)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # A mixin may extend the marker tuples after this base's __init_subclass__ ran.
        self._check_contract(self)

    def mutate_manifest(self, buf: bytearray) -> None:
        raise NotImplementedError

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        # Required: the console cannot show a demotion input that failed to land.
        raise NotImplementedError

    def build_efuse_image(self):
        assert self.efuse_preload and self.efuse_preload.is_file(), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        assert self.expected_lc_raw >= 0, "subclass must set expected_lc_raw"
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}; fix "
            f"efuse_preload or expected_lc_raw"
        )
        assert sboot_dis == self.expected_sboot_dis, (
            f"SBOOT_DIS is {sboot_dis}, expected {self.expected_sboot_dis}"
        )
        self._sip_dis = image.field_int("SIP_DIS")
        self._sys_dis = image.field_int("SYS_DIS")
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x, SBOOT_DIS=%d, BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Anchor layout, seal and key first: a misplaced write in the signed region re-hashes.
        for slot in ("primary", "backup"):
            mm.verify_usage_constraints_layout(buf, slot)
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)
        self.mutate_manifest(buf)
        self.check_manifest_stimulus(buf)
        pbase = mm.slot_base("primary")
        # Whole fields: a prefix leaves part of the stimulus unwitnessed.
        self._planted = {
            mm.OFF_SELECTOR_BITS: bytes(
                buf[
                    pbase + mm.OFF_SELECTOR_BITS : pbase
                    + mm.OFF_SELECTOR_BITS
                    + mm.SELECTOR_BITS_LEN
                ]
            ),
            mm.OFF_DEMOTION_CONTROL: bytes(
                buf[pbase + mm.OFF_DEMOTION_CONTROL : pbase + mm.OFF_DEMOTION_CONTROL + 2]
            ),
            mm.OFF_SECURE_BOOT_CONTROL: bytes(
                buf[pbase + mm.OFF_SECURE_BOOT_CONTROL : pbase + mm.OFF_SECURE_BOOT_CONTROL + 1]
            ),
        }
        self._manifest_hash = bytes(mm.manifest_hash(buf, "primary"))
        self._sb_requested = int(
            bool(mm.secure_boot_control(buf, "primary") & mm.SECURE_BOOT_ENFORCED_BIT)
        )
        for slot in ("primary", "backup"):
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def _sample_demote(self, dut) -> tuple[int, int, int, int]:
        return (
            self.rd(dut.lcc_demote_state_1_probe_o),
            self.rd(dut.lcc_demote_lock_1_probe_o),
            self.rd(dut.lcc_demote_state_2_probe_o),
            self.rd(dut.lcc_demote_lock_2_probe_o),
        )

    async def _demote_monitor(self, dut) -> None:
        prev = None
        cycle = 0
        try:
            while True:
                await RisingEdge(dut.clk_i)
                cycle += _SAMPLE_EVERY
                # rd() raises on an unknown bit; samples before reset are skipped.
                try:
                    cur = self._sample_demote(dut)
                except Exception:  # noqa: BLE001 - X before reset is not a sample
                    continue
                if cur != prev:
                    self._demote_changes.append((cycle, cur))
                    prev = cur
        except Exception:  # noqa: BLE001 - end of sim tears down the clock
            return

    async def run_scenario(self) -> None:
        self._demote_changes: list[tuple[int, tuple[int, int, int, int]]] = []
        cocotb.start_soon(self._demote_monitor(cocotb.top))
        await super().run_scenario()

    def check_transport(self, console: list[str], flash) -> None:
        self._check_boot_chain_order(console)
        self._check_demotion_console(console)
        self._check_demote_registers()
        self._check_feat_ctrl(console)
        self._check_boot_pcr(console)
        self._check_primary_served(flash)
        self._check_stimulus_served(flash)

    def _check_boot_chain_order(self, console: list[str]) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: every member boots its primary on the first read. Console: {console}"
        )
        signed = "RSA_VERIFY_OK" in self.required_markers
        assert signed != ("RSA_EXEC" in self.forbidden_markers), (
            f"{type(self).__name__} must either require RSA_VERIFY_OK or forbid RSA_EXEC"
        )
        ordered = (SIGNED_PATH_REQUIRED if signed else ()) + ("MANIFEST_OK", "PAYLOAD_OK")
        oc.assert_attempt(
            attempts[0],
            error=None,
            stage="accepted",
            ordered=ordered,
            absent=() if signed else ("RSA_EXEC", "RSA_VERIFY_OK"),
        )

        def index_of(marker: str) -> int:
            return next((i for i, line in enumerate(console) if oc.count([line], marker)), -1)

        i_ok = index_of("MANIFEST_OK")
        i_last_demote = max(index_of(t) for t in self.demotion_required)
        i_copied = index_of("BL1_COPIED")
        i_jump = index_of("BL1_JUMP=")
        assert 0 <= i_ok < i_last_demote < i_copied < i_jump, (
            f"boot chain out of order: MANIFEST_OK@{i_ok} -> last demotion token"
            f"@{i_last_demote} -> BL1_COPIED@{i_copied} -> BL1_JUMP=@{i_jump}. The "
            f"demotion decision must sit between manifest acceptance and the BL1 "
            f"handoff. Console: {console}"
        )
        self.logger.info(
            "CHK-BOOT-CHAIN-ORDER: MANIFEST_OK@%d -> demotion@%d -> BL1_COPIED@%d -> BL1_JUMP=@%d",
            i_ok,
            i_last_demote,
            i_copied,
            i_jump,
        )

    def _check_demotion_console(self, console: list[str]) -> None:
        assert self.demotion_required, "subclass must set demotion_required"
        forbidden = tuple(t for t in DEMOTION_TOKENS if t not in self.demotion_required)
        for token in self.demotion_required:
            hits = [i for i, line in enumerate(console) if token in line]
            assert len(hits) == 1, (
                f"demotion token {token!r} appeared {len(hits)} times at {hits}, "
                f"expected exactly 1: the demotion block runs once per boot. Console: {console}"
            )
        for token in forbidden:
            assert not any(token in line for line in console), (
                f"demotion token {token!r} must not appear: it belongs to a different "
                f"row of the demotion decision table than the one this testcase "
                f"drives. Console: {console}"
            )
        for valued in self.demotion_values:
            hits = [i for i, line in enumerate(console) if valued in line]
            assert len(hits) == 1, (
                f"demotion {valued!r} appeared {len(hits)} times at {hits}, expected "
                f"exactly 1. Console: {console}"
            )
        i_ok = next((i for i, line in enumerate(console) if "MANIFEST_OK" in line), -1)
        assert i_ok >= 0, f"ROM never printed MANIFEST_OK. Console: {console}"
        for token in self.demotion_required:
            i_tok = next(i for i, line in enumerate(console) if token in line)
            assert i_ok < i_tok, (
                f"demotion token {token!r} appeared at line {i_tok}, before MANIFEST_OK "
                f"at line {i_ok}: the demotion decision cannot precede the manifest "
                f"it reads. Console: {console}"
            )
        self.logger.info(
            "CHK-DEMOTION-CONSOLE: %s each exactly once and after MANIFEST_OK; none of %s present",
            ", ".join(repr(t) for t in self.demotion_required),
            ", ".join(repr(t) for t in forbidden),
        )

    def _check_demote_registers(self) -> None:
        assert self.expect_demote_1 != (-1, -1), "subclass must set expect_demote_1"
        assert self.expect_demote_2 != (-1, -1), "subclass must set expect_demote_2"
        st1, lk1, st2, lk2 = self._sample_demote(cocotb.top)
        self.logger.info(
            "CHK-DEMOTE-TRANSITIONS: %d change(s) recorded: %s",
            len(self._demote_changes),
            [
                (c, f"st1=0b{v[0]:02b} lk1={v[1]} st2=0b{v[2]:02b} lk2={v[3]}")
                for c, v in self._demote_changes
            ],
        )
        assert self._demote_changes, (
            "no DEMOTE probe transition was recorded; check that "
            "lcc_demote_state_{1,2}_probe_o and lcc_demote_lock_{1,2}_probe_o are wired in "
            "dv/tb/tb_top.sv and that _demote_monitor() ran"
        )
        first = self._demote_changes[0][1]
        assert first == (0b10, 0, 0b10, 0), (
            f"first recorded DEMOTE sample is st1=0b{first[0]:02b} lk1={first[1]} "
            f"st2=0b{first[2]:02b} lk2={first[3]}, expected the reset state "
            f"(0b10, 0, 0b10, 0) -- demote 0 on both rails, both locks clear "
            f"(sep_lifecycle_ctrl.rdl)"
        )
        n_changes = len(self._demote_changes)
        assert n_changes >= self.demote_changes_min, (
            f"only {n_changes} DEMOTE sample(s) recorded, expected at least "
            f"{self.demote_changes_min}: BL0 never reached the DEMOTE_1 write (only O4 "
            f"writes nothing, and it sets demote_changes_min = 1)"
        )
        assert self.demote_changes_max is None or n_changes <= self.demote_changes_max, (
            f"{n_changes} DEMOTE sample(s) recorded, expected at most "
            f"{self.demote_changes_max}: a write other than the demotion decision "
            f"reached the lifecycle controller"
        )
        got_1 = (_decode_demote(st1), lk1)
        got_2 = (_decode_demote(st2), lk2)
        assert got_1 == self.expect_demote_1, (
            f"DEMOTE_1 reads (demote={got_1[0]}, lock={got_1[1]}), expected "
            f"(demote={self.expect_demote_1[0]}, lock={self.expect_demote_1[1]})"
        )
        assert got_2 == self.expect_demote_2, (
            f"DEMOTE_2 reads (demote={got_2[0]}, lock={got_2[1]}), expected "
            f"(demote={self.expect_demote_2[0]}, lock={self.expect_demote_2[1]}). BL0 "
            f"writes DEMOTE_2 only at PROD_END (lc_write_demotion_2() in rom_main.c), and "
            f"the W1S lock never clears (sep_lifecycle_ctrl.rdl)"
        )
        # DEMOTE_2 (0, 0) equals reset; only the PROD_END members prove the lock_2 probe is live.
        self.logger.info(
            "CHK-DEMOTE-REGISTERS PASS: DEMOTE_1 demote=%d lock=%d, DEMOTE_2 demote=%d "
            "lock=%d -- read from the lifecycle controller, matching the expected "
            "demotion outcome",
            got_1[0],
            got_1[1],
            got_2[0],
            got_2[1],
        )

    def _check_feat_ctrl(self, console: list[str]) -> None:
        m = next((_LC_STATE_RE.search(line) for line in console if _LC_STATE_RE.search(line)), None)
        assert m, (
            f"ROM never printed LC_STATE=, so the live LC state is unknown. Console: {console}"
        )
        lc = int(m.group(1), 16)
        assert lc == self.expected_lc_raw, (
            f"ROM read LC_STATE=0x{lc:x}, expected 0x{self.expected_lc_raw:x} from the preload"
        )
        dut = cocotb.top
        sec_dis = self.rd(dut.lcc_security_disable_probe_o) & 0x1
        assert sec_dis == 0, (
            "SEC_DIS is asserted, which forces FEAT_CTRL to all-ones and makes the "
            "comparison below vacuous; no testcase in this family presents a token"
        )
        demote_1 = _decode_demote(self.rd(dut.lcc_demote_state_1_probe_o))
        demote_2 = _decode_demote(self.rd(dut.lcc_demote_state_2_probe_o))
        want = feat_ctrl_expected(
            lc, self._sip_dis, self._sys_dis, demote_1=demote_1, demote_2=demote_2, sec_dis=0
        )
        got = self.rd(dut.lcc_feat_ctrl_probe_o)
        assert got == want, (
            f"FEAT_CTRL reads 0x{got:016x}, expected 0x{want:016x} for LC_STATE=0x{lc:x}, "
            f"SIP_DIS=0x{self._sip_dis:016x}, SYS_DIS=0x{self._sys_dis:016x}, "
            f"DEMOTE_1={demote_1}, DEMOTE_2={demote_2} (lifecycle_controller.adoc "
            f"per-LC-state feature control profile)"
        )
        self.logger.info(
            "CHK-DEMOTE-FEAT-CTRL PASS: FEAT_CTRL=0x%016x equals the spec profile for "
            "LC_STATE=0x%x, SIP_DIS=0x%016x, SYS_DIS=0x%016x, DEMOTE_1=%d, DEMOTE_2=%d",
            got,
            lc,
            self._sip_dis,
            self._sys_dis,
            demote_1,
            demote_2,
        )

    def _check_boot_pcr(self, console: list[str]) -> None:
        dc = int.from_bytes(self._planted[mm.OFF_DEMOTION_CONTROL], "little")
        bl2_pair = (1 << mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) | (
            1 << mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]
        )
        # PROD_END ignores the manifest, so no BL2 decision is recorded.
        bl2 = 0 if self.expected_lc_raw == LC_PROD_END else int(dc & bl2_pair == bl2_pair)
        demote, lock = self.expect_demote_1
        bits = demote | (lock << 1) | (bl2 << 2)
        secure_boot = secure_boot_decision(
            self._sb_requested, self.expected_sboot_dis, self.expected_lc_raw
        )
        mg.assert_boot_pcr(
            self.logger,
            console,
            self._manifest_hash,
            lc_state=self.expected_lc_raw,
            demotion_decision=bits,
            secure_boot=secure_boot,
            sboot_dis=self.expected_sboot_dis,
        )

    def _check_primary_served(self, flash) -> None:
        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions. All {len(txns)} transactions: "
            f"{[hex(t['opcode']) for t in txns]}"
        )
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address 0x{mm.PRIMARY_MANIFEST_OFFSET:x}"
        )
        idx, txn = hit
        magic = ev.bytes_at(txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert magic == mm.MANIFEST_MAGIC, (
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, expected "
            f"{mm.MANIFEST_MAGIC!r}"
        )
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the demotion verdict was taken from a "
            f"manifest this testcase did not plant its inputs in"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the demotion inputs the ROM "
            "read are the ones this testcase planted in the PRIMARY",
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
            len(rds),
        )

    def _check_stimulus_served(self, flash) -> None:
        names = {
            mm.OFF_SELECTOR_BITS: "selector_bits",
            mm.OFF_DEMOTION_CONTROL: "demotion_control",
            mm.OFF_SECURE_BOOT_CONTROL: "secure_boot_control",
        }
        assert getattr(self, "_planted", None), (
            "no planted-stimulus snapshot: mutate_flash_image() did not run, so the "
            "device-side check below has nothing to compare against"
        )
        rds = ev.reads(flash.get_transactions())
        served = {}
        pbase = mm.slot_base("primary")
        for off, want in self._planted.items():
            addr = pbase + off
            # Each field must sit in one read; a field split across reads fails here.
            hit = ev.covering_read(rds, addr)
            assert hit is not None, (
                f"no single SPI read covered {names[off]} at flash 0x{addr:x}, so "
                f"the device record cannot confirm the stimulus reached the DUT"
            )
            _i, txn = hit
            got = ev.bytes_at(txn, addr, len(want))
            assert got == want, (
                f"the device served {got.hex()} for {names[off]} at flash "
                f"0x{addr:x}, but this testcase planted {want.hex()}; the offline check "
                f"passed, so the transport changed the stimulus"
            )
            served[names[off]] = got.hex()
        self.logger.info(
            "CHK-STIMULUS-SERVED: the flash device returned exactly the planted "
            "bytes for all three demotion inputs -- %s. This is the DUT-side half "
            "of the stimulus evidence; check_manifest_stimulus() is the offline half",
            ", ".join(f"{k}={v}" for k, v in served.items()),
        )


def narrow_life_cycle_states(
    test, buf: bytearray, allowed: int, *, reseal_slots: tuple[str, ...]
) -> None:
    for slot in ("primary", "backup"):
        mm.set_lifecycle_states(buf, slot, allowed, "chiplet")
        got = mm.lifecycle_states(buf, slot, "chiplet")
        assert got == allowed, (
            f"{slot} chiplet lifecycle_states reads back 0x{got:08x} after the "
            f"write, expected 0x{allowed:08x}"
        )
        bit = mm.SELECTOR_BIT_LIFECYCLE["chiplet"]
        sel = mm.set_selector_bit(buf, slot, bit, True)
        assert sel & (1 << bit), (
            f"{slot} selector_bits is 0x{sel:032x} with bit {bit} clear after the "
            f"write, so the ROM would skip the lifecycle constraint entirely and "
            f"narrowing lifecycle_states would assert nothing"
        )
        # SEP reports no package or system lifecycle, so selecting either fails the slot.
        for scope in ("package", "system"):
            other = mm.SELECTOR_BIT_LIFECYCLE[scope]
            assert not sel & (1 << other), (
                f"{slot} selects the {scope} lifecycle (selector bit {other}), which "
                f"SEP cannot report: the slot would be refused "
                f"rather than reaching the demotion decision"
            )
    for slot in reseal_slots:
        pm.reseal(buf, slot)
        pm.verify_sealed(buf, slot)
    test.logger.info(
        "CHK-STIMULUS-LC-CONSTRAINT: both slots chiplet lifecycle_states -> 0x%08x "
        "with selector bit %d set, so the ROM must map the live LC state into this "
        "bitmap for the boot to proceed; re-sealed slots: %s",
        allowed,
        mm.SELECTOR_BIT_LIFECYCLE["chiplet"],
        ", ".join(reseal_slots) or "(none)",
    )
