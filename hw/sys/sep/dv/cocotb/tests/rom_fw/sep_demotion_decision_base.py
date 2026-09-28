# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the BL0 demotion-decision testcases ([S25]).

Every member boots to completion and they differ only in the demotion inputs and
the verdict those inputs must produce, so the register observation, the ordering
chain and the scope disclosures live here once. Eight members inherit this file
through ``sep_demotion_prod_base`` (PROD, secure boot disabled) and
``sep_demotion_prod_end_base``, covering six of the seven outcomes below; O3b has
no member.

============================================================================
THE DECISION
============================================================================

``rom_main.c`` ``[S25]`` reads four inputs, three of them bits of one signed
manifest field:

  ========================================  ==================
  input                                     source
  ========================================  ==================
  ``lc_state``                              eFuse LC_STATE
  ``demotion_control`` BL1_DEMOTION_VALID   manifest
  ``demotion_control`` BL1_DEMOTION_ENABLE  manifest
  ``demotion_control`` BL2 request          manifest
  ========================================  ==================

``demotion_control`` is a u16 at manifest offset 172, inside the signed region.
Bits 0..3 are BL1_DEMOTION_VALID, BL1_DEMOTION_ENABLE, BL2_DEMOTION_VALID and
BL2_DEMOTION_ENABLE (``oca_layout.h``; ``oca_boot.h``'s ``OCA_DEMOTE_*`` mirror
them). The BL2 *request* is the conjunction of its pair -- a lone ENABLE is not a
request.

**At PROD_END the manifest is not read at all.** ``rom_main.c`` short-circuits on
``lc_state == LC_STATE_PROD_END`` and returns from the block before fetching
``demotion_control``, so every value of the field produces one outcome. Any
number of PROD_END members are stimuli on that single observable, not separate
coverage points.

``sel`` = BL1_DEMOTION_VALID, ``auth`` = BL1_DEMOTION_ENABLE, ``bl2`` = the BL2
request. Register columns are ``(demote, lock)``, the same form as
``expect_demote_1`` / ``expect_demote_2``; ``(0, 0)`` means never written.

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

**Three notations are in play and two of them collide.** This table and the
assertions use ``(demote, lock)``. The ROM composes the register WORD as
``{lock[1], demote[0]}`` (``bootrom/prod/src/lifecycle.c``), so O2a's word is
``0x3``. The DUT rail pair is ``{~demote, demote}``, so O2a's
``lcc_demote_state_1_probe_o`` is ``0b01``. The collision to watch: the word
``0b10`` means "no demote, locked", while the rail ``0b11`` is a broken rail that
:func:`_decode_demote` raises on. Tabulating the word where a rail is meant, or
the reverse, produces a plausible-looking wrong expectation.

============================================================================
WHY THE REGISTERS ARE PROBED
============================================================================

**The console cannot check this feature.** Every demotion string is printed from
a local computed one line earlier -- ``BL1_DEMOTE=`` from ``demotion_reg``,
``DEMOTE_LOCKED`` / ``DEMOTE_NOT_LOCKED`` from ``lock_demotion`` -- so a ROM that
decided correctly, printed correctly, then wrote the wrong value to the wrong
register passes a console-only test. An instrument that shares the DUT's
assumption cannot falsify it.

An external AXI read-back is not a substitute either: ``rtl/sep.sv`` passes
``.inbound_filter_skip_i (feat_ctrl.sep_debug)`` and ``sep_debug`` is 0 under
PROD_END, so such an access must clear the inbound filter. The probes are
``lcc_demote_state_{1,2}_probe_o``, the DUT outputs brought out unchanged, and
``lcc_demote_lock_{1,2}_probe_o``, read-only XMRs of ``demote_reg_{1,2}.lock``
(``rtl/sep_lifecycle_ctrl.sv``) -- the LOCK bit is on no port. No force, no
deposit.

``state`` is differentially encoded ``{~demote, demote}``
(``ocah_prim/rtl/prim_diff_encode_multi.sv``), so bit 0 is the demote bit and
``2'b00`` / ``2'b11`` are broken rails rather than verdicts.

**An end-of-run read is sound because neither field can be walked back.** Both
are write-one-to-set and are never cleared by hardware
(``sep_lifecycle_ctrl.rdl``), so the value observed is what BL0 wrote, and "never
written" is observable as ``lock == 0`` rather than being indistinguishable from
"written with zeros". This matters because the runs do not stop at hand-off:
``bl1_pass_test`` executes to completion, so the registers are read after BL1 has
run.

