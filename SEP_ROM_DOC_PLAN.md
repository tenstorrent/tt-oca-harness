# Review: `hw/sys/sep/bootrom/prod/doc/rom.adoc`

**Verdict: the content is strong — by a wide margin the best SEP boot ROM specification we
have — but it did not survive the transition intact, and its implementation-status claims are
now inverted for the single biggest item. It is not currently published, and should not be
published as-is.**

2848 lines, 98 headings, 640 table rows, requirement IDs (`SEP-ROM-*`), a security-check
inventory, a boot-stage-to-status-code traceability matrix, and a self-declared
implementation-status matrix. `cpu.adoc`'s BL0 section is ~120 lines by comparison. This
document is the real specification; `cpu.adoc` is a summary.

---

## A. It does not render at all

1. **Not included in `index.adoc`.** Every other SEP doc is; this one is not. 137 KB of
   specification invisible to the doc build.
2. **Two unresolvable includes**, both pointing at a `src/` tree that does not exist here:
   - line 2: `include::src/_templates/sep_rom_settings.adoc[]` — document settings/attributes
   - line 2397: `include::src/generated/status_values.adoc[]` — the **generated status-code
     registry**, i.e. the entire Code Registry section renders empty

The status-code table is generated from `status_values.tsv`. Either that generation step
comes across too, or the section needs a different source.

## B. Internal paths — violates the open-repo policy

8 references to `fw/sep/bootcode`, plus `fw/deps/`, `fw/smc/prod_rom/specification/`,
`meta/registers/`, `meta/status/`. The in-repo equivalents are `hw/sys/sep/bootrom/prod/src/`,
`hw/sys/sep/bootrom/prod/include/`, and the generated register headers. The "Sources of Truth"
section (line 89) is entirely internal paths and needs rewriting against this repo's layout.

Also stale: `tools/validators/oca/lib/` — the validation library moved out from under `tools/`
to `validators/oca/lib/`.

## C. Implementation status is inverted for the biggest item

The status matrix's first row reads:

> OCA CLASSIC manifest | *gap* | Code still parses legacy `"TBL1"` `manifest_t`; OCA validator
> library not yet integrated.

That is the **pre-migration** state. Of the 11 `IMPLEMENTATION GAP` admonitions, five are
closed by the work just completed (verified against the code, not assumed):

| Gap | Section | Status now |
|---|---|---|
| Legacy `TBL1` parsing; OCA library not integrated | line 1266 | **closed** |
| Legacy `public_key_sel` index encoding | line 1652 | **closed** — OCA bitmap in use |
| Decrypts before any payload hash; no `payload_hash_chain` | line 1942 | **closed** — ciphertext-first, then chain |
| Crypto stage outside the per-slot retry loop | line 2310 | **closed** — `oca_validate_manifest` is inside `try_manifest_slot`, per-slot WARN |
| Packer writes backup manifest at `0x81000` not `0x41000` | line 1160 | **closed** — configs pack at `0x41000`; backup rotation verified in sim |

Still open (verified still present):

- Peripheral/bus reset is a stub — `PERIPH_RST_TODO`, `rom_main.c:259`
- PMP fence policy and Smepmp binding/release — unimplemented
- Fuse-sense readiness ordering — only the PLL path polls `smc_fuse_sense_done`
- Demotion directive still read from legacy fields; `VALID` qualifier not preserved
- Gate-ledger self-check exists only on a branch

## D. Two technical errors — one security-relevant

**D1. The revocation bit mapping is wrong.** `tbl:revoke_map` claims:

| Doc says | Reality |
|---|---|
| `CHIPLET_PUBK_REVOKE` bit 6 → OCA bitmap bit 16 | bit 16 → bit 16 |
| `CHIPLET_PUBK_REVOKE` bit 7 → OCA bitmap bit 17 | bit 17 → bit 17 |

The RDL (`sep_efuse_map.rdl:727`), `periphs.adoc`, and the implementation all agree there is
**no offset**: `plat_get_root_key_revocation()` copies the 32-bit fuse straight into the
bitmap (`fuse_read_bytes(..., out, 4u)`), so select bit *N* and revoke bit *N* name one key.

This matters. Implementing to the doc produces exactly the select-vs-revoke numbering
disagreement where authorization passes, revocation inspects an unrelated bit, and **a revoked
key boots**. That is the bug class `test_otp_anchored_key_revocation_uses_the_same_slot_numbering`
exists to catch, and it was a real bug earlier in this integration.

**D2. Anti-rollback ordering is understated.** The doc says the security-version check "runs
*after* signature verification (it presumes an authenticated manifest)". It runs **before**
*and* again after — `oca_validator.c:389` then `:394` under `OCA_RECHECK_SECURITY_VERSION`.
Before, so a superseded manifest is rejected without spending the modexp; again after, so a
fault that skipped the first evaluation still has to defeat the second.

