// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Byte offset -> (bank, entry) for the 4-core CPU scratchpad.
//
// One definition, used by every backdoor that reaches the scratch macros: the
// +smc_scratch_ram_hex image loader in smc_cpu_mem_dv.sv and the peek decodes
// in tb_top.sv. A wrong copy of this map is silent: it loads firmware into
// banks the CPU never fetches from, and every testcase that does not execute
// that firmware still passes.
//
// The mapping is not a flat round-robin. It is read out of the cluster's own
// decode, in two places:
//
//   OCAH4CORECluster_TLXbar_mbus_i1_o33_a32d64s11k1z3u.sv:700-755
//     Bank select. Every one of the 32 requestAIO_0_<n> terms compares the
//     same two fields: address[20:17], which picks one of eight contiguous
//     128 KB groups (values 3..10, base 0x60000), and address[7:6], which
//     picks one of four banks inside that group.
//         bank = 4 * address[19:17]_group + address[7:6]
//
//   OCAH4CORECluster_TLRAM.sv:308,286
//     Entry select, inside the bank the xbar already chose:
//         addr     = address[16:3]
//         RW0_addr = {addr[13:5], addr[2:0]} = {address[16:8], address[5:3]}
//     address[7:6] is absent because it went to the bank select above.
//
// So the interleave granularity is 64 bytes across FOUR banks -- a 256-byte
// cycle -- and the other three bits of bank index come from the top of the
// 1 MB window, not from the stripe counter. A flat "round-robin across all 32
// banks every 64 bytes" model agrees with this only for the first 256 bytes
// and diverges from offset 0x100 onward.
package smc_scratch_map_pkg;

  // 64 data bits + 8 SECDED bits per entry; addresses are byte addresses.
  localparam int unsigned SCRATCH_BYTES_PER_ENTRY = 8;
  // address[7:6]: the stripe that rotates between the four banks of a group.
  localparam int unsigned SCRATCH_BANK_STRIPE_BYTES = 64;
  localparam int unsigned SCRATCH_BANKS_PER_GROUP = 4;
  // address[20:17]: 128 KB per group, eight groups, 1 MB of scratch.
  localparam int unsigned SCRATCH_GROUP_BYTES = 32'h0002_0000;
  localparam int unsigned SCRATCH_ENTRIES_PER_STRIPE =
      SCRATCH_BANK_STRIPE_BYTES / SCRATCH_BYTES_PER_ENTRY;

  // Which of the 32 scratch_ram_intf_req[] ports serves this byte offset.
  // Offsets are relative to the base of the scratch window, so the group index
  // is just the high part of the offset.
  function automatic int unsigned smc_scratch_bank(input int unsigned offset);
    return SCRATCH_BANKS_PER_GROUP * (offset / SCRATCH_GROUP_BYTES)
         + ((offset / SCRATCH_BANK_STRIPE_BYTES) % SCRATCH_BANKS_PER_GROUP);
  endfunction

  // Which entry of that bank. address[16:8] concatenated with address[5:3],
  // written as arithmetic so it reads the same way as the bank function.
  function automatic int unsigned smc_scratch_entry(input int unsigned offset);
    return ((offset % SCRATCH_GROUP_BYTES)
              / (SCRATCH_BANK_STRIPE_BYTES * SCRATCH_BANKS_PER_GROUP))
             * SCRATCH_ENTRIES_PER_STRIPE
         + ((offset % SCRATCH_BANK_STRIPE_BYTES) / SCRATCH_BYTES_PER_ENTRY);
  endfunction

endpackage : smc_scratch_map_pkg