**O4 is the exception and needs an exact transition count.** It is the only
outcome with ``lock == 0``, and ``sep_lifecycle_ctrl.sv`` derives the software
write-enable as ``~lock``, so on O4 the register stays writeable by later
software. Its member declares ``demote_changes_min`` / ``demote_changes_max`` as
``(1, 1)`` -- pinning the count across the whole simulation including BL1 --
where the default ``(2, None)`` suits every outcome that writes DEMOTE_1.

============================================================================
SCOPE
============================================================================

**These testcases cover the decision only.** BL0 has no key-manager driver on the
demotion path: ``rom_main.c`` stores ``bl2_demotion_decision`` into ``bl0_state``
for BL1 to consume and derives nothing from it, so there is no KBKDF salt or SKS
UID key to check here.

**There is no architected demotion status code.** ``status_values.h`` defines
none and the whole [S25] block contains no ``report_status`` call, so the
reference's ``STATUS: DEMOTION_SELECTED`` / ``_NOT_SELECTED`` / ``_LOCKED`` /
``_NOT_LOCKED`` strings have no counterpart. The register probes stand in for
them.

**The PROD_END members require both registers to read locked.** DEMOTE_1 and
DEMOTE_2 locked is the strongest discriminator those members have, and it is
derived from this ROM's own control flow.
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

# Every console string the [S25] block can emit (rom_main.c,
# :409). A member requires the ones its outcome produces and forbids
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
            f"(hw/common/ocah_prim/rtl/prim_diff_encode_multi.sv:41-49), so an equal "
            f"pair is a broken encoder rather than a demotion verdict"
        )
    return state & 0x1


