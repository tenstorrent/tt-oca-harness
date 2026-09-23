# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for the BL0 demotion-decision tests.

Each member drives one row of the table below; the base checks the console tokens and
the DEMOTE_1/DEMOTE_2 ``(demote, lock)`` probes. Only BL0's decision is observable.

  sel = ``selector_bits[17]``, auth = ``usage_constraints.flags[0]``, bl2 = ``flag_args[0]``

  ==  ===============================  ==========================================  ==========  ==========
  #   condition                        console                                     DEMOTE_1    DEMOTE_2
                                                                                   (dem, lock) (dem, lock)
  ==  ===============================  ==========================================  ==========  ==========
  O1  LC = PROD_END (sel/auth/bl2      ``DEMOTE: PROD_END lock`` +                 (0, 1)      **(0, 1)**
      all ignored)                     ``DEMOTE_LOCKED``                                       only case
  O2a sel=1 auth=1 bl2=0               ``BL1_DEMOTE=1`` ``BL2_DEMOTE_DEC=0``       **(1, 1)**  (0, 0)
                                       ``DEMOTE_LOCKED``
  O2b sel=1 auth=1 bl2=1               ``BL1_DEMOTE=1`` ``BL2_DEMOTE_DEC=1``       **(1, 1)**  (0, 0)
                                       ``DEMOTE_LOCKED``
  O3a sel=1 auth=0 bl2=0               ``BL1_DEMOTE=0`` ``BL2_DEMOTE_DEC=0``       (0, 1)      (0, 0)
                                       ``DEMOTE_LOCKED``
  O3b sel=1 auth=0 bl2=1               ``BL1_DEMOTE=0`` ``BL2_DEMOTE_DEC=1``       (0, 1)      (0, 0)
                                       ``DEMOTE_LOCKED``
  O4  sel=0 bl2=1 (auth ignored)       ``DEMOTE: BL2 deferred, unlocked`` +        **(0, 0)**  (0, 0)
                                       ``BL2_DEMOTE_DEC=1`` ``DEMOTE_NOT_LOCKED``  unwritten
  O5  sel=0 bl2=0 (auth ignored)       ``DEMOTE: BL2 deferred, lock non-demoted``  (0, 1)      (0, 0)
                                       + ``BL2_DEMOTE_DEC=0`` ``DEMOTE_LOCKED``
  ==  ===============================  ==========================================  ==========  ==========
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

EFUSE_DIR = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
)

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Every demotion console token; a member requires its own and forbids the rest.
DEMOTION_TOKENS = (
    "DEMOTE: PROD_END lock",
    "BL1_DEMOTE=",
    "DEMOTE: BL2 deferred, unlocked",
    "DEMOTE: BL2 deferred, lock non-demoted",
    "BL2_DEMOTE_DEC=",
    "DEMOTE_LOCKED",
    "DEMOTE_NOT_LOCKED",
)

# The monitor samples every clock edge; this only scales the logged cycle count.
_SAMPLE_EVERY = 1


def _decode_demote(state: int) -> int:
    if state not in (0b01, 0b10):
        raise AssertionError(
            f"demote rails read 0b{state:02b}, which is neither 0b10 (demote=0) nor "
            f"0b01 (demote=1). prim_diff_encode_multi drives {{~d, d}} "
            f"(hw/common/och_prim/rtl/prim_diff_encode_multi.sv:41-49), so an equal "
            f"pair is a broken encoder rather than a demotion verdict"
        )
    return state & 0x1


