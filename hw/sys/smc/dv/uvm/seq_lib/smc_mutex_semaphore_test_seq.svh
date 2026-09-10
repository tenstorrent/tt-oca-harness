// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC mutex/semaphore scenario sequence (smc_mutex_semaphore_test), carrying
// the cocotb smc_mutex_semaphore_test_seq semantics on the SEP_IN AXI4
// ingress: CPU_CTRL MUTEX[0] take / deny / release, MUTEX[1] independence,
// and the SEMA[0] signed accumulator.
//
// EXPECT-SOURCE is the SPEC, not the RTL -- cpu_ctrl.rdl:270-293:
//   reg MUTEX  `mutex[0:0] = 0x1`, "Reads will attempt to acquire mutex, 1 on
//              success. If the mutex is already acquired, the read will
//              return 0. To release the mutex, write any value to the
//              register." MUTEX[4] @ 0x240 -- four independent locks.
//   reg SEMA   `sema[15:0] = 0x0`, "Writing to this register will inc/dec the
//              semaphore value. The written value is treated as a signed
//              number using 2s compliment." SEMA[4] @ 0x260.
// Every address, field mask and reset value is symbol-sourced through
// smc_types (smc_top_addrmap_pkg + the generated smc_reg.svh).
//
// WHAT MAKES THE DENY LEG REAL. The second read of MUTEX[0] expects 0, and
// that expectation is only meaningful because the first read expected the
// "available" encoding and got it: a mutex stuck at 0 would fail leg 1, and a
// mutex stuck at 1 would fail leg 2. MUTEX[1] is then read while MUTEX[0] is
// held and must still report available, so "acquired" is a property of one
// lock rather than of the block.
//
// ONLY THE RDL FIELD BITS ARE COMPARED. Both registers are declared
// regwidth 64 with their live field inside the low 32 bits, so the bits above
// the field hold no field and are masked out instead of being given an
// invented expectation. The scoreboard's mutex_sema feature masks the same
// way.
//
// 16 PASSES IN ONE SIMULATION. A read acquires, so every pass must hand the
// block back in the state it found it: MUTEX[0] and MUTEX[1] are both released
// at the end (the release-proof read in leg 5 re-acquires MUTEX[0], which is
// why a second release follows it), and SEMA[0] is returned to its baseline by
// the matching negative increment. Without that, pass 2 would open on a held
// mutex and a non-zero accumulator.
//
// +SMC_MUTEX_SCOREBOARD_NEGATIVE corrupts the reference model's prediction so
// the run must FAIL.