class sep_demotion_decision_base(sep_rom_ot_dma_boot_test):
    """Boot to completion and check the [S25] demotion verdict on both channels."""

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
    # The default pair (2, None) is exactly the predicate
    # ``len(self._demote_changes) >= 2`` -- the assertion these two attributes
    # replace -- so every member that does not set them keeps the check unchanged.
    #
    # It is parameterised because O4 is a genuine exception rather than a defect:
    # ``rom_main.c`` clears ``lock_demotion``, so never runs, DEMOTE_1
    # is never written, both registers stay at their reset value and the monitor
    # records exactly ONE sample -- the reset sample itself. The O4 member sets
    # ``(1, 1)``, which is STRICTER than the default in the only direction O4 can
    # be strict: it pins the count exactly instead of leaving it open above.
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
        whole content is "the input is set and the ROM ignores it" needs its own
        per-run confirmation that the input really was set.
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
        # Whole fields, not prefixes: selector_bits is 16 bytes and reading 8 of
        # it would leave half the stimulus unwitnessed.
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
        which is the same idiom ``sep_firmware_mbist_pass_test._gate_monitor`` uses
        (,); without it an uncaught exception in a
        ``start_soon`` coroutine would surface as a failure of a testcase that had
        already done its job. That guard is load-bearing and does fire.

        **THE INNER ONE IS INERT UNDER VERILATOR, AND AN EARLIER VERSION OF THIS
        DOCSTRING CLAIMED OTHERWISE.** It was written to skip a sample that cannot
        be resolved, but :meth:`sep_base_test.rd` already swallows the exception and
        returns 0 (``tests/sep_base_test.py:70-76``), so ``_sample_demote`` never
        raises and this ``except`` cannot be reached. Under Verilator that is
        harmless: the model is 2-state, the differential encoder drives ``2'b10``
        from cycle 0, and every run to date records its first sample as the reset
        state. On a 4-state simulator it would NOT be harmless -- an X probe would
        resolve to 0, the first recorded sample would be ``(0, 0, 0, 0)``, and the
        reset-state assertion in :meth:`_check_demote_registers` would fail for
        every member of this family. **So this family is Verilator-specific in that
        one respect, and porting it to a 4-state simulator requires resolving X
        explicitly rather than through ``rd()``.** It is load-bearing for the O4
        member, whose evidence IS the sample count.
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

        The inherited ``required_markers`` loop only asks whether each string
        appears anywhere, so order is pinned here instead: the manifest is
        accepted, THEN the
        [S25] decision runs, THEN BL1 is copied and jumped to. That last edge matters
        for the demotion group specifically -- ``rom_main.c`` writes the register
        before ``rom_handoff_bl1``, so a run that handed off first and
        wrote afterwards would be a real ordering defect and is not currently
        observable any other way.
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
            f"boot chain out of order: MANIFEST_OK@{i_ok} -> last [S25] token"
            f"@{i_last_demote} -> BL1_COPIED@{i_copied} -> BL1_JUMP=@{i_jump}. The "
            f"demotion decision must sit between manifest acceptance and the BL1 "
            f"handoff (rom_main.c:349-353, :377-436, :444). Console: {console}"
        )
        self.logger.info(
            "CHK-BOOT-CHAIN-ORDER: MANIFEST_OK@%d -> [S25]@%d -> BL1_COPIED@%d -> BL1_JUMP=@%d",
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
                f"[S25] token {token!r} appeared {len(hits)} times at {hits}, "
                f"expected exactly 1. The demotion block runs once per boot "
                f"(rom_main.c:379-436), so any other count means it ran twice or not "
                f"at all. Console: {console}"
            )
        for token in forbidden:
            assert not any(token in line for line in console), (
                f"[S25] token {token!r} must not appear: it belongs to a different "
                f"row of the demotion decision table than the one this testcase "
                f"drives. Console: {console}"
            )
        for valued in self.demotion_values:
            hits = [i for i, line in enumerate(console) if valued in line]
            assert len(hits) == 1, (
                f"[S25] {valued!r} appeared {len(hits)} times at {hits}, expected "
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
                f"[S25] token {token!r} appeared at line {i_tok}, before MANIFEST_OK "
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
            f"value. Every outcome of the [S25] block except O4 writes DEMOTE_1, so no "
            f"transition means BL0 did not reach rom_main.c:432. O4 is the one member "
            f"entitled to a single sample and it declares demote_changes_min = 1"
        )
        assert self.demote_changes_max is None or n_changes <= self.demote_changes_max, (
            f"{n_changes} DEMOTE sample(s) recorded, expected at most "
            f"{self.demote_changes_max}. A member that pins the count exactly is "
            f"asserting that the registers moved that many times and no more; an extra "
            f"transition means something other than the single [S25] write reached the "
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
        # Honest note on the (0, 0) case: it is ALSO the reset value, so on its own a
        # DEMOTE_2 probe stuck at 0 would satisfy it vacuously. Two things stop that
        # being a hole. The state half is guarded -- an X- or 0-resolved rail pair is
        # 0b00, which _decode_demote() raises on rather than reading as demote 0. And
        # the PROD_END member requires lock_2 == 1 through the same wiring, so the two
        # members of this family jointly prove the DEMOTE_2 probe is live in both
        # directions. Neither member proves it alone.
        self.logger.info(
            "CHK-DEMOTE-REGISTERS PASS: DEMOTE_1 demote=%d lock=%d, DEMOTE_2 demote=%d "
            "lock=%d -- read from the lifecycle controller, matching the expected "
            "[S25] outcome",
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
        Between the two sits the flash BFM and the whole SPI/DMA transport, so for
        a member whose stimulus the ROM never echoes this is the only DUT-side
        evidence that the bytes arrived.

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
    """Constrain BOTH slots to a single chiplet lifecycle state, and say why.

    The packed image selects no usage constraints at all, so it boots under any
    lifecycle and the run's acceptance says nothing about which state the ROM
    decoded. Selecting the chiplet lifecycle and narrowing it to one state makes
    the boot itself the evidence: with the selector bit set the ROM maps the live
    LC state to a bit and refuses the manifest when it is clear, so the run cannot
    succeed unless the ROM decoded the lifecycle this testcase is named for.

    The CHIPLET scope only. SEP provisions no package or system lifecycle --
    ``plat_get_lifecycle_state`` reports ``OCA_HW_UNAVAILABLE`` for both -- and a
    selected constraint the device cannot evaluate fails the slot
    (SEP-ROM-MAN-040), so selecting either would refuse the manifest for a reason
    that has nothing to do with demotion.
    """
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
        for scope in ("package", "system"):
            other = mm.SELECTOR_BIT_LIFECYCLE[scope]
            assert not sel & (1 << other), (
                f"{slot} selects the {scope} lifecycle (selector bit {other}), which "
                f"SEP cannot report: the slot would be refused under SEP-ROM-MAN-040 "
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
