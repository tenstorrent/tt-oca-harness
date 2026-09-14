# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the BL0 demotion-decision testcases ([C15]).

Every member boots to completion and they differ only in the demotion inputs and
in the verdict those inputs must produce, so the register observation, the
ordering chain and the disclosure live here once.

**EIGHT members inherit this file, covering SIX of the seven outcomes below.** The
two intermediate bases are ``rom_fw/sep_demotion_prod_base.py`` (PROD, secure boot
disabled on both surfaces) and ``rom_fw/sep_demotion_prod_end_base.py``.

============================================================================
THE MECHANISM, ESTABLISHED ONCE FOR THE WHOLE DEMOTION GROUP
============================================================================

The decision is ``rom_main.c`` and it reads exactly FOUR inputs:

  ==========================================  ==============
  input                                       source
  ==========================================  ==============
  ``lc_state``                                eFuse LC_STATE
  ``usage_constraints.selector_bits`` bit 17  manifest
  ``usage_constraints.flags`` bit 0           manifest
  ``boot_arguments.flag_args`` bit 0          manifest
  ==========================================  ==============

Bit positions: ``SELECTOR_BIT_BL1_DEMOTION`` is 17 because
``SELECTOR_BIT_LIFE_CYCLE_STATES`` is ``DEVICE_ID_NUM_WORDS * 2`` = 16
(``manifest.h``); ``USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION`` is 0
(``manifest.h``); ``FLAG_ARGS_BIT_BL2_DEMOTION`` is 0 (``manifest.h``).

**THE COLLAPSE, AND IT IS THE MOST IMPORTANT THING IN THIS FILE.** ``rom_main.c``
short-circuits on ``lc_state == LC_STATE_PROD_END`` and returns from the block having
read NONE of the three manifest inputs -- the selector bit,
``usage_constraints.flags`` and ``flag_args`` are consulted only inside the
``else``. So **at PROD_END every combination of
the three manifest inputs produces the identical outcome.** The five PROD_END
demotion stimuli are FIVE STIMULI ON ONE OBSERVABLE, not five coverage points; the
PROD_END members cover that one outcome and say so.

The seven distinct observables of the whole block, derived from the source and
confirmed here on RTL. ``sel`` = ``selector_bits[17]``, ``auth`` =
``usage_constraints.flags[0]``, ``bl2`` = ``flag_args[0]``.

**THE REGISTER COLUMNS ARE ``(demote, lock)`` TUPLES, IN THE SAME FORM AS
``expect_demote_1`` / ``expect_demote_2`` BELOW.** They are NOT the 32-bit word
``lc_write_demotion()`` composes, and NOT the 2-bit probe rail value: all three
notations are in play in this file, and tabulating the register WORD (``0x2`` /
``0x3``) would collide with the rail encoding -- ``0b11`` is the broken-rail
condition :func:`_decode_demote` raises on, and ``0b10`` equals the word for "no
demote, locked". ``(0, 0)`` means the register was never written.

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

For the record, the three notations and how to convert: the ROM composes the register
WORD as ``{lock[1], demote[0]}`` (``bootrom/prod/src/lifecycle.c:116-128``, masks at
``regs/gen/c/blocks/sep_lifecycle_ctrl.h``), so O2a's word is ``0x3``; the DUT output
rail pair is ``{~demote, demote}``, so O2a's ``lcc_demote_state_1_probe_o`` is
``0b01``; and this table and the assertions use ``(demote, lock)``.

**A CAVEAT ON O4.** O4 is the only outcome with ``lock == 0``, and
``sep_lifecycle_ctrl.sv`` derives the register's software write-enable as ``~lock``,
so on O4 the register stays WRITEABLE by later software. Every member of this family
reads its registers AFTER BL1 has executed:
``dv/fw/tests/bl1_pass_test/bl1_pass_test.c`` is a real payload that runs to
completion -- it prints ``BL1`` and writes the mailbox PASS the harness gates on. An
end-of-run read is nevertheless sound on every LOCKED outcome: the DEMOTE field's
software write-enable is ``~lock`` (``sep_lifecycle_ctrl.sv``) and the LOCK field is
write-one-to-set with no hardware clear (``sep_lifecycle_ctrl.rdl:23-36``), so
neither field can be walked back, and ``grep -rnE "DEMOTE|LIFECYCLE"
dv/fw/tests/bl1_pass_test/`` returns nothing. The O4 member does not need that
argument: it pins the transition count EXACTLY, across the whole simulation
including BL1.

