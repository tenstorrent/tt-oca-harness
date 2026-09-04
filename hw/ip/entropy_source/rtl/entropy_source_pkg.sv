// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_source_pkg.sv
 * @brief Package defining entropy source register and data type definitions.
 *
 * @details Provides register address/data width definitions and common type
 *          aliases (reg_addr_t, reg_data_t, reg_strb_t) for entropy source
 *          register access, plus the NRINGS constant specifying the number of
 *          entropy generator lanes.
 */

package entropy_source_pkg;

  localparam int unsigned REG_ADDR_WIDTH =
        entropy_source_reg_pkg::ENTROPY_SOURCE_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  localparam int unsigned NRINGS = 12;

  // ------------------------------------------------------------------------
  // Error / fault aggregation bus.
  //
  // Single named collection point for every error and fault signal in the
  // entropy source. Populated combinationally in entropy_source.sv and used
  // to drive the individual INTR_STATUS sticky bits. This struct is an
  // internal aggregation point; irq_o to the SEP host is the single OR of
  // these bits.
  // ------------------------------------------------------------------------
  typedef struct packed {
    logic health_test_failed;  // |health_status (Rep/APT/Markov)
    logic fifo_error;          // entropy_fifo.security_alert_o
    logic fifo_overflow;       // entropy_fifo.overflow_o
    logic fifo_underflow;      // entropy_fifo.underflow_o
    logic biw_obs_overflow;    // u_biw_obs_fifo.overflow_o (diagnostic tap drop)
    logic noise_obs_overflow;  // u_noise_obs_fifo.overflow_o (raw-collection gap)
    logic es_cntr_err;         // counter-fault escalation -> local_escalate_i
    logic main_sm_alert;       // entropy_src_main_sm.main_sm_alert_o (AlertHang)
    logic main_sm_err;         // entropy_src_main_sm.main_sm_err_o
    logic persistent_failure;  // alert_thresh_fail fired -> main_sm locked
    logic autotune_fail;       // auto-detune retune fired on a HT failure
  } entropy_source_err_bus_t;

endpackage
