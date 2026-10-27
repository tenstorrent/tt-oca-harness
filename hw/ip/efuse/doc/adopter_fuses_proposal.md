## Summary

Adopters integrating the harness into their own SoC need fuses of their own. This proposes a
supported, sized adopter fuse region in both the SMC and the SEP. The harness senses it, shadows it,
locks it and exports it, without interpreting its contents and without RTL changes per adopter.
Harness spares stay reserved for the harness. The scope is a small set of configuration fuses that
adopter logic needs continuously; bulk data such as memory repair is a follow-up.

## 1. Adopter fuse maps

- The adopter provides `smc_adopter_fuse_map.rdl` and `sep_adopter_fuse_map.rdl` containing their own
  fields.
- The maps sit inside the adopter external windows, `smc_external` and `sep_external`, so the adopter
  can make them as large as they need.
- The harness ships default stub files with those names.

## 2. Parameters

- Add adopter window base and size to `smu_pkg` `CFG` for each subsystem, alongside the existing
  `SMC_EFUSE_SHIM_SIZE` / `SEP_EFUSE_SHIM_SIZE`.
- Add static checks that each adopter window fits inside `smc_external` / `sep_external`, in the same
  style as the existing SHIM size checks in `smu.sv`.
- Keep two address spaces distinct:
  - **Software window:** where the adopter map appears in the external window. Base and size come
    from `CFG`.
  - **Fuse bit address:** where the adopter bits sit in the OTP. Fixed to start at the end of the
    harness's 8 Kbit, so harness fuse addresses never move. Only the size varies.

## 3. Sensing and the shadow file

- Sensing fills the harness shadow file, then a second, adopter shadow file, through the same SHIM.
- The harness sees one linear fuse address space, and the adopter's SHIM maps addresses to macros.
- **Fuse sense done means every region is sensed.** `fuse_sense_done` (and so
  `smc_fuse_sense_done_o` / `sep_fuse_sense_done_o`, the `efuse_sense_done` status bit, the
  fuse-released reset and the SEP secure-test-mode latch) asserts only once both the harness and the
  adopter regions are in their shadow files. With the default empty adopter map this is identical to
  today, so existing DV is unaffected.
- An adopter-done signal can remain for observability and for qualifying the boundary export, but
  the boot flow depends only on the combined done.
- Implementation: reuse `efuse_shadow_regs` as a second instance for the adopter file, rather than
  one FSM writing both files.
  - Add a start-address parameter (default 0) and a sense-start input (tied high for the harness
    instance). The adopter instance starts when the harness instance finishes and reads from fuse
    bit address 8192. `.address` is a bit address, not a word index.
  - Make the preload plusarg name a parameter; today it is chosen by `HAS_LC_STATE`, which would give
    a SEP adopter instance the SMC plusarg.
  - The controller's command mux keeps the SHIM in sense mode until the adopter instance is done.
  - The harness instance's code, hierarchy and signal names are unchanged, so testbench taps,
    coverage and FSM exclusions, lint waivers and scan-protection naming keep matching. A single FSM
    would rewrite exactly the lines those artifacts are keyed on, and widen the counter that feeds
    the SEP `LC_STATE` capture.
- The adopter instance is reset by the controller's `rst_ni`, never by the fuse-released
  `reset_n_o`, or it would wait on itself.
- An empty adopter region must elaborate away cleanly (a packed array cannot have zero elements),
  so that combined done equals harness done exactly in the default build.

### Boot-flow races this avoids

If done meant "harness region only", the fuse-released reset would let the CPU and the controller's
read and program interfaces run while the adopter READ is still streaming:

- **Firmware can take the SHIM mid-stream.** The mux hands the SHIM to a firmware read or program
  once done is high, and routes responses by its current selection. Adopter words would land in the
  firmware's read interface, the adopter shadow would never reach its word count, and adopter done
  would never assert. Giving adopter sensing priority instead leaves the firmware request hanging or
  timing out.
- **Firmware sees bus errors.** Until its own sense completes, the shadow module answers APB accesses
  with `pslverr` and `0xBADCAB1E`, so early ROM code that locks adopter slices would fault.
- **Adopter hardware captures zeros.** Logic released by the same reset would sample its
  configuration before the adopter shadow is filled.