The map above is derived from this tree's ``rom_main.c``.

**O4 IS THE HIGHEST-VALUE OUTCOME.** It is the only path where ``lock_demotion``
goes false (``rom_main.c``), the only one producing ``DEMOTE_NOT_LOCKED``, and the
ONLY one where DEMOTE_1 is left entirely unwritten -- which, on this platform, is
directly observable as ``lcc_demote_lock_1_probe_o == 0`` and is a claim the console
cannot make, because ``DEMOTE_NOT_LOCKED`` is printed from a local, not read back
from the register. Every PROD_END member beyond the first is covered-by-O1 and says
so, with this file cited, rather than counting as an independent coverage point.

**O4 MUST OVERRIDE THE TRANSITION-COUNT BOUND.** :meth:`_check_demote_registers`
requires at least :attr:`demote_changes_min` probe samples, two by default. On O4
DEMOTE_1 is never written and DEMOTE_2 is untouched, so the registers stay at their
reset value and there is exactly ONE sample -- the default bound fires with "the
registers never moved off their reset value", which for O4 is the CORRECT behaviour,
not a defect. The O4 member declares ``(1, 1)``, which pins the count EXACTLY and is
stricter than the default rather than a relaxation of it. **Do not read that failure
as a DUT problem and do not weaken the default.**

Outcome **O3b** (``sel=1 auth=0 bl2=1``) has no testcase. Four PROD members share
``rom_fw/sep_demotion_prod_base.py`` and two PROD_END members share
``rom_fw/sep_demotion_prod_end_base.py``; the O1 member ``auth_flag_0_prod_end`` and
the O2a member ``auth_flag_0_prod_sel_bit_set`` carry the skeleton inline. All eight
reach this file, which keeps the register observation, the ordering chain and the
disclosures in one place.

**THE OTHER TWO PROD_END MEMBERS ARE COVERED-BY-O1 AND SAY SO.** They are
``no_flag_prod_end`` (all three manifest inputs clear) and
``no_flag_prod_end_sel_bit_set`` (selector bit 17 set). Both produce the O1 outcome
that ``auth_flag_0_prod_end`` covers, so neither adds a ROM path.
They are not equally weak, and the difference is in what a FAILURE would mean rather
than in the outcome: with ``sel = 1`` at PROD_END the O1 outcome is reachable only if
``rom_main.c`` preempts the selector-bit arm, so
``no_flag_prod_end_sel_bit_set`` is a negative control on the short-circuit ORDER
that neither ``auth_flag_0_prod_end`` (sel 0) nor ``no_flag_prod_end`` (all inputs
clear) can provide. ``no_flag_prod_end`` adds no falsifying power at all and its own
docstring states that plainly.

============================================================================
THE EVIDENCE CHANNEL, AND WHY IT HAD TO BE ADDED
============================================================================

**The console alone cannot check this feature.** Every demotion string is printed
from a LOCAL computed one line earlier -- ``BL1_DEMOTE=`` from ``demotion_reg``
(``rom_main.c``), ``DEMOTE_LOCKED`` / ``DEMOTE_NOT_LOCKED`` from
``lock_demotion`` -- so a ROM that decided correctly, printed
correctly and then wrote the wrong value to the wrong register would pass a
console-only test unchallenged: an instrument that shares the DUT's assumption
cannot falsify it.

