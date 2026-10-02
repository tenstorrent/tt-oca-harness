<!-- SPDX-License-Identifier: Apache-2.0 -->
# Plan — replace the bus-partner target with an independent I3C VIP

## Goal

`dv/tb/tb_i3ccore.sv` instantiates `NumI3c=2` copies of the same vendored
i3ccore RTL: instance 0 is the controller under test, instance 1 is the bus
partner acting as target. Every bus-traffic result is therefore produced and
checked by the same RTL on both sides, so a protocol-level defect that is
symmetric cannot be detected.

This plan keeps instance 0 as the DUT and replaces the instance-1 bus partner
with `ocah_i3c_vip` (over `cocotbext_i3c.I3CTarget`), giving a stimulus and
response source independent of the DUT.

The immediate motivation is the open item in `BRINGUP_STATUS.md`:
`i3c_error_target_abort.test_short_read_permitted` (`sre=0` produces no
response descriptor). With the current topology that failure cannot be
attributed — an independent target settles whether it is a controller-side
reporting gate (category B) or an artifact of the target-side RTL.

## Constraint that shapes the plan

`cocotbext_i3c.I3CTarget` does not implement CCCs. `i3c_target.py:139` carries
`TODO: Handle CCCs.`; the message handler special-cases only 0x20 and 0x23
(target reset actions) and treats every other CCC as not addressed to it.
`max_read_length` is a constructor argument with the note
`TODO: Should be controlled with CCC`.

The DUT controller issues these CCCs across the current test set:

| CCC | Code | Form | Call sites |
|---|---|---|---|
| SETDASA | 0x87 | directed write | 13 — required by `bring_up_and_assign()` |
| SETMRL / SETMWL | 0x8A / 0x89 | directed write | 11 / 5 |
| GETBCR / GETMWL / GETMRL | 0x8E / 0x8B / 0x8C | directed read, must return data | 6 / 4 / 4 |
| RSTACT | 0x9A | directed write + defining byte | 4 |
| ENEC / DISEC | 0x00 / 0x01 | broadcast write | IBI enable/disable |
| RSTDAA | 0x06 | broadcast write | 1 |
| SETNEWDA | 0x88 | directed write | 1 |

So the VIP target is not a drop-in partner today. Phase 1 below adds the one
CCC that unblocks bring-up and answers the open item; Phase 3 adds the rest
only if Phase 2 shows the approach holds.

## What does not change

Out of scope, and to stay on the RTL target for coverage reasons:

- `test_i3ccore`, `i3c_axi_protocol`, `i3c_reg_reset_value_full` — AXI register
  access only, no bus traffic.
- `i3c_multi_instance_indep` — needs two RTL instances by definition.
- `i3c_immediate_write_sanity`, `i3c_error_sanity`, `i3c_error_parity_inject`,
  `i3c_tx_capacity_512`, `i3c_ibi_sanity` — these verify the target-side TTI
  path of the RTL. Moving them to a Python target would remove that coverage.

The VIP target is a second configuration, not a replacement. Both run.

## Phase 1 — SETDASA and controllable short read

Smallest change that produces a verdict on the open item.

1. **TB wiring.** Add a cocotb-drivable pair (`vip_scl_o`, `vip_sda_o`,
   released high) and fold it into the existing open-drain nets at
   `tb_i3ccore.sv:122` and `:127`, matching the `oe && !o` convention already
   documented there. Gate instance 1's contribution behind a parameter so the
   RTL target can be excluded without deleting it. `sda_corrupt` at `:131`
   stays as is.
2. **SETDASA in the VIP target.** Accept the reserved-byte header, match 0x87,
   receive the dynamic-address byte, ACK, and store the address for subsequent
   private transfers. Land it as a subclass in the IP's own `dv/cocotb/env/`,
   next to its only consumer — not in `hw/common/dv/vip/` until Phase 3 proves
   the shape.
3. **Short-read control.** Drive the data phase to supply fewer bytes than
   requested and terminate with the T-bit, using `handle_read` /
   `send_byte(byte, terminate)` and `max_read_length`.
4. **New test module** `i3c_vip_short_read.py`: `sre=0` and `sre=1`, mirroring
   the stimulus of `i3c_error_target_abort` so the two topologies are directly
   comparable.

**Exit criterion.** Both `sre` values run against the VIP target and the
response-descriptor behaviour is captured with log evidence. If `sre=1` still
reports and `sre=0` still does not, the controller-side reporting gate is
confirmed as category (B) and gets a ticket against the vendored i3c-core. No
existing expectation or assertion is modified either way.

