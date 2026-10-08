// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// smu_wrapper VCS covergroup exclusions, applied with -elfile at report time.
// Format Version: 2
// ExclMode: default
//
// Generated from urg's `-dump full_exclusions group` template of the merged
// database; regenerate rather than edit. README.md beside this file states what each class
// drops and why; the ANNOTATION before each class repeats the reason.
//==================================================

ANNOTATION: "SMU-WRAPPER-GROUP-VENDORED-I3C: the target-FSM bus-event covergroup the chipsalliance I3C core declares in i3c_target_fsm.sv, one per controller. The wrapper bench reaches the six controllers through the SMC only; their internals are graded by hw/ip/i3ccore_wrap/dv, and the SMU's own view of them is the cov/sv points."
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[0].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[1].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[2].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[3].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[4].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
CHECKSUM: "1886092696 1325688841"
covergroup smu_wrapper_uvm_top.u_dut.u_smu.u_smc.u_smc_peripherals.u_i3ccore_wrapper.gen_i3c_inst[5].u_i3c_wrapper.u_i3c.xcontroller.xcontroller_standby.xcontroller_standby_i3c.xi3c_target_fsm::cg_bus_event_fsm_transitions