An external AXI read-back is not a substitute: ``rtl/sep.sv`` passes
``.inbound_filter_skip_i (feat_ctrl.sep_debug)`` and ``sep_debug`` is 0 under
PROD_END, so such an access must clear the inbound filter, and the LOCK bit is on no
port at all. ``lcc_demote_state_1_o`` and ``lcc_demote_state_2_o`` are
``sep_wrapper`` outputs (``rtl/sep_lifecycle_ctrl.sv`` up through
``rtl/sep_crypto.sv`` and ``rtl/sep.sv``). ``dv/tb/tb_top.sv`` therefore exposes
``lcc_demote_state_{1,2}_probe_o``, the DUT outputs brought out unchanged, and
``lcc_demote_lock_{1,2}_probe_o``, read-only XMRs of ``demote_reg_{1,2}.lock``
(``rtl/sep_lifecycle_ctrl.sv``) -- the same probe class as
``sep_internal_interrupts_probe_o``, no force and no deposit.

``state`` is differentially encoded ``{~demote, demote}``
(``hw/common/och_prim/rtl/prim_diff_encode_multi.sv:41-49``), so bit 0 IS the demote
bit and ``2'b00`` / ``2'b11`` are broken rails rather than verdicts. Both register
fields are write-one-to-set and are never cleared by hardware
(``regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl:23-36``), which is what
makes an end-of-run read sound: the value observed IS what BL0 wrote, and "never
written" is observable as ``lock == 0`` rather than being indistinguishable from
"written with zeros".

============================================================================
DISCLOSED GAPS
============================================================================

**THE MEMBERS ASSERT MORE THAN THE REFERENCE DOES.** The reference's PROD_END row
expects only ``STATUS: DEMOTION_NOT_SELECTED`` (``sep_demotion_uid_checker.py``) and
appends NO lock expectation at all; its PROD row expects ``DEMOTION_SELECTED`` +
``DEMOTION_LOCKED``. The PROD_END members here additionally require DEMOTE_1 and
DEMOTE_2 to read locked. That expectation is derived from THIS ROM (``rom_main.c``),
not from the reference, and it is the single strongest discriminator in the family
-- but it is an addition, not a port.

**These are HALF-PORTS and every member says so.** The reference's demotion/UID test
spends about half its volume verifying that the demotion decision then feeds the
KBKDF salt and the three SKS UID keys -- the KBKDF model (the salt is
built from ``lc_state``, the demotion decision and ``sboot_dis``), the
SKS bus monitor, and the UID comparison. This ROM has
no BL0-side key-manager driver on the demotion path -- ``rom_main.c`` stores
``bl2_demotion_decision`` into ``bl0_state`` for BL1 to consume and BL0 derives
nothing from it -- so that half cannot be ported here at all. **These testcases cover
the DECISION only.**

**There is no architected demotion status code on this ROM.** ``grep -n DEMOT
bootrom/prod/include/status_values.h`` is empty, and the whole [C15] block contains
no ``report_status`` call, so the reference's ``STATUS: DEMOTION_SELECTED`` /
``_NOT_SELECTED`` / ``_LOCKED`` / ``_NOT_LOCKED``
(``sep_demotion_uid_checker.py``) cannot be ported on either platform: here the
codes do not exist, not merely go unemitted. The register probes above are the
substitution, and they are STRONGER than the strings the reference scrapes.
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

EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Every console string the [C15] block can emit (rom_main.c). A member requires
# the ones its outcome produces and forbids
# ALL the others, which is what stops two members of this family from accepting each
# other's log.
DEMOTION_TOKENS = (
    "DEMOTE: PROD_END lock",
    "BL1_DEMOTE=",
    "DEMOTE: BL2 deferred, unlocked",
    "DEMOTE: BL2 deferred, lock non-demoted",
    "BL2_DEMOTE_DEC=",
    "DEMOTE_LOCKED",
    "DEMOTE_NOT_LOCKED",
)

# How often the register sampler wakes. The demotion write happens once, late, and
# is never cleared, so this only decides the resolution of the transition record in
# the log -- not whether the final value is observed.
_SAMPLE_EVERY = 1


def _decode_demote(state: int) -> int:
    """Decode the 2-bit {~demote, demote} rail pair, or raise if it is broken."""
    if state not in (0b01, 0b10):
        raise AssertionError(
            f"demote rails read 0b{state:02b}, which is neither 0b10 (demote=0) nor "
            f"0b01 (demote=1). prim_diff_encode_multi drives {{~d, d}} "
            f"(hw/common/och_prim/rtl/prim_diff_encode_multi.sv:41-49), so an equal "
            f"pair is a broken encoder rather than a demotion verdict"
        )
    return state & 0x1