- **SEP secure test mode would block the adopter sense entirely.** The SEP latches secure test mode
  on the rising edge of sense done and feeds it back into the controller, which then holds back
  every sense command. Today the harness sense always finishes before that latch takes effect; an
  adopter sense that started after harness done would never run in secure test mode.

## 4. SHIM command handshake (ready/valid)

Today the command interface has no acknowledgement. The SHIM accepts a command whenever it is idle
and `valid` is high, and every requester (sense, read, program) holds `valid` high until its
response returns. Correctness depends on the controller deselecting the request before the SHIM
returns to idle. With the reference SHIM those two events coincide with zero cycles of margin; a
SHIM without a finish state would accept the sense READ a second time, its responses would go to
whichever path the mux has switched to, and the load path can overwrite the last shadow word. A
second sense command adds a second handoff of this kind.

Proposal: the adopter SHIM drives a `ready` signal.

- A command transfers on a cycle where `valid` and `ready` are both high. The requester holds the
  request stable while `valid && !ready`, and drops `valid` after the transfer with no consequence.
- Responses are unchanged: a valid-only stream with no backpressure. The controller always accepts
  them.
- The controller counts outstanding responses per command (the access length for a sense, one for a
  read or program) and switches the mux only when none are outstanding.
- For most SHIMs `ready` is "my command FSM is idle", which is one line. A SHIM must not tie `ready`
  high unless it can genuinely accept a command in any state.
- Carry `ready` either as a field of the response struct (`EFUSE_COMMAND_RESP_T`), which adds no
  boundary port but changes the packed layout, or as a separate `efuse_shim_command_ready_i` port per
  subsystem, which leaves the struct alone. The separate port is easier for DV monitors and BFMs
  that unpack the struct.
- This is a contract change for every adopter, not only those using adopter fuses. Update the
  reference SHIM (`efuse_interface_shim.sv`), the integrator guide's SHIM contract and figure, and
  the DV components that drive or watch SHIM responses directly (for example the SEP eFuse SHIM
  fault-injection tests and the SMU sense probe). The existing sense-sequence checks count read
  command pulses, which stays at one per command.

## 5. Boundary export

- Export the adopter shadow file at `smu.sv` as a flat word array sized by `CFG`, for example
  `smc_adopter_shadow_regs_o` and `sep_adopter_shadow_regs_o` (`logic [N-1:0][31:0]`). The adopter
  casts it to the struct generated from its own RDL.
- Widen the fuse bit-address and access-length types in `smc_efuse_pkg` / `sep_efuse_pkg` (today
  fixed at 8 Kbit: a 13-bit bit address and a 9-bit word counter) to a fixed maximum, with `CFG`
  bounding what is actually used. Package typedefs cannot follow a `CFG` value.
  - To keep default builds bit-identical, take the widths from a size constant in a stub-generated
    adopter package whose default size is 0. A build without adopter fuses keeps today's widths and
    today's DV.

## 6. Fabric routing

- Place the adopter fuse window directly after the eFuse SHIM control block at the base of the
  external window.
- Extend the existing diversion from SHIM size to SHIM size plus adopter size, so software accesses to
  adopter fuses enter the eFuse controller. They then go through its lock and lifecycle checks instead
  of leaving on `smc_external_req_o` / `sep_external_req_o`.

## 7. Hardware locks for the adopter region

- The harness owns a fixed 64-bit `LOCKS` register at offset `0x0` of each adopter region, followed
  by the adopter's map at `0x8`.
- `LOCKS` holds 32 read/write pairs, with the write lock at bit 2n and the read lock at bit 2n+1,
  matching the harness maps.
- The harness splits the adopter payload (excluding `LOCKS`) into 32 equal slices of 32-bit words.
  Pair n governs slice n. Example: 128 words gives 4 words per pair (words 0–3 to pair 0, words 4–7
  to pair 1, and so on).
- Lock granularity is therefore the adopter map size divided by 32, rounded up to a power of two so
  the slot index is a shift, not a divide (100 words → 4 per slot, 25 slots used; 200 words → 8 per
  slot, 25 slots used). Unused slots are harmless.
