/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef TT_SMC_INTERRUPTS_H
#define TT_SMC_INTERRUPTS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// SMC CPU interrupt map (4-core config: NUM_EXT_INTERRUPTS=256, NUM_CPU_INTERRUPTS=328)
//
// cpu_interrupts_o layout (hw/sys/smc/rtl/smc_base.sv):
//   [255:0]   ext_interrupts_i            -> PLIC IDs   1-256
//   [287:256] peripheral_interrupts_i     -> PLIC IDs 257-288
//   [319:288] mailbox_interrupts[31:0]    -> PLIC IDs 289-320
//   [320]     tdr_dbg_ctrl_clocks_stopped -> PLIC ID  321
//   [321]     cla_interrupt               -> PLIC ID  322
//   [327:322] (unused)
//
// PLIC ID = cpu_interrupts_o bit index + 1 (RISC-V PLIC source 0 is reserved)

// SEP mailbox: peripheral_interrupts[7:0] = cpu_interrupts_o[263:256] -> PLIC IDs 257-264
#define SEP_MAILBOX_0_INTERRUPT_ID (257)
#define SEP_MAILBOX_1_INTERRUPT_ID (258)
#define SEP_MAILBOX_2_INTERRUPT_ID (259)
#define SEP_MAILBOX_3_INTERRUPT_ID (260)
#define SEP_MAILBOX_4_INTERRUPT_ID (261)
#define SEP_MAILBOX_5_INTERRUPT_ID (262)
#define SEP_MAILBOX_6_INTERRUPT_ID (263)
#define SEP_MAILBOX_7_INTERRUPT_ID (264)

// Telemetry: peripheral_interrupts[10:8] = cpu_interrupts_o[266:264] -> PLIC IDs 265-267
#define NOC_O_TELEMETRY_INTERRUPT_ID (265)
#define NOC_M_TELEMETRY_INTERRUPT_ID (266)
#define NOC_N_TELEMETRY_INTERRUPT_ID (267)

// NDM reset: peripheral_interrupts[11] = cpu_interrupts_o[267] -> PLIC ID 268
#define NDMRESET_INTERRUPT_ID (268)

// I3C: peripheral_interrupts[17:12] = cpu_interrupts_o[273:268] -> PLIC IDs 269-274
#define I3C_0_INTERRUPT_ID (269)
#define I3C_1_INTERRUPT_ID (270)
#define I3C_2_INTERRUPT_ID (271)
#define I3C_3_INTERRUPT_ID (272)
#define I3C_4_INTERRUPT_ID (273)
#define I3C_5_INTERRUPT_ID (274)

// UART: peripheral_interrupts[21:18] = cpu_interrupts_o[277:274] -> PLIC IDs 275-278
// Each bit is the OR of uart_irq, uart_err, and log_engine_irq for that UART instance.
#define UART_0_INTERRUPT_ID (275)
#define UART_1_INTERRUPT_ID (276)
#define UART_2_INTERRUPT_ID (277)
#define UART_3_INTERRUPT_ID (278)

// AVS: peripheral_interrupts[22] = cpu_interrupts_o[278] -> PLIC ID 279
#define AVS_INTERRUPT_ID (279)

// I2C: peripheral_interrupts[25:23] = cpu_interrupts_o[281:279] -> PLIC IDs 280-282
#define I2C_0_INTERRUPT_ID (280)
#define I2C_1_INTERRUPT_ID (281)
#define I2C_2_INTERRUPT_ID (282)

// SEP WDT: peripheral_interrupts[26] = cpu_interrupts_o[282] -> PLIC ID 283
// (~rst_ext_wdt_ni, active-low inverted before routing)
#define SEP_WDT_INTERRUPT_ID (283)

// Locked field access: peripheral_interrupts[27] = cpu_interrupts_o[283] -> PLIC ID 284
#define LOCKED_FIELD_ACCESS_INTERRUPT_ID (284)

// AXI hang detector: peripheral_interrupts[30] = cpu_interrupts_o[286] -> PLIC ID 287
// One line shared by all three detectors (sys_axi, sep_axi, data_accel).
#define AXI_HANG_DETECTOR_INTERRUPT_ID (287)

// SMC inbound mailbox: cpu_interrupts_o[319:288] -> PLIC IDs 289-320
#define MAILBOX_0_INTERRUPT_ID (289)
#define MAILBOX_1_INTERRUPT_ID (290)
#define MAILBOX_2_INTERRUPT_ID (291)
#define MAILBOX_3_INTERRUPT_ID (292)
#define MAILBOX_4_INTERRUPT_ID (293)
#define MAILBOX_5_INTERRUPT_ID (294)
#define MAILBOX_6_INTERRUPT_ID (295)
#define MAILBOX_7_INTERRUPT_ID (296)
#define MAILBOX_8_INTERRUPT_ID (297)
#define MAILBOX_9_INTERRUPT_ID (298)
#define MAILBOX_10_INTERRUPT_ID (299)
#define MAILBOX_11_INTERRUPT_ID (300)
#define MAILBOX_12_INTERRUPT_ID (301)
#define MAILBOX_13_INTERRUPT_ID (302)
#define MAILBOX_14_INTERRUPT_ID (303)
#define MAILBOX_15_INTERRUPT_ID (304)
#define MAILBOX_16_INTERRUPT_ID (305)
#define MAILBOX_17_INTERRUPT_ID (306)
#define MAILBOX_18_INTERRUPT_ID (307)
#define MAILBOX_19_INTERRUPT_ID (308)
#define MAILBOX_20_INTERRUPT_ID (309)
#define MAILBOX_21_INTERRUPT_ID (310)
#define MAILBOX_22_INTERRUPT_ID (311)
#define MAILBOX_23_INTERRUPT_ID (312)
#define MAILBOX_24_INTERRUPT_ID (313)
#define MAILBOX_25_INTERRUPT_ID (314)
#define MAILBOX_26_INTERRUPT_ID (315)
#define MAILBOX_27_INTERRUPT_ID (316)
#define MAILBOX_28_INTERRUPT_ID (317)
#define MAILBOX_29_INTERRUPT_ID (318)
#define MAILBOX_30_INTERRUPT_ID (319)
#define MAILBOX_31_INTERRUPT_ID (320)

// Internal interrupts
// TDR clocks stopped by CLA: cpu_interrupts_o[320] -> PLIC ID 321
#define TDR_CLOCKS_STOPPED_INTERRUPT_ID (321)
// DFD CLA interrupt: cpu_interrupts_o[321] -> PLIC ID 322
#define CLA_INTERRUPT_ID (322)

void plic_init(uint8_t core_id);

void global_interrupt_enable(void);

#ifdef __cplusplus
}
#endif

#endif /* TT_SMC_INTERRUPTS_H */
