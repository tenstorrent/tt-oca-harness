## Summary

Adopters integrating the harness into their own SoC need fuses of their own. This proposes a
supported, sized adopter fuse region in the SMC. The harness senses it, shadows it, locks it and
exports it, without interpreting its contents and without RTL changes per adopter. Harness spares
stay reserved for the harness. The SEP has no adopter region and is unchanged apart from the SHIM
handshake (section 4).

The scope is a small set of fuses that adopter logic needs continuously, such as memory repair
entries and sensor trims. Bulk data that needs streaming rather than shadowing is a follow-up.

## 1. Adopter contract

The adopter describes its region to the harness with three `CFG` fields and nothing else. The
harness RTL needs only the region's size, its place in `smc_external` and where each lock region
ends; it never needs adopter field names, so no generated package, typedef or register flow is part
of the contract.

Required:

- Set the three `CFG` fields (section 2).
- Connect `smc_adopter_shadow_regs_o`, a plain array of 32-bit words (section 5).

Recommended, not required:

- Describe the payload in `smc_adopter_fuse_map.rdl`. The shadow file is visible to software in
  `smc_external`, so an RDL gives the adopter, from one file, C headers for its firmware, register
  documentation for its own manuals, and an SV struct to cast the export to.
- The harness ships an example map, `smc_adopter_fuse_map.rdl` next to this proposal (512 bytes of
  memory repair entries, sensor trims and adopter spares in 32 lock regions), and an optional script
  that derives the `CFG` values from an adopter RDL or checks them against it.

An adopter with a handful of trim words can therefore set three fields and connect one port.

## 2. Parameters

Add three fields to `smu_pkg` `CFG`, alongside the existing `SMC_EFUSE_SHIM_SIZE`:

```systemverilog
int unsigned       SMC_ADOPTER_FUSE_BASE;        // byte offset of the window in smc_external
int unsigned       SMC_ADOPTER_FUSE_WORDS;       // 32-bit words in the region; 0 = no region
logic [31:0][15:0] SMC_ADOPTER_LOCK_REGION_END;  // word one past the end of region n; 0 = unused
```

- Region _n_ covers words `[END[n-1], END[n])`, with `END[-1] = 0`. Because each region starts
  where the previous one ends, the regions tile the map by construction and a gap cannot be
  expressed.
- Static checks in `smu.sv`, in the style of the existing SHIM size check:
  - the window fits inside `smc_external` and does not overlap the SHIM control block;
  - the window base is aligned to its size rounded up to a power of two (section 8);
  - the used entries are non-zero and strictly increasing, every later entry is zero, and the last
    used entry equals `SMC_ADOPTER_FUSE_WORDS`;
  - with `SMC_ADOPTER_FUSE_WORDS = 0`, every entry is zero.
- The default configuration sets all three to zero: no adopter region.
- Example, for the example map: `SMC_ADOPTER_FUSE_WORDS = 128` and ends `4, 8, … 64` for the 16
  repair entries, `68, … 96` for the 8 trims, `100, … 128` for the 8 spares.
- Keep two address spaces distinct:
  - **Software window:** where the adopter map appears in `smc_external`, at
    `SMC_ADOPTER_FUSE_BASE`, `4 * SMC_ADOPTER_FUSE_WORDS` bytes long.
  - **Fuse bit address:** where the adopter bits sit in the OTP. Fixed to start at the end of the
    SMC harness's 8 Kbit, so harness fuse addresses never move because of adopter size. Only the
    size varies.

## 3. Sensing and the shadow file

- Sensing fills the SMC harness shadow file, then a second, adopter shadow file, through the same
  SHIM.
- The harness sees one linear fuse address space, and the adopter's SHIM maps addresses to macros.
- Because `ADOPTER_LOCKS` sits in the harness map, the adopter's locks are sensed before any adopter
  payload word arrives.
- **Fuse sense done means every region is sensed.** `fuse_sense_done` (and so
  `smc_fuse_sense_done_o`, the `efuse_sense_done` status bit and the fuse-released SMC reset) asserts
  only once both the harness and the adopter regions are in their shadow files. The SEP's sense and
  its secure-test-mode latch are unaffected.
- An adopter-done signal can remain for observability and for qualifying the boundary export, but
  the boot flow depends only on the combined done.