class sep_demotion_decision_base(sep_rom_ot_dma_boot_test):
    """Boot to completion and check the [C15] demotion verdict on both channels."""

    flash_image = SECURE_FLASH_IMAGE

    # --- subclass contract -------------------------------------------------
    # Committed OTP preload this scenario needs.
    efuse_preload: Path | None = None
    # Expected raw LC state, so a member cannot silently run under the other's fuse.
    expected_lc_raw: int = -1
    # Expected SBOOT_DIS fuse value.
    expected_sboot_dis: int = 0
    # Expected end-of-run (demote, lock) for each register. `lock == 0` with
    # `demote == 0` is the observable form of "BL0 never wrote this register",
    # sound only because both fields are write-one-to-set.
    expect_demote_1: tuple[int, int] = (-1, -1)
    expect_demote_2: tuple[int, int] = (-1, -1)
    # Console tokens from DEMOTION_TOKENS this outcome must produce. Everything
    # else in DEMOTION_TOKENS is forbidden automatically, which is what stops one
    # member of this family accepting another member's log.
    demotion_required: tuple[str, ...] = ()
    # Fully VALUED console strings this outcome must produce exactly once, e.g.
    # "BL1_DEMOTE=1". Separate from demotion_required because the ROM prints these
    # with simputsdec24 (rom_virt_console.h) and the decoder renders the payload
    # as plain decimal (env/sep_rom_console.py:82-84), so the token and its value
    # are two different claims: that the branch ran, and what it decided.
    demotion_values: tuple[str, ...] = ()
    # Bounds on how many DEMOTE probe samples the monitor must record, inclusive.
    # The default pair (2, None) requires at least one transition after the reset
    # sample.
    #
    # O4 is the one outcome with a single sample: ``rom_main.c`` clears
    # ``lock_demotion``, so ``lc_write_demotion`` never runs, DEMOTE_1 is never
    # written, both registers stay at their reset value and the monitor records
    # exactly ONE sample -- the reset sample itself. The O4 member sets ``(1, 1)``,
    # which is STRICTER than the default in the only direction O4 can be strict: it
    # pins the count exactly instead of leaving it open above.
    # **Do not relax the default to accommodate O4.**
    demote_changes_min: int = 2
    demote_changes_max: int | None = None

    def mutate_manifest(self, buf: bytearray) -> None:
        raise NotImplementedError

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Assert the mutated fields, from the ARTEFACT, before the run.

        Not optional, and not duplication of the console. Two of the four demotion
        inputs are fields the ROM does not echo by value on every path -- at
        PROD_END it echoes none of them -- so a stimulus that silently failed to
        land would produce exactly the log a correct run produces. A member whose
        whole content is "the flag is set and the ROM ignores it" needs per-run
        confirmation that the flag was set: assert the stimulus, not only the
        outcome.
        """
        raise NotImplementedError

    # --- stimulus ----------------------------------------------------------
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
            "CHK-STIMULUS-EFUSE: LC raw=0x%x, SBOOT_DIS=%d, BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Anchor the usage_constraints offsets against the shipped bytes BEFORE
        # touching them: verify_layout only proves the hash covers the TBS, which
        # cannot catch a field that moved WITHIN it, and a demotion mutator writing
        # into the wrong offset would re-hash cleanly and produce a plausible run.
        # Anchor the whole image before mutating: each slot is fully sealed, its
        # modulus is the dev0 key the ROM has in slot 0, and the local signer
        # reproduces the packer's own signature byte for byte. The last of these is
        # what makes a later re-seal sound by construction rather than by assertion.
        for slot in ("primary", "backup"):
            mm.verify_usage_constraints_layout(buf, slot)
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)
        self.mutate_manifest(buf)
        self.check_manifest_stimulus(buf)
        # Snapshot the three demotion input fields as PLANTED, keyed by their
        # manifest-relative offset, so _check_stimulus_served() can require the
        # DEVICE to have returned exactly these bytes. See that method for why the
        # offline artefact check is not sufficient on its own.
        pbase = mm.slot_base("primary")
        self._planted = {
            mm.OFF_SELECTOR_BITS: bytes(
                buf[pbase + mm.OFF_SELECTOR_BITS : pbase + mm.OFF_SELECTOR_BITS + 8]
            ),
            mm.OFF_USAGE_FLAGS: bytes(
                buf[pbase + mm.OFF_USAGE_FLAGS : pbase + mm.OFF_USAGE_FLAGS + 4]
            ),
            mm.OFF_FLAG_ARGS: bytes(buf[pbase + mm.OFF_FLAG_ARGS : pbase + mm.OFF_FLAG_ARGS + 4]),
        }
        for slot in ("primary", "backup"):
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    # --- register observation ----------------------------------------------
    def _sample_demote(self, dut) -> tuple[int, int, int, int]:
        return (
            self.rd(dut.lcc_demote_state_1_probe_o),
            self.rd(dut.lcc_demote_lock_1_probe_o),
            self.rd(dut.lcc_demote_state_2_probe_o),
            self.rd(dut.lcc_demote_lock_2_probe_o),
        )

    async def _demote_monitor(self, dut) -> None:
        """Record every change of the four demotion probes, with the cycle number.

        The final value is what the assertions use -- both fields are write-one-to-set
        so it cannot be walked back -- but the transition record is what turns "the
        register reads 0x3" into "BL0 wrote it, once, and it was 0 before".

        Two levels of exception handling, and they are not the same thing. The
        OUTER one returns when the clock itself is torn down at end of simulation,
        which is the same idiom ``sep_firmware_mbist_pass_test._gate_monitor`` uses;
        without it an uncaught exception in a
        ``start_soon`` coroutine would surface as a failure of a testcase that had
        already done its job. That guard is load-bearing and does fire.

        **THE INNER ONE IS INERT.** :meth:`sep_base_test.rd` resolves unknown bits
        to zero and never raises, so ``_sample_demote`` never raises and this
        ``except`` cannot be reached. Under Verilator that is harmless: the model
        is 2-state and the differential encoder drives ``2'b10`` from cycle 0, so
        the first recorded sample is the reset state. On a 4-state simulator an X
        probe would resolve to 0, the first recorded sample would be
        ``(0, 0, 0, 0)``, and the reset-state assertion in
        :meth:`_check_demote_registers` would fail for every member of this
        family. **So this family is Verilator-specific in that one respect, and
        porting it to a 4-state simulator requires resolving X explicitly rather
        than through ``rd()``.** The O4 member's evidence IS the sample count, so
        that member depends on this behaviour directly.
        """
        prev = None
        cycle = 0
        try:
            while True:
                await RisingEdge(dut.clk_i)
                cycle += _SAMPLE_EVERY
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

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        self._check_boot_chain_order(console)
        self._check_demotion_console(console)
        self._check_demote_registers()
        self._check_primary_served(flash)
        self._check_stimulus_served(flash)

    def _check_boot_chain_order(self, console: list[str]) -> None:
        """The boot chain must run in order, with the demotion block inside it.

        The reference enforces ORDER across its whole pattern list --
        ``find_pattern_sequence`` searches each entry from the previous match onward
        -- while the inherited ``required_markers`` loop only asks whether each string
        appears anywhere (``sep_rom_ot_dma_boot_test.py``). Without this the
        port would be weaker than the reference on exactly the axis the reference is
        strict about, so the chain is pinned here: the manifest is accepted, THEN the
        [C15] decision runs, THEN BL1 is copied and jumped to. That last edge matters
        for the demotion group specifically -- ``rom_main.c`` writes the register
        before ``rom_handoff_bl1``, so a run that handed off first and
        wrote afterwards would be a real ordering defect and is not observable any
        other way.
        """

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
            "CHK-BOOT-CHAIN-ORDER: MANIFEST_OK@%d -> [C15]@%d -> BL1_COPIED@%d -> BL1_JUMP=@%d",
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
        # The decision must follow the manifest it is taken from. rom_main.c reads
        # the manifest out of bl0_state, i.e. after rom_manifest_boot()
        # returned OK, so every demotion token sits after MANIFEST_OK.
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
        # The transition record is what turns "the register reads (1, 1)" into "BL0
        # WROTE it, and it was at its reset value before". Asserting it is what makes
        # the probe path itself load-bearing: a probe that resolved to a constant
        # would produce a final value that happened to match and no transitions at
        # all. Both fields reset to 0 (sep_lifecycle_ctrl.rdl:23-36), so the first
        # recorded sample must be the reset state and at least one change must follow.
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
        # The (0, 0) case is ALSO the reset value, so on its own a DEMOTE_2 probe
        # stuck at 0 would satisfy it vacuously. Two things stop that being a hole.
        # The state half is guarded -- an X- or 0-resolved rail pair is 0b00, which
        # _decode_demote() raises on rather than reading as demote 0. And the PROD_END
        # members require lock_2 == 1 through the same wiring, so the members of this
        # family jointly prove the DEMOTE_2 probe is live in both directions. No
        # member proves it alone.
        self.logger.info(
            "CHK-DEMOTE-REGISTERS PASS: DEMOTE_1 demote=%d lock=%d, DEMOTE_2 demote=%d "
            "lock=%d -- read from the lifecycle controller, matching the expected "
            "[C15] outcome",
            got_1[0],
            got_1[1],
            got_2[0],
            got_2[1],
        )

    def _check_primary_served(self, flash) -> None:
        """The demotion inputs live in the PRIMARY manifest, so the primary must boot.

        The backup carries different demotion inputs by construction, so a silent
        failover would measure a different row of the decision table under this
        testcase's name -- and it would still reach MANIFEST_OK and still print a
        valid-looking demotion verdict. The device record is the only channel that
        can exclude it.
        """
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
        """Require the DEVICE to have returned the demotion bytes this test planted.

        :meth:`check_manifest_stimulus` reads the mutated buffer -- an offline
        artefact -- so it proves what was STAGED, not what the DUT was given.
        Between the two sits the flash BFM and the whole SPI/DMA transport, and for
        the members of this family whose stimulus the ROM never echoes this is the
        only DUT-side evidence of it: an instrument that shares the DUT's assumption
        cannot falsify it.

        It matters most to the PROD_END members. At PROD_END the ROM reads none of
        the three inputs, so the console cannot separate one PROD_END row from
        another, and this check is the FIRST channel on which their stimuli differ
        observably at run time -- the served ``selector_bits`` word differs between
        ``no_flag_prod_end`` and ``no_flag_prod_end_sel_bit_set`` even though every
        console line is identical.

        Each field must be covered by a SINGLE read. The ROM currently fetches the
        whole 1184-byte manifest in one transaction, so all three are; if the
        transport ever splits a field across two reads this assertion fires and the
        fix is to stitch the reads, not to drop the check.
        """
        names = {
            mm.OFF_SELECTOR_BITS: "usage_constraints.selector_bits",
            mm.OFF_USAGE_FLAGS: "usage_constraints.flags",
            mm.OFF_FLAG_ARGS: "boot_arguments.flag_args",
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


def narrow_life_cycle_states(
    test, buf: bytearray, allowed: int, *, reseal_slots: tuple[str, ...]
) -> None:
    """Narrow BOTH slots' ``life_cycle_states`` to a single state, and say why.

    The shipped image permits TEST_DEV | PROD | PROD_END (0x7,
    ``configs/secure_boot_test.yaml:54``), so it boots under any of the
    three and the run's acceptance says nothing about which state the ROM decoded.
    The reference narrows it per lifecycle -- 0x2 for PROD and 0x4 for PROD_END,
    written to both slots -- and this port does the same. It is
    also a STRENGTHENING: ``selector_bits`` bit 16 is already set in the shipped
    image, so the ROM maps the live LC state to a bit and refuses the manifest with
    ``LC_USAGE_CONSTRAINT_FAIL`` if it is clear (``manifest_load.c``). The
    boot therefore cannot succeed unless the ROM decoded the lifecycle this testcase
    is named for.
    """
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
        mm.SHIPPED_LIFE_CYCLE_STATES,
        allowed,
        mm.SELECTOR_BIT_LIFE_CYCLE_STATES,
        ", ".join(reseal_slots) or "(none)",
    )