(`cpu.adoc` had the mirror-image error — "before, not after" — introduced in the spec pass
earlier today. Corrected.)

## E. OTP key slots under-described

The doc lists two fuse key slots (bits 16, 17), named `SEP_EFUSE_MAP_PUBLIC_KEY_0/1`. The
implementation resolves **five**, under the RDL's current names:

| Bit | Bank |
|---|---|
| 16, 17 | `CHIPLET_PUBK_HASH0` / `HASH1` |
| 20 | `SIP_PUBK_HASH0` |
| 22 | `SYS_PUBK_HASH` |
| 24 | `SIP_PUBK_HASH1` |

and explicitly refuses the PQC slots (18, 19, 21, 23, 25) as unsupported rather than
resolving them. `OCA_KEY_SLOT_MAX` is 25, with [31:26] reserved.

The ROM-key row is otherwise accurate, including its warning that the digests are test
placeholders that must be replaced before mask finalization — still true, and worth keeping
prominent.

## F. Overlap with `cpu.adoc`

Both now describe the BL0 boot flow. That is two copies of one thing and will drift. Options:

1. **`cpu.adoc` summarises and cross-references `rom.adoc`** (recommended) — keeps the
   chapter readable in the SEP book and puts the normative detail in one place.
2. Keep both independent — cheaper now, guaranteed drift later.

---

## Suggested remediation order

1. **Wire it in** — add to `index.adoc`; resolve or replace the two includes. Without this
   nothing else is visible. *(Also decide where the generated status-code table comes from.)*
2. **Fix D1** — the revocation mapping table. Security-relevant and a one-table fix.
3. **Fix D2 and E** — check order, and the five OTP slots with current bank names.
4. **Refresh the status matrix and the 11 gap admonitions** — five are closed; leaving them
   makes the document actively misleading about what is verified.
5. **Purge internal paths** and rewrite "Sources of Truth" against this repo.
6. **Resolve the `cpu.adoc` overlap.**

Items 1–3 are small and high value. Item 4 is the bulk of the work and is the one that decides
whether the document can be trusted.

---

## Status (2026-09-02): all six items closed

| # | Item | Outcome |
|---|---|---|
| 1 | Wire it in | **Done.** In `index.adoc`; `src/_templates/` include dropped, status-code include repointed to `gen/status_values.adoc` (generated in-repo by `gen_status_table.py`). |
| 2 | Fix D1 (revocation mapping) | **Done.** `tbl:revoke_map` is 1:1 with no offset, with a WARNING explaining why the property is security-relevant. |
| 3 | Fix D2 (check order) and E (OTP slots) | **Done.** Anti-rollback documented as before *and* after signature verification; five OTP banks under current RDL names. The `fig:key_select_revoke` diagram still carried both errors and was corrected in Phase 9. |
| 4 | Refresh matrix + gap admonitions | **Done in two halves.** Matrix in Phase 8; the admonitions were missed and closed in Phase 9 — five of them still described pre-migration behaviour the matrix already called *closed*. |
| 5 | Purge internal paths | **Done.** No `fw/sep/bootcode`, `fw/deps/`, `meta/` references remain. |
| 6 | Resolve `cpu.adoc` overlap | **Done, option 1.** `cpu.adoc` is an eight-bullet summary that names `rom.adoc` as normative and says outright that it is deliberately not a second description. |

Two defects this review did **not** catch, both found in Phase 9:

- **`tbl:manifest_fields` was stale from offset 200 onward**, the signed region included
  (`[0,3145)` for `[0,3172)`). Section E flagged the *TOC entry* table as recorded against an
  old submodule revision; the same was true of the manifest field table and went unremarked.
- **`<<tbl:sep_msg_codes>>` never resolved.** Section A got the include path fixed, but the
  generator emits that table without the anchor `rom.adoc` cross-references.

The lesson for the next pass: the mechanical checks (xref resolution, table cell alignment,
requirement-index completeness) are cheap, and each of them found something a careful read
had missed twice.

---

## Phase 10 (2026-09-03): mechanical-check pass over the Phase 9 tree

Ran the checks the Phase 9 note recommended, against the working tree (Phase 9 edits still
uncommitted on top of `d5af9dd3`). They found one more instance of the same staleness class.