- Implementation: reuse `efuse_shadow_regs` as a second instance for the adopter file, rather than
  one FSM writing both files.
  - Add a start-address parameter (default 0) and a sense-start input (tied high for the harness
    instance). The adopter instance starts when the harness instance finishes and reads from fuse
    bit address 8192. `.address` is a bit address, not a word index.
  - Add an optional external lock-vector input (off by default). The harness instance keeps taking
    its lock vector from its own first shadow words; the adopter instance takes it from
    `ADOPTER_LOCKS` in the harness shadow file. Its field map is the region table the harness
    builds from `SMC_ADOPTER_LOCK_REGION_END` (section 7).
  - Add a lock-vector width parameter. Access control sizes its lock input as
    `2 * (EFUSE_FIELDS - 1)`, which assumes one field is the `LOCKS` meta-field; the adopter
    instance has no meta-field and takes all 64 bits of `ADOPTER_LOCKS`.
  - The shadow map type is already a parameter (`efuse_map_t`). The adopter instance passes
    `logic [SMC_ADOPTER_FUSE_WORDS-1:0][31:0]`, so it needs no struct and no flat-output mode.
  - The sense is one READ whose length is the shadow word count, so the adopter word count needs no
    rounding; the access-length type only has to hold it (section 5).
  - Make the preload plusarg name a parameter. Both SMC instances have `HAS_LC_STATE = 0`, so today
    they would load the same `smc_shadow_reg_preload` file.
  - The controller's command mux keeps the SHIM in sense mode until the adopter instance is done.
  - The harness instance's module code, hierarchy and signal names are unchanged, so testbench taps,
    FSM exclusions, lint waivers and scan-protection naming keep matching. A single FSM would
    rewrite exactly the lines those artifacts are keyed on.
- The adopter instance is reset by the controller's `rst_ni`, never by the fuse-released
  `reset_n_o`, or it would wait on itself.
- An empty adopter region must elaborate away cleanly (a packed array cannot have zero elements).
  The adopter instance sits in a `generate` on `SMC_ADOPTER_FUSE_WORDS > 0`, so that combined done
  equals harness done exactly when there is no adopter region.

### Boot-flow races this avoids

If done meant "harness region only", the fuse-released reset would let the SMC CPU and the
controller's read and program interfaces run while the adopter READ is still streaming:

- **Firmware can take the SHIM mid-stream.** The mux hands the SHIM to a firmware read or program
  once done is high, and routes responses by its current selection. Adopter words would land in the
  firmware's read interface, the adopter shadow would never reach its word count, and adopter done
  would never assert. Giving adopter sensing priority instead leaves the firmware request hanging or
  timing out.
- **Firmware sees bus errors.** Until its own sense completes, the shadow module answers APB accesses
  with `pslverr` and `0xBADCAB1E`, so early firmware reading adopter fuses would fault.
- **Adopter hardware captures zeros.** Logic released by the same reset would sample its
  configuration before the adopter shadow is filled.

## 4. SHIM command handshake (ready/valid)

Today the command interface has no acknowledgement. The SHIM accepts a command whenever it is idle
and `valid` is high, and every requester (sense, read, program) holds `valid` high until its
response returns. Correctness depends on the controller deselecting the request before the SHIM
returns to idle. With the reference SHIM those two events coincide with zero cycles of margin; a
SHIM without a finish state would accept the sense READ a second time, its responses would go to
whichever path the mux has switched to, and the load path can overwrite the last shadow word. The
adopter region adds a second sense command, and so a second handoff of this kind.

Proposal: the SHIM drives a `ready` signal.

- A command transfers on a cycle where `valid` and `ready` are both high. The requester holds the
  request stable while `valid && !ready`, and drops `valid` after the transfer with no consequence.
- Responses are unchanged: a valid-only stream with no backpressure. The controller always accepts
  them.
- The controller counts outstanding responses per command (the access length for a sense, one for a
  read or program) and switches the mux only when none are outstanding.
- For most SHIMs `ready` is "my command FSM is idle", which is one line. A SHIM must not tie `ready`
  high unless it can genuinely accept a command in any state.
- Carry `ready` either as a field of the response struct (`EFUSE_COMMAND_RESP_T`), which adds no
  boundary port but changes the packed layout, or as a separate `efuse_shim_command_ready_i` port,
  which leaves the struct alone. The separate port is easier for DV monitors and BFMs that unpack the
  struct.
