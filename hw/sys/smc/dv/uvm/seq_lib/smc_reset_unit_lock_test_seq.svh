// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC reset-unit lock scenario sequence (smc_reset_unit_lock_test), carrying
// the cocotb smc_reset_unit_lock_test_seq semantics on the SEP_IN AXI4
// ingress: the reset unit's two `onwrite=woset` lock registers are sticky,
// and each one masks the register it guards.
//
// Semantics are taken from the RDL, not assumed. Both lock fields are
// `sw=rw; hw=r; onwrite=woset;` with reset 0, one bit per subsystem, and each
// lock's description names the register it guards and the per-bit hold rule:
// SS_CONFIG_LOCK "lock[s] down SS config. If bit 0 is written, then bit 0 of
// other SS config cannot be written to again" (reset_unit.rdl SS_CONFIG_LOCK),
// and SS_COLD_RESET_LOCK the same for SS cold reset. So a
// locked bit keeps its value on read-back. The RDL does not state how the
// bus answers a write that hits locked bits; CHK-CSR-RESP requires OKAY there
// as this bench's working assumption, recorded in the VPLAN row.
//
// Two things stop the masking leg passing for the wrong reason:
//
//   * THE TARGET IS PROVED WRITABLE AT THAT BIT FIRST. Without it, "the
//     locked bit did not change" is satisfied by a register that never
//     changes at all.
//   * THE MASKED WRITE CARRIES AN UNLOCKED BIT ALONGSIDE THE LOCKED ONE, AND
//     THAT BIT IS REQUIRED TO CHANGE. So "unchanged" cannot be explained by
//     the write having been dropped on the floor.
//
// 16 PASSES IN ONE SIMULATION. `woset` is irreversible, so the cocotb twin
// relies on each testcase owning its simulation. That does not hold here:
// ocah_test runs at least 16 scenario passes back to back without a reset
// between them. Each pass therefore locks A FRESH BIT -- bit 1 + loop_index --
// while bit 0 is never locked in any pass and stays the writability control.
// The bits locked by earlier passes accumulate, which the sequence accounts
// for through smc_lock_accum_mask() and the reference model rebuilds from the
// traffic it observed.
//
// Every value compare is also made independently by the always-on
// smc_scoreboard's lock_csr feature, whose reference model applies woset to
// the lock and lock-filtered bit-enables to the guarded register;
// +SMC_LOCK_SCOREBOARD_NEGATIVE corrupts that prediction so the run must
// FAIL.

