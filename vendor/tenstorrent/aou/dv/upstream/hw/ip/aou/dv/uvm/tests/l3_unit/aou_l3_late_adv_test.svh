// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: © 2026 Tenstorrent USA Inc

// Credits that cross the final DeactivateAck. DISABLED is a die's own state
// (AoU v0.8 8.2): the die sending the last DeactivateAck is DISABLED at once,
// the die receiving it only when it arrives, and until then it may still send
// request credits (8.4). Both models advertise until they are DISABLED
// (aou_l3_cfg::late_adv) and hold back some request credit to send behind
// their own DeactivateReq (late_adv_hold), so it races the peer's final
// DeactivateAck. The link has 20 cycles of flight time, about five flits, so
// the race is not decided by a single cycle. Two rounds: A deactivates, so B's
// late credits cross A's final DeactivateAck on the PL stream; then B
// deactivates, so A's late credits cross B's final DeactivateAck on the LP
// stream. Neither AOU_FDI_CHECKER nor the receiving model may
// report them, the checker must have seen some each way, and the next
// activation must start from the fresh advertisement alone: a receiver that
// counted late credits would overrun its peer there (AOU-R16,
// VIOL_CRD_UNDERFLOW).
class aou_l3_late_adv_test extends aou_l3_unit_env_test;
  `uvm_component_utils(aou_l3_late_adv_test)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    rounds = 2;
    cfg_a.late_adv_hold = 31;
    cfg_b.late_adv_hold = 31;
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    link.latency = 20;
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    bring_up();
    traffic();
    a.deactivate();
    b.wait_state(AOU_LS_DISABLED);
    idle(100);
    bring_up();
    traffic();
    b.deactivate();
    a.wait_state(AOU_LS_DISABLED);
    idle(100);
    phase.drop_objection(this);
  endtask

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    expect_true(chk.total() == 0, $sformatf("no rule findings (%s)", chk.summary()));
    expect_true(fdi_chk.late_adv_flits[1] > 0,
                "B's credits crossed A's final DeactivateAck at the checker");
    expect_true(fdi_chk.late_adv_flits[0] > 0,
                "A's credits crossed B's final DeactivateAck at the checker");
  endfunction
endclass