- The SMC and SEP share the controller IP, so the handshake applies to both SHIMs and is one contract
  for every adopter, not only those using adopter fuses. Update the reference SHIM
  (`efuse_interface_shim.sv`), the integrator guide's SHIM contract and figure, and the DV components
  that drive or watch SHIM responses directly (for example the SEP eFuse SHIM fault-injection tests
  and the SMU sense probe). The existing sense-sequence checks count read command pulses, which stays
  at one per command.

## 5. Boundary export

- Export the adopter shadow file at `smu.sv` as `smc_adopter_shadow_regs_o`, a plain word array
  whose width follows `CFG`:

  ```systemverilog
  localparam int unsigned SmcAdopterPortWords =
      (CFG.SMC_ADOPTER_FUSE_WORDS > 0) ? CFG.SMC_ADOPTER_FUSE_WORDS : 1;
  output logic [SmcAdopterPortWords-1:0][31:0] smc_adopter_shadow_regs_o,
  ```

  A port width may depend on a module parameter, so no package typedef is involved. With no adopter
  region the port is one word tied to zero. The adopter uses word indices directly, or casts the
  array to a struct generated from its own RDL.
- Widen the fuse bit-address and access-length types in `smc_efuse_pkg` (today fixed at 8 Kbit: a
  13-bit bit address and a 9-bit word counter) to a fixed ceiling, with `SMC_ADOPTER_FUSE_WORDS`
  bounding what is actually used and a static check rejecting a size above the ceiling. Package
  typedefs cannot follow a `CFG` value. `sep_efuse_pkg` is unchanged.
  - Cost: the SMC command structs change width in every build, including builds with no adopter
    region, so the reference SHIM, the SMC and SMU DV components that pack or unpack those structs,
    and any adopter SHIM follow the wider layout.
  - The 16-bit region-end entries allow 65535 words (about 2 Mbit); the ceiling is chosen with them
    (see open questions).

## 6. Fabric routing

- Place the adopter fuse window directly after the eFuse SHIM control block at the base of
  `smc_external`.
- Extend the existing diversion from SHIM size to SHIM size plus adopter size, so software accesses to
  adopter fuses enter the eFuse controller. They then go through its lock and lifecycle checks instead
  of leaving on `smc_external_req_o`.

## 7. Hardware locks for the adopter region

The adopter region's locks live in the SMC harness fuse map, `smc_efuse_map.rdl`, next to the
harness's own locks. The adopter region is pure payload.

- Rename `LOCKS` to `HARNESS_LOCKS`. Its layout and behaviour are unchanged: 32 write/read pairs for
  the harness fields, read by hardware from the first shadow words.
- Add `ADOPTER_LOCKS`, a 64-bit register of 32 write/read pairs, with the write lock at bit 2n and the
  read lock at bit 2n+1. Pair n governs adopter lock region n.
- Both lock registers are hardware-consumed, so they sit together at the top of the map, and both are
  treated as lock meta-fields: never lock-checked themselves, set-only in the shadow (write-1-to-set),
  and kept in Class 1 storage so scan cannot clear them. `Class1ShadowRanges` grows to cover words
  0–3.
- The map must still tile the 8 Kbit bank without gaps, and all 32 `HARNESS_LOCKS` slots are already
  assigned. `ADOPTER_LOCKS` takes 8 bytes from the spare area:

  | Offset | Register | Change |
  |---|---|---|
  | `0x000` | `HARNESS_LOCKS` | renamed from `LOCKS` |
  | `0x008` | `ADOPTER_LOCKS` | new |
  | `0x010` | `JTAG_PUBLIC_IDENTITY` | was `0x008` |
  | `0x030` | `I2C_I3C_ID[9]` | was `0x028` |
  | `0x078` | `SMC_CONFIG` | was `0x070` |
  | `0x080` | `OCCP_TRANSPORT_TIMEOUT` | was `0x078` |
  | `0x088` | `SPARE[27]` (256-bit) | was `SPARE[28]` at `0x080` |
  | `0x3E8` | `SPARE_TAIL[3]` (64-bit) | new; takes lock slot 31, formerly `SPARE[27]` |

  A trial compile of this layout fills exactly 1024 bytes. The harness loses 64 spare bits, and the
  last lock slot governs 192 bits instead of 256.