class sep_demotion_decision_base(sep_rom_ot_dma_boot_test):

    flash_image = SECURE_FLASH_IMAGE

    efuse_preload: Path | None = None
    expected_lc_raw: int = -1
    expected_sboot_dis: int = 0
    # (0, 0) means BL0 never wrote the register; both fields are write-one-to-set.
    expect_demote_1: tuple[int, int] = (-1, -1)
    expect_demote_2: tuple[int, int] = (-1, -1)
    # Every DEMOTION_TOKENS entry not listed here is forbidden.
    demotion_required: tuple[str, ...] = ()
    # Valued strings, such as "BL1_DEMOTE=1", that must appear exactly once.
    demotion_values: tuple[str, ...] = ()
    # Inclusive bounds on recorded DEMOTE samples; only O4 (no write) may go below 2.
    demote_changes_min: int = 2
    demote_changes_max: int | None = None

    def mutate_manifest(self, buf: bytearray) -> None:
        raise NotImplementedError

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        # The ROM does not echo every input, so a stimulus that did not land is silent.
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
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}. The "
            f"lifecycle IS the first demotion input (rom_main.c:383), so running "
            f"under the wrong one measures a different row of the decision table "
            f"under this testcase's name"
        )
        assert sboot_dis == self.expected_sboot_dis, (
            f"SBOOT_DIS is {sboot_dis}, expected {self.expected_sboot_dis}"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x, SBOOT_DIS=%d, BL1_VERSION=0x%x, "
            "PUBK_REVOKE=0x%x", lc, sboot_dis, image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # A wrong field offset would re-seal cleanly, so anchor layout and signer first.
        for slot in ("primary", "backup"):
            mm.verify_usage_constraints_layout(buf, slot)
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)
        self.mutate_manifest(buf)
        self.check_manifest_stimulus(buf)
        # Snapshot the planted demotion fields for _check_stimulus_served().
        pbase = mm.slot_base("primary")
        self._planted = {
            mm.OFF_SELECTOR_BITS: bytes(
                buf[pbase + mm.OFF_SELECTOR_BITS:pbase + mm.OFF_SELECTOR_BITS + 8]),
            mm.OFF_USAGE_FLAGS: bytes(
                buf[pbase + mm.OFF_USAGE_FLAGS:pbase + mm.OFF_USAGE_FLAGS + 4]),
            mm.OFF_FLAG_ARGS: bytes(
                buf[pbase + mm.OFF_FLAG_ARGS:pbase + mm.OFF_FLAG_ARGS + 4]),
        }
        for slot in ("primary", "backup"):
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

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
                # rd() maps X to 0, so a 4-state simulator needs explicit X handling here.
                try:
                    cur = self._sample_demote(dut)
                except Exception:  # noqa: BLE001 - unreachable while rd() returns 0
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
        self._check_primary_served(flash)
        self._check_stimulus_served(flash)

    def _check_boot_chain_order(self, console: list[str]) -> None:
        # The demotion write must precede the BL1 handoff; no other check sees that order.
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_ok = index_of("MANIFEST_OK")
        i_last_demote = max(index_of(t) for t in self.demotion_required)
        i_copied = index_of("BL1_COPIED")
        i_jump = index_of("BL1_JUMP=")
        assert 0 <= i_ok < i_last_demote < i_copied < i_jump, (
            f"boot chain out of order: MANIFEST_OK@{i_ok} -> last [C15] token"
            f"@{i_last_demote} -> BL1_COPIED@{i_copied} -> BL1_JUMP=@{i_jump}. The "
            f"demotion decision must sit between manifest acceptance and the BL1 "
            f"handoff (rom_main.c:349-353, :377-436, :444). Console: {console}"
        )
        self.logger.info(
            "CHK-BOOT-CHAIN-ORDER: MANIFEST_OK@%d -> [C15]@%d -> BL1_COPIED@%d -> "
            "BL1_JUMP=@%d", i_ok, i_last_demote, i_copied, i_jump,
        )

    def _check_demotion_console(self, console: list[str]) -> None:
        assert self.demotion_required, "subclass must set demotion_required"
        forbidden = tuple(t for t in DEMOTION_TOKENS if t not in self.demotion_required)
        for token in self.demotion_required:
            hits = [i for i, line in enumerate(console) if token in line]
            assert len(hits) == 1, (
                f"[C15] token {token!r} appeared {len(hits)} times at {hits}, "
                f"expected exactly 1. The demotion block runs once per boot "
                f"(rom_main.c:379-436), so any other count means it ran twice or not "
                f"at all. Console: {console}"
            )
        for token in forbidden:
            assert not any(token in line for line in console), (
                f"[C15] token {token!r} must not appear: it belongs to a different "
                f"row of the demotion decision table than the one this testcase "
                f"drives. Console: {console}"
            )
        for valued in self.demotion_values:
            hits = [i for i, line in enumerate(console) if valued in line]
            assert len(hits) == 1, (
                f"[C15] {valued!r} appeared {len(hits)} times at {hits}, expected "
                f"exactly 1. The token alone says the branch ran; this says what it "
                f"decided. Console: {console}"
            )
        # The decision reads the accepted manifest, so every token follows MANIFEST_OK.
        i_ok = next((i for i, line in enumerate(console) if "MANIFEST_OK" in line), -1)
        assert i_ok >= 0, f"ROM never printed MANIFEST_OK. Console: {console}"
        for token in self.demotion_required:
            i_tok = next(i for i, line in enumerate(console) if token in line)
            assert i_ok < i_tok, (
                f"[C15] token {token!r} appeared at line {i_tok}, before MANIFEST_OK "
                f"at line {i_ok}: the demotion decision cannot precede the manifest "
                f"it reads (rom_main.c:349-353 then :380-381). Console: {console}"
            )
        self.logger.info(
            "CHK-DEMOTION-CONSOLE: %s each exactly once and after MANIFEST_OK; none "
            "of %s present",
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
            [(c, f"st1=0b{v[0]:02b} lk1={v[1]} st2=0b{v[2]:02b} lk2={v[3]}")
             for c, v in self._demote_changes],
        )
        # A constant probe could match the final value, so require reset state then a change.
        assert self._demote_changes, (
            "no DEMOTE probe transition was recorded at all. Either the probes are "
            "not wired (lcc_demote_state_{1,2}_probe_o / lcc_demote_lock_{1,2}_probe_o "
            "in dv/tb/tb_top.sv) or the monitor never sampled, in which case the "
            "end-of-run values below are not evidence of anything BL0 did"
        )
        first = self._demote_changes[0][1]
        assert first == (0b10, 0, 0b10, 0), (
            f"first recorded DEMOTE sample is st1=0b{first[0]:02b} lk1={first[1]} "
            f"st2=0b{first[2]:02b} lk2={first[3]}, expected the reset state "
            f"(0b10, 0, 0b10, 0) -- demote 0 on both rails, both locks clear "
            f"(sep_lifecycle_ctrl.rdl:23-36). If the run STARTS at the expected final "
            f"value then the value proves nothing about this boot"
        )
        n_changes = len(self._demote_changes)
        assert n_changes >= self.demote_changes_min, (
            f"only {n_changes} DEMOTE sample(s) recorded, expected at least "
            f"{self.demote_changes_min}, so the registers never moved off their reset "
            f"value. Every outcome of the [C15] block except O4 writes DEMOTE_1, so no "
            f"transition means BL0 did not reach rom_main.c:432. O4 is the one member "
            f"entitled to a single sample and it declares demote_changes_min = 1"
        )
        assert self.demote_changes_max is None or n_changes <= self.demote_changes_max, (
            f"{n_changes} DEMOTE sample(s) recorded, expected at most "
            f"{self.demote_changes_max}. A member that pins the count exactly is "
            f"asserting that the registers moved that many times and no more; an extra "
            f"transition means something other than the single [C15] write reached the "
            f"lifecycle controller"
        )
        got_1 = (_decode_demote(st1), lk1)
        got_2 = (_decode_demote(st2), lk2)
        assert got_1 == self.expect_demote_1, (
            f"DEMOTE_1 reads (demote={got_1[0]}, lock={got_1[1]}), expected "
            f"(demote={self.expect_demote_1[0]}, lock={self.expect_demote_1[1]}). "
            f"This is the value BL0 actually retired into the lifecycle controller, "
            f"not the value it printed -- the console string is formatted from a "
            f"local (rom_main.c:395-397, :431-435) and cannot detect a write that "
            f"went to the wrong place or carried the wrong value"
        )
        assert got_2 == self.expect_demote_2, (
            f"DEMOTE_2 reads (demote={got_2[0]}, lock={got_2[1]}), expected "
            f"(demote={self.expect_demote_2[0]}, lock={self.expect_demote_2[1]}). "
            f"BL0 writes DEMOTE_2 on exactly one path -- lc_write_demotion_2(false, "
            f"true) at rom_main.c:386, reached only at PROD_END -- so lock=0 here "
            f"means it was never written, which is sound because the field is "
            f"write-one-to-set and hardware never clears it "
            f"(sep_lifecycle_ctrl.rdl:31-36)"
        )
        # (0, 0) is also the reset value; the PROD_END members prove the lock_2 probe is live.
        self.logger.info(
            "CHK-DEMOTE-REGISTERS: DEMOTE_1 demote=%d lock=%d, DEMOTE_2 demote=%d "
            "lock=%d -- read from the lifecycle controller, matching the expected "
            "[C15] outcome", got_1[0], got_1[1], got_2[0], got_2[1],
        )

    def _check_primary_served(self, flash) -> None:
        # A silent failover would still print a valid-looking verdict for another row.
        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions. All {len(txns)} transactions: "
            f"{[hex(t['opcode']) for t in txns]}"
        )
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}"
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
            idx, mm.PRIMARY_MANIFEST_OFFSET, magic, len(rds),
        )


    def _check_stimulus_served(self, flash) -> None:
        names = {mm.OFF_SELECTOR_BITS: "usage_constraints.selector_bits",
                 mm.OFF_USAGE_FLAGS: "usage_constraints.flags",
                 mm.OFF_FLAG_ARGS: "boot_arguments.flag_args"}
        assert getattr(self, "_planted", None), (
            "no planted-stimulus snapshot: mutate_flash_image() did not run, so the "
            "device-side check below has nothing to compare against"
        )
        rds = ev.reads(flash.get_transactions())
        served = {}
        pbase = mm.slot_base("primary")
        for off, want in self._planted.items():
            addr = pbase + off
            # Each field must sit in one read; stitch reads if the transport splits one.
            hit = ev.covering_read(rds, addr)
            assert hit is not None, (
                f"no single SPI read covered {names[off]} at flash 0x{addr:x}, so "
                f"the device record cannot confirm the stimulus reached the DUT"
            )
            _i, txn = hit
            got = ev.bytes_at(txn, addr, len(want))
            assert got == want, (
                f"the device served {got.hex()} for {names[off]} at flash "
                f"0x{addr:x}, but this testcase planted {want.hex()}. The offline "
                f"artefact check passed, so the difference is in the transport, not "
                f"in the mutation -- the DUT was given a different stimulus from the "
                f"one this testcase's name describes"
            )
            served[names[off]] = got.hex()
        self.logger.info(
            "CHK-STIMULUS-SERVED: the flash device returned exactly the planted "
            "bytes for all three demotion inputs -- %s. This is the DUT-side half "
            "of the stimulus evidence; check_manifest_stimulus() is the offline half",
            ", ".join(f"{k}={v}" for k, v in served.items()),
        )


