// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AVSBus CRC3
//
//-----------------------------------------------------------------------------

module avsbus_crc3 (
  input  logic [31:0] i_msg,
  output logic [2:0]  o_crc,
  output logic        o_check_good
);
  //timeunit 1ns;
  //timeprecision 1ps;


  assign o_crc[2]=i_msg[30]^i_msg[27]^i_msg[26]^i_msg[25]^i_msg[23]^i_msg[20]^i_msg[19]^i_msg[18]^i_msg[16]^i_msg[13]^i_msg[12]^i_msg[11]^i_msg[9]^i_msg[6]^i_msg[5]^i_msg[4]^i_msg[2];
  assign o_crc[1]=i_msg[31]^i_msg[29]^i_msg[26]^i_msg[25]^i_msg[24]^i_msg[22]^i_msg[19]^i_msg[18]^i_msg[17]^i_msg[15]^i_msg[12]^i_msg[11]^i_msg[10]^i_msg[8]^i_msg[5]^i_msg[4]^i_msg[3]^i_msg[1];
  assign o_crc[0]=i_msg[31]^i_msg[28]^i_msg[27]^i_msg[26]^i_msg[24]^i_msg[21]^i_msg[20]^i_msg[19]^i_msg[17]^i_msg[14]^i_msg[13]^i_msg[12]^i_msg[10]^i_msg[7]^i_msg[6]^i_msg[5]^i_msg[3]^i_msg[0];

  assign o_check_good = ~|o_crc;

endmodule