- Example `ADOPTER_LOCKS` definition, in the style of the existing map:

  ```systemrdl
  field adopter_lock_f {
      sw = rw;
      onwrite = woset;
      hw = r;
      desc = "When set, the governed adopter lock region is locked for this access type, in both
              the fuses and the shadow copy.";
  };

  reg ADOPTER_LOCKS {
      desc = "Lock controls for the adopter fuse payload in smc_adopter_fuse_map. Pair n governs the
              n-th lock region of that map.";
      regwidth = 64;

      adopter_lock_f region0_write_lock[0:0] = 0x0;
      adopter_lock_f region0_read_lock[1:1] = 0x0;
      // ... one pair per region ...
      adopter_lock_f region31_write_lock[62:62] = 0x0;
      adopter_lock_f region31_read_lock[63:63] = 0x0;
  };
  ```

- Lock pairs align with the regions the adopter defines in `SMC_ADOPTER_LOCK_REGION_END`, up to a
  hard limit of 32. Pairs beyond the last used entry are unused. An adopter that uses the example
  RDL convention makes each top-level register instance (each array element separately, a `regfile`
  as one) a region, and the optional script derives the ends that way; the hardware sees only the
  ends.
- An elaboration-time function in `smc_efuse_pkg` builds the region table from the ends as
  `rule_t` entries, the same form as the harness field map, with byte ranges
  `[4 * END[n-1], 4 * END[n] - 1]` and no static bits. The adopter shadow instance and the guard use
  the existing range lookup with this second table, so no new lock-lookup logic is needed. Every
  comparison is against a constant.
- The `CFG` encoding cannot express a gap, and the static checks reject more than 32 regions by
  construction. This matters because an address outside every range falls to the guard's unmapped
  index, which is never locked, so a gap would be a fuse anyone could burn. The harness map follows
  the same no-gap rule.
- Lock pair n keeps its meaning only while region n does. Appending a region leaves earlier pairs
  unchanged; inserting or removing one renumbers every later pair. Once parts carry burned
  `ADOPTER_LOCKS` bits, the adopter may grow the region only by appending ends.
- Cost: each lookup is up to 32 address-range comparisons, at the adopter access control and at the
  guard's read and program checks. The harness already pays this for its own fields; the adopter
  ranges are wider.
- Hardware and software locks both work as today: burning an `ADOPTER_LOCKS` fuse is a permanent
  hardware lock, and writing the shadow copy (write-1-to-set) is a software lock until reset.

### Cost of putting the locks in the harness map

- Unlike the earlier per-region wrapper, this changes the SMC harness map for every build, including
  builds with no adopter fuses. The default build is no longer bit-identical for the SMC.
- Renaming `LOCKS` changes the generated names (`SMC_TOP_SMC_EFUSE_MAP_LOCKS_*`,
  `smc_efuse_map_locks_reg_t`, `SMC_EFUSE_MAP__LOCKS__*`). About 27 hand-written files use them,
  mostly SMC cocotb sequences and tests, plus `smc_efuse_pkg`, SMC DV docs and testlists.
- Shifting every field after `ADOPTER_LOCKS` by 8 bytes invalidates hard-coded offsets and SMC shadow
  preload images. Firmware that uses the generated macros follows automatically.
- The SEP map, its DV and its waivers are untouched.

### Static policy: none

Each harness rule also carries static bits (set-only write, write lock, secure-test write lock) that
govern software writes to the shadow copy only; fuse programming is checked against the dynamic lock
bits alone. The adopter lock regions use no static policy.

- Every region is write-unlocked, read-unlocked and has no secure-test lock. This matches most
  harness fields. The region table could carry static bits later, through another `CFG` field, if a
  use case needs them.
- Unlocked regions let firmware override the shadow, which the adopter's hardware sees immediately,
  until reset. This is intended for the target use cases: soft memory repair during bring-up and
  test, and trial sensor trims before burning.
- The 32 dynamic write/read lock pairs in `ADOPTER_LOCKS` are the only protection, set by firmware
  (until reset) or burned (permanent). They stay; dropping them would leave nothing to stop firmware
  burning the adopter region in the field.

Risks and the contract rules that cover them:

- **Protection depends on someone setting the locks.** Until a region's write lock is set, burned in
  the fuses (permanent) or set in the shadow copy (until reset), anything that reaches the adopter
  window can override the region's shadow words, and anything that reaches the eFuse control
  registers can program extra 1s into its fuses, which is permanent. Extra bits in repair data
  break repair; a bad trim mis-calibrates a sensor. Burning a region's write lock at manufacture
  protects it with no firmware involvement. For regions whose locks are not burned, the harness ROM
  does not know the adopter's regions, so the adopter's firmware must set their shadow locks early
  in boot, and the adopter documents which regions those are.