| Check | Result |
|---|---|
| Requirement anchors vs. index | 94 defined, 94 indexed, 0 missing either way, 0 duplicates — the doc's "All 94" is correct |
| Table geometry (cells ÷ declared cols) | 32 tables, all exact |
| Xref resolution across the **whole TRM book** (162 files, 471 anchors) | one genuine break, fixed |
| `tbl:manifest_fields` vs. `src/oca/constants.py` | 40 rows, one wrong — fixed |
| `sec:entropy` prose vs. `sep_entropy.c`/`.h` | every register, symbol, phase and lock verified accurate |
| Generated status table vs. `status_values.h` | regenerates byte-identical; 150 codes matches the title |
| Internal-path policy | clean |
| `asciidoctor` render of the SEP book | no errors outside the Antora-only `partial$` register includes |

### What was wrong

**`manifest_security_control` (rom.adoc, offset 191).** The field was widened 1 → 2 bytes in
the same submodule uprev that moved every offset from 200 onward — there is a
`test_manifest_security_control_is_two_bytes` and a determinism-test comment recording the
widening. Phase 9 corrected the table *from offset 200 down* and stopped one row short, so
this row kept the pre-uprev width. It also listed two bits where the format defines six; the
validator honours four of them (bits 0, 1, 4, 5) and deliberately skips bits 2–3 because
verifier entries are deferred. Row now gives the u16 width and all four honoured bits.

**`<<drbg>>` in `memory_map.adoc`** never resolved — retargeted to
`drbg-deterministic-random-bit-generator`. With that, every xref in the TRM book resolves.
(An earlier check against the SEP chapter alone also flagged `<<use-cases>>` in
`introduction.adoc`; that one is a false positive — the anchor lives in `doc/trm/src/use_cases.adoc`
and resolves in the real book. Worth remembering: the SEP chapter's anchor set is *not* the
right scope for this check.)