### Result

Met. `i3c_vip_short_read` on Verilator 5.036, seed 1
(`random seed = 0x00C0FFEE`):

Both runs use one length pair and one VIP instance, so SRE is the only variable:

```
 32225ns  TARGET:::CCC 0x87 assigned dynamic address 0x10
 32275ns  Short read (sre=1): controller requests 24B, VIP target supplies 20B
 98255ns    response=0x70000014 err_status=0x7 data_length=20 rx_drained=16B
 98255ns  Short read (sre=0): controller requests 24B, VIP target supplies 20B
2898625ns  AssertionError: no response descriptor for a permitted short read
           (requested=24, supplied=20), after 20000 polls:
           ctrl_rx_drained=16B of 20B supplied, VIP target state=I3cState.FREE,
           last PIO_INTR_STATUS=0x00000009 (rx_thld=0, resp_ready=0,
                                            transfer_err=0, transfer_abort=0)
```

This is what excludes the target. SRE is a command-descriptor field written over
AXI; it never appears on the I3C bus, so with the lengths held fixed the target
performs the identical transfer in both runs. `sre=1` yields `ERR_STATUS 0x7`
with `DATA_LENGTH=20`, the received length, which also proves the model's short
read is well formed on the wire and that the controller decodes it. Flipping only
SRE removes the response descriptor entirely, and raises no error either.

Two conclusions follow. The gap is inside the controller, not in whatever
implements the target. And the controller already holds the received length,
since `DATA_LENGTH=20` appears on the `sre=1` path, so what is missing is the
descriptor, not the count.

The peer-topology run in `i3c_error_target_abort` shows the same
`PIO_INTR_STATUS=0x00000009` signature, so the two topologies agree.

The test is left failing as a spec-correct sentinel. It is in the `vip` group,
not `all`.

### Harness blockers cleared to get there

All category (A), all pre-existing except the last:

1. **Verilator could not build the TB at all**, including the existing tests.
   The `smc` bender target supplies `prim_ram_1p_scr_ext.sv` but not the
   `prim_cipher_pkg` / `prim_prince` / `prim_subst_perm` it instantiates, which
   are gated on `any(opentitan_smu, sep, smu, key_manager)`. Nothing in this TB
   uses a scrambled RAM, so `i3ccore_wrap_sim_cfg.toml` drops the file through
   `build.exclude_files`. `i3c_write_read_sanity` passes again after that. The
   same gap presumably affects any other `smc`- or `dtp`-target build.
2. **cocotbext-i3c does not import under the repo's cocotb.** Version 1.1.0
   reads `cocotb.utils._get_log_time_scale` / `_get_simulator_precision` and
   `cocotb.handle.ModifiableObject`, all moved or dropped in cocotb 2.0.
   `env/cocotbext_i3c_compat.py` restores them and re-exports the classes, so
   nothing under `vendor/.../upstream/` is hand-edited.
3. **The stock target model rejects two legal sequences**, so `VipI3cTarget`
   replaces `wait_header` rather than extending it: a directed CCC phase, whose
   preceding header `handle_message` has already cleared, and a private transfer
   opened directly with the dynamic address and no reserved byte. Both trip an
   assert that encodes a sequencing assumption the spec does not require.

## Phase 2 — validate the topology

Confirm the VIP target is a faithful bus partner before any migration.

1. Port `i3c_write_read_sanity` to the VIP target as a parallel module. Private
   write and read only, so SETDASA is the only CCC needed.
2. Compare against the RTL-target run: byte content, and OD/PP timing on the
   shared bus. `OcahI3cMonitor` can observe passively alongside.
3. Record the bring-up sequence differences — the VIP target has no TTI
   registers, so `init_target()` and `configure_thresholds()` become no-ops
   and `wait_dynamic_addr()` reads Python state.

**Exit criterion.** The VIP-target variant passes and its bus timing matches
the RTL-target run. A mismatch here stops the plan and gets reported, since it
would mean the VIP target, not the DUT, is the thing under suspicion.

## Phase 3 — optional batch migration

Only if Phases 1 and 2 both pass, and only for the controller-side tests.

1. Add the remaining CCC handlers from the table above, plus a Python-side
   BCR / MWL / MRL register model for the GET responses. IBI initiation needs
   no new work: `I3CTarget.send_ibi(mdb, data)` already exists.