- **No secrets in the adopter region.** Without a secure-test lock, secret ranges or Class 1
  storage, adopter words get normal scan handling. Repair and trim data are fine. Adopter secrets
  belong in the SEP, which this proposal does not extend.
- **Reachability of the window.** If agents outside the SMC can reach the adopter window through the
  chiplet aperture, they can override unlocked regions. Confirm the inbound filtering (see open
  questions).

## 8. Access control: the adopter shadow behind the JTAG mux

The adopter shadow file sits on the same access path as the harness shadow file. Figure:
`efuse_adopter_interface.svg`, a copy of the controller figure in
`hw/sys/sep/doc/assets/sep-efuse-interface.svg` with the adopter instance added and numbered impact
notes.

Path for both the functional port (firmware, through the `smc_external` diversion) and the OTP JTAG
port: JTAG lifecycle filter (JTAG only), then functional/JTAG AXI-Lite mux, address decode, AXI-Lite
to APB bridge, APB demux, then the per-instance access control. Placing the adopter instance there
has these consequences.

- **Lifecycle policy comes for free.** In PROD, RMA_SiP or on a lifecycle integrity error,
  `smc_efuse_wrapper` answers every JTAG access with an error except reads of
  `JTAG_PUBLIC_IDENTITY`, so JTAG cannot read, override or program adopter fuses in the field. In
  other lifecycle states JTAG has full access, which is the path ATE uses to write and burn repair
  data before any firmware exists. The filter takes `JTAG_PUBLIC_IDENTITY`'s address from the
  generated address package, so the 8-byte shift in section 7 follows automatically. Adopter fuses
  follow the same JTAG policy as every other fuse: the filter gains no adopter-specific range, and
  `JTAG_PUBLIC_IDENTITY` stays the only JTAG-readable fuse in PROD and RMA_SiP.
- **Lock writes and accesses cannot race.** `ADOPTER_LOCKS` is written through the harness MAP
  window; the adopter window is checked against it. Both windows sit behind one single-outstanding
  APB bridge, so a lock write completes before the next adopter-window access from either port.
- **Address decode.** The controller sends `[MAP base, CTRL end]` (MMR end in the SEP) to the
  interface path and everything else to the SHIM bank control port. The adopter window lives in
  `smc_external`, not next to the MAP and CTRL windows, so the decode needs a second interface range,
  enabled only when the adopter size is non-zero. Without it, adopter accesses fall through to the
  SHIM port.
- **APB demux.** A fifth target (adopter shadow) widens `efuse_reg_map_e` in the shared `efuse_pkg`
  from 2 to 3 bits; it is full today with MAP, CTRL, MMR and the error target. The SEP, and an SMC
  without adopter fuses, answer the new target with SLVERR in the same way the SMC answers MMR today.
- **Window alignment.** The shadow module indexes by the low address bits, so the adopter window base
  must be aligned to its size rounded up to a power of two. Add this to the `smu.sv` static check
  (section 2), which may push the window base past the SHIM block (section 6).
- **Blocked accesses.** Like the harness instance, the adopter access control answers a locked region
  with `0xBADCAB1E` and no SLVERR, and raises `locked_field_access_interrupt_o`. OR the two instances'
  interrupt and debug lock outputs, or give the adopter its own bits in `efuse_debug_o`.
- **Before sense done.** The adopter window returns SLVERR until the combined sense done, as the
  harness window does today, so JTAG flows must wait for sense done before touching either window.
- **Program and read path (`efuse_guard`).** The CTRL window's program and read interfaces are
  reached by both ports too. The guard truncates the target's byte address to the MAP window width
  (10 bits for the SMC) before looking up a rule, so an adopter target at fuse bit 8192 or above
  would wrap onto harness rules and be checked against the wrong lock. The guard must select harness
  or adopter rules from the full, widened bit address and index `ADOPTER_LOCKS` for adopter targets.
- **Lock struct coupling.** The guard reads harness locks as `shadow_regs_i.locks.locks`, a member
  name shared by the SMC and SEP map structs. Either keep the hand-written `smc_efuse_pkg` member
  named `locks` after the RDL rename, or pass both lock vectors to the guard as ports.
- **Fairness.** JTAG and firmware share the mux, so a long JTAG sweep of the adopter window stalls
  firmware accesses to every eFuse window. This is no worse than a sweep of the harness map.

## 9. Documentation plan