**Two stale DV comments contradicting the new `sec:entropy` section.** The secure-boot test
and its testlist entry both still described the retired `+sep_crypto_edn_force` whole-chain
grant ("the boot flow does not bring up entropy_source/CSRNG/EDN", "the ROM has no CSRNG/EDN
code") while the arg they annotate is now `+esrc_noise_force`. The args were right and the
doc's status-matrix claim was true; only the comments lied. Both rewritten.

### Verified, not assumed

`SEP_ENTROPY_BRINGUP ?= 1` in `bootrom/prod/Makefile` — the entropy chain is on by default,
which is what makes the status-matrix row *closed* rather than *branch*. The bring-up is
reached from exactly the two callbacks the spec names (`oca_platform.c:135` signature verify,
`:209` payload decrypt). If that default ever flips to 0, the matrix row and SEP-ROM-ENT-010
both become wrong — worth a note in whatever removes the flag.

The remaining `+sep_crypto_edn_force` implementation in `tb/tb_top.sv` is now unreferenced by
any test. Left in place (removing TB capability is not a doc change) but it is dead and a
reasonable follow-up.

---

## Phase 11 (2026-09-03): review items 4, 5, 6

### Item 4 — the ten rows marked *closed*

All ten re-verified against the code. **Nine hold exactly as written. One overclaimed.**

| Row | Verdict | Evidence |
|---|---|---|
| OCA CLASSIC manifest | holds | no `TBL1` in `src/` or `include/`; `manifest.h` deleted |
| Key selection encoding | holds | `plat_is_key_authorized` walks the 128-bit bitmap, refuses ambiguous/empty/reserved; `revocation.c:52` unions manifest ∪ device |
| Root key authorization | holds | first of the four checks in `oca_validator.c:385`, before any public-key op |
| **Fuse-key digest addresses** | holds | generated symbols in a switch; the code even records the old `+0x100/+0x120` bug and where it landed |
| Anti-rollback scheme | holds | `oca_validator.c:389` then `:394`; `OCA_RECHECK_SECURITY_VERSION` defaults to 1 |
| **Payload check order** | holds | `check_encrypted_payload` numbers the steps 1/2/3: hash ciphertext → decrypt → validate plaintext; cleartext path converges on the same `check_plaintext_payload` |
| Payload cipher AES-256-CBC | holds | `oca_platform.c:214`; `sep_rom_oca_encrypted_boot_test` in the testlist |
| **Retry scope** | holds | `try_manifest_slot()` contains `oca_validate_manifest` (:193) and `oca_check_payload_at` (:260); failure `continue`s to the next slot, WARN per slot, ERROR only after all slots |
| Packer backup-manifest offset | holds | `pack_images_constants.py` → `0x41000`; `test_packing.py:499` asserts it against the old `0x81000` |
| Crypto block reset release | **overclaimed → narrowed** | see below |

**The one overclaim.** The row said "Each crypto block is released from
`SEP_RESET_CTRL.SW_RESET_N` before first use." Only OTBN and AES are: `hmac_sha256.c` never
writes the register. It works because `HMAC_SW_RST_N` resets to 1 (released) — but that is a
different claim, and "each block is released" would send someone looking for a release call
that does not exist. Row now states which blocks are explicitly released and that HMAC relies
on the reset default.

### Item 5 — `tt-boot-manifest` TOC entry layout

**Genuinely closed; the *closed* marking is correct.** Producer (`src/oca/constants.py`) and
validator (`validators/oca/lib/oca_layout.h`) agree field for field, and both agree with
`tbl:toc_entry`: entry 276 B with `hash` at 80 (not the old 44), header 32 B, all thirteen
rows summing exactly to 276. The specific old concerns are all resolved — per-entry TOC hashes
*are* verified (`OCA_FAIL_PAYLOAD_ENTRY_HASH`), and the chain iterates **stored entry order**
(`pt + HEADER + i*ENTRY_SIZE`), not ascending offset, matching PL-030 step 3.

### Item 6 — personal-branch references: replaced

Decision: **drop the branch names, keep the facts.** A published spec should say *whether*
something is on `main`, not whose branch it is on — the branch name is the part that rots, and
it is the same class of problem as an internal path. Commit `3de14630f` is kept: it names no
person and survives a rename. Two status values became *unmerged* (from *branch* and
*implemented on branch*). If you want a durable forward pointer, an issue number is the right
one — say the word and I will swap them in.

### What items 4–6 turned up on the way

The register- and offset-sweeps written for this pass found more than the three items did:

- **The whole fuse table was shifted +4.** All eight addresses after `LOCKS` were one 4-byte
  slot low, so the documented `BL1_VERSION` address (`0x10930088`) was in fact
  `CHIPLET_PUBK_REVOKE`'s real address, and so on down the table. Implementing to the doc
  reads the neighbouring fuse — the same failure shape as the D1 revocation-mapping bug, and
  it had survived every review so far because nobody diffs addresses by hand.

  *Cause and provenance.* Inserting `LOCKS_SPARE` (32-bit `@0x8`) into `sep_efuse_map.rdl`
  pushed everything after `LOCKS` down by 4; the table predates that. Verified against the
  RDL instantiation block itself (`sep_efuse_map.rdl:1049-1086`), not only the generated
  header. Three independent sources agree: the RDL, `regs/gen/c/sep_addr.h`, and the ROM's own
  postmortem comment — `oca_platform.c` records that the retired
  `CHIPLET_PUBK_REVOKE + 0x100/+0x120` arithmetic landed on `SPI_PHY_DLL_SLAVE` and 16 bytes
  into `CHIPLET_PUBK_HASH0`, which resolves correctly only if the revoke bank is at `0x88`
  (`0x88+0x100 = 0x188` = `SPI_PHY_DLL_SLAVE`; `0x88+0x120 = 0x1A8` = `0x198+0x10`). Under the
  current map the doc's old `0x10930194` is `SPI_RB_VALID_TIME`. Note that `periphs.adoc`
  describes the map by *slot number* and carries no addresses, so it was never a check on
  this.
- **The same table still listed `PUBLIC_KEY_0`/`PUBLIC_KEY_1`** at the pre-uprev addresses.
  Those names now exist only in a stale VP dependency copy. Replaced with the five current
  banks. Section E of the original review fixed `tbl:key_slots` and the diagram; this table
  was the third place and was missed.
- **Four inline manifest offsets** were still pre-uprev — `payload_hash` 2748→2775 and
  `payload_hash_chain` 2820→2847 *inside SEP-ROM-PL-030*, plus `unauthenticated_flags`
  3729→3756 and `encryption_iv` 234→235. Phase 9 corrected the field table; the prose citing
  the same fields was not swept.
- **The security-check inventory had D2 a third time** — "Anti-rollback … *After* signature",
  contradicting SB-070, the flow diagram, the status matrix and the code. Also "8 slots"
  (pre-dates the five OTP banks) and a dead `MANIFEST_ERR_KEY_HASH_MISMATCH`.
- **Five dead `MANIFEST_ERR_*` codes** retired to the `OCA_FAIL_*` / `OCA_BOOT_ERR_*` families
  the code actually defines.
- `tbl:key_slots` now records that ROM bits 6–7 exist but are unprovisioned, and that an
  unprovisioned slot authorizes nothing — a deliberate difference from the old ROM that the
  code calls out and the spec did not.

The pattern across Phases 9–11 is one thing: **the uprev moved numbers, and each pass fixed
the numbers it happened to be looking at.** Tables, then prose, then register addresses. The
sweeps are kept in `hw/sys/sep/doc/checks/` (untracked; see its README) — each found something.
A doc-CI job that checks offsets and addresses against the generated headers would have caught
all of it the day the submodule moved.
