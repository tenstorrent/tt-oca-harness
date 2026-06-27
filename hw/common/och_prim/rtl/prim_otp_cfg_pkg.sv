// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//--------------------------------------------------
// OTP Configuration Package
//
//--------------------------------------------------
package prim_otp_cfg_pkg;

  typedef struct packed {
    logic test;
  } otp_cfg_t;

  typedef struct packed {
    logic done;
  } otp_cfg_rsp_t;

  parameter otp_cfg_t OTP_CFG_DEFAULT = '0;

endpackage // prim_otp_cfg_pkg