The TRM describes as-built hardware, so this text is written on the feature branch and merges in
the same pull request as the RTL. It follows `doc/trm/AUTHORING.md`: hardware behaviour only,
procedures in the Programmer's Guide, no copied register fields, stable `efuse-adopter-*` anchors,
and figures that meet the inline font-size floors.

**TRM, eFuse chapter (`hw/ip/efuse/doc/`)**

- `architecture.adoc`: new section `[[efuse-adopter-fuses]] === Adopter Fuse Region (SMC)`, about
  a page and a half, after the shadow register material:
  - Purpose: SMC only, sized by `CFG`; the harness senses, shadows, locks and exports the region
    without interpreting it.
  - One simplified figure: adopter map in `smc_external`, the second shadow instance on the shared
    access path, `ADOPTER_LOCKS` feeding its locks, and the `smc_adopter_shadow_regs_o` export. The
    proposal figures are too dense for the TRM font floors and are not reused.
  - Summary table: configuration, map description, software window, fuse bit address, shadow file,
    export, locks, static policy, JTAG policy.
  - Sensing and boot: the adopter region is sensed after the harness map through the same SHIM, and
    sense done covers both.
  - Locks: what `HARNESS_LOCKS` and `ADOPTER_LOCKS` govern and how the region ends define the
    regions; fields are left to the generated register table.
  - Access path: same functional/JTAG path as the harness shadow, JTAG lifecycle policy unchanged,
    locked regions read `0xBADCAB1E`, and the guard checks program and read commands to adopter fuses.
  - Constraints: window alignment, size ceiling, no secrets, append-only growth, no region by
    default.
- Corrections to existing text:
  - `index.adoc`: add a feature bullet.
  - `architecture.adoc`: the software-lock row of the lock table names `LOCKS`; the shadow capacity
    row gains the adopter region; one sentence in the SMC JTAG policy saying the adopter window
    follows it.
  - `interface.adoc`: the "1 KB total" statement, and the SHIM `ready` handshake in the command
    protocol.
  - `memmap.adoc`: a short paragraph on the adopter window. No generated table, since the adopter
    owns that map.
- The SMC shadow register table regenerates from `smc_efuse_map.rdl` and needs no hand edit.

**Outside the TRM (same pull request)**

- Integrator guide (`doc/integrator/src/smu-smc.adoc`): the 8 Kbit statement, the SHIM handshake,
  the three `CFG` fields and their static checks, the new export port, and the optional RDL and
  script.
- Programmer's Guide (`doc/programmer/src/smc-programming.adoc`): the `LOCKS` rename and locking
  production regions early in boot.
- SMC scan protection (`hw/sys/smc/doc/scan_protection.adoc`): Class 1 storage covers words 0–3.

**Verification:** the `doc/trm/AUTHORING.md` checklist: `make doc-trm-serve`, the PDF build, anchor
resolution and the figure font floors.

## Open questions

- **`ADOPTER_LOCKS` placement.** The layout above follows the rule that hardware-consumed fuses sit
  at the top, at the cost of shifting every later harness field. Placing `ADOPTER_LOCKS` at the end
  of the map (`0x3F8`, with the spare tail before it) would leave every existing offset unchanged,
  keeping only the rename as churn.
- **`security_disable` path.** Sensing is skipped there; confirm how `fuse_sense_done` and the
  fuse-released reset behave today, and make the adopter instance mirror it so boot cannot stall.
- **SMC-to-SEP coupling.** The SEP's `ext_boot_seq_done_i` comes from the SMC's qualified signal, so
  a longer SMC sense also delays SEP release.
- **DV timing bounds.** The SMC boot sense bounds (`SENSE_BOUND_CYCLES`) need headroom for a
  non-empty adopter region; the default configuration leaves them unchanged.
- **Inbound reach of the adopter window.** The SMC's top-level map, including `smc_external`, is
  described as accessible to external agents. Confirm whether a host can reach the adopter window
  through the SMC chiplet aperture, since unlocked regions rely on firmware locking them in time.
- **Handshake carrier.** Response-struct field or separate `ready` port (section 4).
- **Ceiling for the widened address type.** It caps the largest adopter region, including any future
  streamed or bulk mode, and is chosen together with the 16-bit region-end entries.
- **Keeping `CFG` and an adopter RDL in step.** Nothing forces an adopter that has an RDL to run the
  checking script, so the two can drift. Decide whether the script is only offered, or also
  documented as a step in the adopter's own build.
