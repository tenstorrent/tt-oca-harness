// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Compute and check the AVSBus CRC-3 over a 32-bit message.
//
// crc_o is the residue over msg_i; check_good_o is high when that residue is zero.

module avsbus_crc3 (
  input  logic [31:0] msg_i,                                // Message bits to CRC.
  output logic [2:0]  crc_o,                                // CRC-3 residue.
  output logic        check_good_o                          // High when the residue is zero.
);
  //timeunit 1ns;
  //timeprecision 1ps;


  assign crc_o[2]=msg_i[30]^msg_i[27]^msg_i[26]^msg_i[25]^msg_i[23]^msg_i[20]^msg_i[19]^msg_i[18]^msg_i[16]^msg_i[13]^msg_i[12]^msg_i[11]^msg_i[9]^msg_i[6]^msg_i[5]^msg_i[4]^msg_i[2];
  assign crc_o[1]=msg_i[31]^msg_i[29]^msg_i[26]^msg_i[25]^msg_i[24]^msg_i[22]^msg_i[19]^msg_i[18]^msg_i[17]^msg_i[15]^msg_i[12]^msg_i[11]^msg_i[10]^msg_i[8]^msg_i[5]^msg_i[4]^msg_i[3]^msg_i[1];
  assign crc_o[0]=msg_i[31]^msg_i[28]^msg_i[27]^msg_i[26]^msg_i[24]^msg_i[21]^msg_i[20]^msg_i[19]^msg_i[17]^msg_i[14]^msg_i[13]^msg_i[12]^msg_i[10]^msg_i[7]^msg_i[6]^msg_i[5]^msg_i[3]^msg_i[0];

  assign check_good_o = ~|crc_o;

endmodule