class smc_mutex_semaphore_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_mutex_semaphore_test_seq)

  localparam string ChkMutexTake = "CHK-MUTEX-TAKE";
  localparam string ChkMutexDeny = "CHK-MUTEX-DENY";
  localparam string ChkMutexIndep = "CHK-MUTEX-INDEP";
  localparam string ChkMutexRelease = "CHK-MUTEX-RELEASE";
  localparam string ChkSemaAccum = "CHK-SEMA-ACCUM";
  localparam string ChkNonvac = "CHK-NONVAC";

  // Signed increment applied through the SEMA write port: +N then -N must
  // return the accumulator. Drawn per pass from the scenario seed rather than
  // fixed, so the 16 passes of one simulation exercise different magnitudes
  // instead of repeating one; bounded well inside the 16-bit field so the
  // sum cannot wrap, which would make the round trip pass for the wrong
  // reason. Never zero: +0 then -0 returns the accumulator whatever the DUT
  // does with a write.
  localparam bit [31:0] SemaStepMin = 32'd1;
  localparam bit [31:0] SemaStepMax = 32'd4095;
  // Accesses this body issues per pass: seven reads and five writes.
  localparam int unsigned ExpectedAccesses = 12;
  // Seven of those twelve are reads -- three of MUTEX[0], one of MUTEX[1],
  // three of SEMA[0] -- and each one is predicted by the mutex_sema model.
  localparam int unsigned PredictedReadsPerPass = 7;

  function new(string name = "smc_mutex_semaphore_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] mutex0 = smc_mutex_addr(0);
    bit [63:0] mutex1 = smc_mutex_addr(1);
    bit [63:0] sema0 = smc_sema_addr(0);
    bit [31:0] sema_step;
    bit [31:0] sema_step_neg;

    seed_scenario_rng();
    sema_step = SemaStepMin +
        32'(random_pattern(32) % (SemaStepMax - SemaStepMin + 32'd1));
    sema_step_neg = (~sema_step + 32'd1) & SmcSemaMask;
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkMutexTake, ChkMutexDeny, ChkMutexIndep,
                    ChkMutexRelease, ChkSemaAccum, ChkNonvac, ChkSbMinAct});
    check_min_activity(SmcFeatureMutexSema, PredictedReadsPerPass);
    if (SmcMutexCount < 2)
      `uvm_fatal(get_type_name(),
                 "the independence leg needs at least two MUTEX instances in the map")
    `uvm_info(get_type_name(),
              $sformatf({"SMC SV-UVM mutex/semaphore (smc_mutex_semaphore_test): MUTEX free=0x%0h ",
                         "taken=0x%0h mask=0x%08h, SEMA mask=0x%08h step=%0d; scenario_seed=%0d"},
                          SmcMutexFree, SmcMutexTaken, SmcMutexMask, SmcSemaMask, sema_step,
                          scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    // 1-2. Acquire, then be denied. Neither leg means anything alone.
    read_field_check(ChkMutexTake, mutex0, SmcMutexMask, SmcMutexFree, "MUTEX0.take");
    read_field_check(ChkMutexDeny, mutex0, SmcMutexMask, SmcMutexTaken, "MUTEX0.deny");

    // 3. A different lock is unaffected while MUTEX[0] is held.
    read_field_check(ChkMutexIndep, mutex1, SmcMutexMask, SmcMutexFree,
                     "MUTEX1.free_while_MUTEX0_held");

    // 4-5. Release and prove it: the read that proves it also re-acquires.
    csr_write(mutex0, 32'h0, "MUTEX0.release");
    read_field_check(ChkMutexRelease, mutex0, SmcMutexMask, SmcMutexFree, "MUTEX0.after_release");

    // 6-7. Hand both locks back free for the next pass.
    csr_write(mutex0, 32'h0, "MUTEX0.cleanup");
    csr_write(mutex1, 32'h0, "MUTEX1.cleanup");

    // 8-12. The signed accumulator: baseline, +N, -N, back to baseline. The
    // baseline expectation of zero is also the check that the previous pass
    // restored it.
    read_field_check(ChkSemaAccum, sema0, SmcSemaMask, 32'h0, "SEMA0.baseline");
    csr_write(sema0, sema_step, "SEMA0.increment");
    read_field_check(ChkSemaAccum, sema0, SmcSemaMask, sema_step & SmcSemaMask, "SEMA0.after_inc");
    csr_write(sema0, sema_step_neg, "SEMA0.decrement");
    read_field_check(ChkSemaAccum, sema0, SmcSemaMask, 32'h0, "SEMA0.restored");

    check_evidence(ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses), 64'(ExpectedAccesses));
    finalize_evidence();
  endtask

  // Read one CSR and compare only the bits the RDL gives the register a field
  // for. csr_read already records CHK-CSR-RESP for the response itself.
  protected task read_field_check(string check_id, bit [63:0] addr, bit [31:0] mask,
                                  bit [31:0] expected, string label);
    bit [31:0] observed;
    csr_read(addr, observed, label);
    check_evidence(check_id, label, 64'(observed & mask), 64'(expected & mask), $sformatf(
                   "addr=0x%0h raw=0x%08h mask=0x%08h", addr, observed, mask));
  endtask

endclass : smc_mutex_semaphore_test_seq