class smc_reset_unit_lock_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_reset_unit_lock_test_seq)

  localparam string ChkTargetWritable = "CHK-LOCK-TARGET-WRITABLE";
  localparam string ChkLockSet = "CHK-LOCK-SET";
  localparam string ChkLockSticky = "CHK-LOCK-STICKY";
  localparam string ChkMasksTarget = "CHK-LOCK-MASKS-TARGET";
  localparam string ChkFreeBitMoved = "CHK-LOCK-FREE-BIT-MOVED";
  localparam string ChkNonvac = "CHK-NONVAC";

  // Bit 0 is the never-locked control; pass `idx` locks bit 1 + idx. The
  // ceiling keeps 1 << (bit + 1) inside 32 bits, so a loop knob that would
  // run out of lockable bits fails loudly instead of silently aliasing.
  localparam int unsigned FreeBit = 0;
  localparam int unsigned MaxLockBit = 30;
  // Accesses this body issues per lock pair and pass: five write+read legs.
  localparam int unsigned AccessesPerPair = 10;
  // Of those ten, five are reads, and each one is predicted by the lock_csr
  // reference model.
  localparam int unsigned ReadsPerPair = 5;

  function new(string name = "smc_reset_unit_lock_test_seq");
    super.new(name);
  endfunction

  task body();
    smc_lock_pair_t pairs[$];
    int unsigned    lock_bit = 1 + loop_index;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkTargetWritable, ChkLockSet, ChkLockSticky,
                    ChkMasksTarget, ChkFreeBitMoved, ChkNonvac, ChkSbMinAct});
    smc_lock_pairs(pairs);
    // Five reads per pair reach the lock_csr predictor each pass.
    check_min_activity(SmcFeatureLockCsr, pairs.size() * ReadsPerPair);
    if (lock_bit > MaxLockBit)
      `uvm_fatal(get_type_name(), $sformatf(
                 {
                   "scenario pass %0d would lock bit %0d: the woset locks only carry bits 1..%0d ",
                   "beyond the never-locked control bit 0. Lower the loop knob."
                 },
                 loop_index,
                 lock_bit,
                 MaxLockBit
                 ))
    `uvm_info(
        get_type_name(),
        $sformatf(
            {"SMC SV-UVM reset-unit lock (smc_reset_unit_lock_test): %0d woset pairs, this pass ",
             "locks bit %0d and keeps bit %0d free; scenario_seed=%0d"}, pairs.size(), lock_bit,
              FreeBit, scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    foreach (pairs[i]) run_pair(pairs[i], lock_bit);

    check_evidence(ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses),
                   64'(pairs.size() * AccessesPerPair));
    finalize_evidence();
  endtask

  // One lock pair, one pass: prove the target bit writable, take the lock on
  // it, prove the lock sticky, then prove the lock masks that bit while an
  // unlocked bit in the same write still lands.
  protected task run_pair(smc_lock_pair_t pair, int unsigned lock_bit);
    bit [31:0] accum = smc_lock_accum_mask(lock_bit);  // bits 1..lock_bit
    bit [31:0] free_mask = 32'h1 << FreeBit;
    bit [31:0] observed;
    string     tag = pair.name;

    // 1. Positive control: bit `lock_bit` is still unlocked, so writing it
    //    must land. Earlier passes' bits are written as 1 too; they are
    //    already locked at 1 and unaffected either way.
    csr_write(pair.target_addr, accum, {tag, ".target_pre_lock"});
    csr_read_check(ChkTargetWritable, pair.target_addr, accum, {tag, ".target_pre_lock"});

    // 2. Take the lock on that one bit; woset ORs it into whatever earlier
    //    passes already locked.
    csr_write(pair.lock_addr, 32'h1 << lock_bit, {tag, ".lock_set"});
    csr_read_check(ChkLockSet, pair.lock_addr, accum, {tag, ".lock_set"});

    // 3. woset: a written 0 cannot release a taken lock.
    csr_write(pair.lock_addr, 32'h0, {tag, ".lock_release_attempt"});
    csr_read_check(ChkLockSticky, pair.lock_addr, accum, {tag, ".lock_sticky"});

    // 4. The masked write: clear every locked bit AND set the free bit in one
    //    access. The locked bits must survive and the free bit must change.
    csr_write(pair.target_addr, free_mask, {tag, ".masked_write"});
    csr_read(pair.target_addr, observed, {tag, ".masked_write"});
    check_evidence(ChkMasksTarget, {tag, ".locked_bits_held"}, 64'(observed & accum), 64'(accum),
                   $sformatf(
                   "wrote 0x%08h to addr=0x%0h with bits 1..%0d locked; read 0x%08h",
                   free_mask,
                   pair.target_addr,
                   lock_bit,
                   observed
                   ));
    check_evidence(ChkFreeBitMoved, {tag, ".free_bit_set"}, 64'(observed & free_mask),
                   64'(free_mask), $sformatf(
                   "bit %0d is locked by no pass, so the same write had to land there", FreeBit));

    // 5. Restore the free bit; the locked bits stay held, which is the same
    //    masking property observed in the other write direction.
    csr_write(pair.target_addr, 32'h0, {tag, ".free_bit_restore"});
    csr_read(pair.target_addr, observed, {tag, ".free_bit_restore"});
    check_evidence(ChkFreeBitMoved, {tag, ".free_bit_cleared"}, 64'(observed & free_mask), 64'h0,
                   "the never-locked bit moves in both directions");
    check_evidence(ChkMasksTarget, {tag, ".locked_bits_held_after_restore"}, 64'(observed & accum),
                   64'(accum), $sformatf("read 0x%08h", observed));
  endtask

endclass : smc_reset_unit_lock_test_seq