2. Provide a VIP-backed class with the same surface the tests already use —
   `initialize`, `configure_thresholds`, `wait_dynamic_addr`,
   `wait_dynamic_addr_cleared`, `enable_ibi_mode`, `disable_ibi_mode`,
   `write_ibi`, `wait_ibi_done` (8 methods; see `env/i3c_api.py:1370`). Select
   it per run so each controller-side test can execute against either partner.
3. Promote the class to `hw/common/dv/vip/ocah_i3c_vip/` once a second consumer
   appears, per the promotion policy in `hw/common/dv/README.md`.

## Per-test migration map

What each module needs from the VIP target, given what it supports today: SETDASA
and SETNEWDA, private read, private write, and the untested `send_ibi`. Derived
from the `ctrl.*` and `tgt.*` calls and the TTI register references in each module.

### Ready now — bus partner only, no CCC beyond SETDASA

`i3c_long_write_sanity`, `i3c_long_read_sanity`, `i3c_back_to_back`,
`i3c_pp_timing_transfer`, `i3c_od_pp_mode_switch`, `i3c_threshold_sweep`.

Each still needs its controller sequence written out, because
`I3CController.private_write` / `private_read` drive the RTL target's TTI
registers to move the far side. `i3c_vip_write_read_sanity` is the pattern.

Already done: `i3c_write_read_sanity` → `i3c_vip_write_read_sanity`,
`i3c_error_target_abort` → `i3c_vip_short_read`.

### Ready with one caveat each

| Module | Caveat |
|---|---|
| `i3c_setnewda` | SETNEWDA is already handled; the `ctrl.set_ccc` path needs checking |
| `i3c_multi_target_dat` | Needs two VIP instances at different addresses. The TB exposes one `vip_sda_o` / `vip_scl_o` pair, so this needs either per-instance drive lines or a wired-AND in Python |
| `i3c_reset_mid_transaction` | The model has no reset recovery, so a reset mid-frame can leave its state machine stranded |

### Needs new CCC handlers

| CCC to add | Unblocks |
|---|---|
| RSTDAA (broadcast, clears the address) | `i3c_broadcast_ccc` |
| SETMWL / SETMRL (directed write) | `i3c_max_length_transfer`, `i3c_random_transfer_stress` |
| GETBCR / GETMWL / GETMRL (directed read, must return data) + RSTACT | `i3c_direct_ccc_sanity`, `i3c_full_ccc_matrix`, `i3c_random_ccc_stress`, `i3c_recovery_reset_iface` |

The directed-read CCCs are the real work: they need a Python-side BCR / MWL / MRL
register model, not just frame decoding.

### Needs target-initiated IBI plus ENEC / DISEC

`i3c_ibi_sanity`, `i3c_ibi_payload_variants`, `i3c_ibi_nack_disabled`,
`i3c_ibi_diag`. `I3CTarget.send_ibi(mdb, data)` exists but is unexercised here,
and these modules arm the IBI through the RTL target's TTI registers, so the
target half is a rewrite rather than a substitution.

### Stays on the RTL target

Not candidates, because the RTL target is the thing under test or the topology
requires it:

- `i3c_immediate_write_sanity`, `i3c_error_parity_inject`, `i3c_error_sanity`,
  `i3c_tx_capacity_512` — these exercise the target-side TTI path.
- `i3c_multi_instance_indep` — two RTL instances by definition.
- `test_i3ccore`, `i3c_axi_protocol`, `i3c_reg_reset_value_full` — AXI register
  access only, no bus traffic.

The IBI modules also read on the target-side RTL, so moving them trades that
coverage away. They are worth a VIP variant alongside, not instead.

## Risks

- **The VIP target is not silicon either.** It is a model, so a Phase 1 or 2
  disagreement identifies which side to investigate; it does not by itself
  prove the DUT wrong. Any category (B) claim still needs spec citation plus
  waveform.
- **Undocumented library surface.** cocotbext-i3c is pinned at 1.1.0 and its
  README and CHANGELOG document only `I3cController` SDR private / legacy-I2C /
  CCC operations. The target model, HDR-DDR, HDR-BT and the recovery interface
  exist in the source with no documentation and no version bump, so the source
  is the reference and an upgrade can break silently.
- **Timing fidelity.** `I3cControllerTimings` follows MIPI I3C Basic v1.1.1
  Tables 86/87 defaults, which need not match what the RTL target does. This is
  what Phase 2 measures.
- **Recovery and HDR stay out.** `i3c_recovery_reset_iface` is unaffected by
  this plan; `cocotbext_i3c.i3c_recovery_interface` is not wrapped.