- The 33 field-map rules (the `LOCKS` meta entry with the existing all-ones sentinel index, plus 32
  slices) are generated from the `CFG` size at elaboration. No adopter field names reach the RTL.
- Hardware and software locks both work as today: burning a `LOCKS` fuse is a permanent hardware lock,
  and writing the shadow copy (write-1-to-set) is a software lock until reset.
- RDL ownership:
  - Harness-owned wrapper per subsystem (`sep_adopter_fuse_locks.rdl` / `smc_adopter_fuse_locks.rdl`,
    defining the `sep_adopter_fuse_region` / `smc_adopter_fuse_region` addrmap): `LOCKS` with 32
    named pairs, plus the adopter payload instantiated at `0x8`.
  - Adopter-owned `sep_adopter_fuse_map.rdl` / `smc_adopter_fuse_map.rdl`: payload fields only.
  - Examples next to this proposal: `sep_adopter_fuse_locks.rdl` (the wrapper) and
    `sep_adopter_fuse_map.rdl` (a 512-byte payload of memory repair entries, sensor trims and adopter
    spares, one register per 4-word slice).
- Contract rule for adopters: align a field to a slice boundary if it must be locked on its own. A field
  that straddles a boundary is governed by two pairs. The register generator could warn when that
  happens.

### Static policy: none

Each harness rule also carries static bits (set-only write, write lock, secure-test write lock) that
govern software writes to the shadow copy only; fuse programming is checked against the dynamic
`LOCKS` bits alone. The adopter region uses no static policy.

- Every slice is write-unlocked, read-unlocked and has no secure-test lock. This matches most harness
  fields and needs no per-slot `CFG` masks.
- Unlocked slices let firmware override the shadow, which the adopter's hardware sees immediately,
  until reset. This is intended for the target use cases: soft memory repair during bring-up and
  test, and trial sensor trims before burning.
- The 32 dynamic write/read lock pairs in `LOCKS` are the only protection, set by firmware (until
  reset) or burned (permanent). They stay; dropping them would leave nothing to stop firmware burning
  the adopter region in the field.

Risks and the contract rules that cover them:

- **Protection depends on someone setting the locks.** Until a slice's write lock is set, anything
  that can reach the adopter window can override the shadow and burn extra 1s into the fuses, which
  is permanent. Extra bits in repair data break repair; a bad trim mis-calibrates a sensor. The
  harness ROM does not know the adopter's slices, so the adopter's firmware must lock its production
  slices early in boot, and the adopter documents which slices those are.
- **No secrets in the adopter region.** Without a secure-test lock, secret ranges or Class 1
  storage, adopter words get normal scan handling and are not masked in secure test mode. Repair and
  trim data are fine. An adopter that needs secret fuses is a future extension that brings back
  per-slot policy, mainly in the SEP.
- **Reachability of the window.** If agents outside the subsystem can reach the adopter window
  through the chiplet aperture, they can override unlocked slices. Confirm the inbound filtering
  (see open questions).

## Open questions
- **`security_disable` path.** Sensing is skipped there; confirm how `fuse_sense_done` and the
  fuse-released reset behave today, and make the adopter instance mirror it so boot cannot stall.
- **SMC-to-SEP coupling.** The SEP's `ext_boot_seq_done_i` comes from the SMC's qualified signal, so
  a longer SMC sense also delays SEP release.
- **JTAG and the controller's window decode.** The AXI-Lite decode checks one contiguous range from
  the MAP to the MMR window; the adopter window's placement affects the JTAG lifecycle policy and the
  error-response routing.
- **DV timing bounds.** The secure-test sense-window test and the boot sense bounds
  (`SENSE_BOUND_CYCLES`) need headroom for a non-empty adopter region; the default stub leaves them
  unchanged.
- **Inbound reach of the adopter window.** The SMC's top-level map, including `smc_external`, is
  described as accessible to external agents. Confirm whether a host can reach the adopter window
  through the SMC (and SEP) chiplet aperture, since unlocked slices rely on firmware locking them in
  time.
- **Handshake carrier.** Response-struct field or separate `ready` port (section 4).
- **Ceiling for the widened address type.** It caps the largest adopter region, including any future
  streamed or bulk mode.