def narrow_life_cycle_states(test, buf: bytearray, allowed: int, *,
                             reseal_slots: tuple[str, ...]) -> None:
    # One permitted LC state makes the boot prove which state the ROM decoded.
    for slot in ("primary", "backup"):
        mm.set_life_cycle_states(buf, slot, allowed)
        got = mm.life_cycle_states(buf, slot)
        assert got == allowed, (
            f"{slot} life_cycle_states reads back 0x{got:08x} after the write, "
            f"expected 0x{allowed:08x}"
        )
        sel = mm.selector_bits(buf, slot)
        assert sel & (1 << mm.SELECTOR_BIT_LIFE_CYCLE_STATES), (
            f"{slot} selector_bits is 0x{sel:016x} with bit "
            f"{mm.SELECTOR_BIT_LIFE_CYCLE_STATES} clear, so the ROM would SKIP the "
            f"lifecycle usage-constraint check entirely (manifest_load.c:540) and "
            f"narrowing life_cycle_states would assert nothing"
        )
    for slot in reseal_slots:
        pm.reseal(buf, slot)
        pm.verify_sealed(buf, slot)
    test.logger.info(
        "CHK-STIMULUS-LC-CONSTRAINT: both slots life_cycle_states 0x%08x -> "
        "0x%08x with selector bit %d set, so manifest_load.c:540-549 must map the "
        "live LC state into this bitmap for the boot to proceed; re-sealed slots: %s",
        mm.SHIPPED_LIFE_CYCLE_STATES, allowed, mm.SELECTOR_BIT_LIFE_CYCLE_STATES,
        ", ".join(reseal_slots) or "(none)",
    )
