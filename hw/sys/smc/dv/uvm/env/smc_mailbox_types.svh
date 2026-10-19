// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Mailbox geometry from smc_pkg; offsets, defaults and masks from the register map.
localparam int unsigned SmcMailboxCount = smc_pkg::NumMailboxes;
localparam int unsigned SmcMailboxDepth = smc_pkg::MailboxDepth;
localparam bit [63:0] SmcMailboxBase =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR;
localparam bit [63:0] SmcMailboxStride =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_1_BASE_ADDR - SmcMailboxBase;
localparam bit [63:0] SmcMailboxPeerOffset =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR - SmcMailboxBase;
localparam bit [63:0] SmcMailboxPortBytes =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_SIZE;

typedef enum int unsigned {
  MBX_WRITE_DATA = SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_REG_OFFSET,
  MBX_READ_DATA = SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_REG_OFFSET,
  MBX_STATUS = SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_REG_OFFSET,
  MBX_ERROR = SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_REG_OFFSET,
  MBX_WIRQT = SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_REG_OFFSET,
  MBX_RIRQT = SMC_MAILBOX_OUTBOUND_MAILBOX_0_RIRQT_REG_OFFSET,
  MBX_IRQS = SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_REG_OFFSET,
  MBX_IRQEN = SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_REG_OFFSET,
  MBX_CTRL = SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_REG_OFFSET
} smc_mailbox_reg_e;

function automatic bit [63:0] smc_mailbox_addr(int unsigned mailbox, bit inbound,
                                               smc_mailbox_reg_e reg_kind);
  return SmcMailboxBase + mailbox * SmcMailboxStride +
         (inbound ? SmcMailboxPeerOffset : 0) + int'(reg_kind);
endfunction

function automatic bit smc_mailbox_decode(bit [63:0] addr, output int unsigned mailbox,
                                          output bit inbound, output int unsigned offset);
  bit [63:0] relative;
  if (addr < SmcMailboxBase || addr >= SmcMailboxBase + SmcMailboxCount * SmcMailboxStride)
    return 0;
  relative = addr - SmcMailboxBase;
  mailbox = int'(relative / SmcMailboxStride);
  relative %= SmcMailboxStride;
  inbound = relative >= SmcMailboxPeerOffset;
  offset = int'(relative - (inbound ? SmcMailboxPeerOffset : 0));
  return 1;
endfunction

function automatic bit [63:0] smc_mailbox_mask(int unsigned offset);
  case (offset)
    MBX_READ_DATA, MBX_WRITE_DATA: return AXIL_MAILBOX_READ_DATA_READ_DATA_MASK;
    MBX_STATUS: return AXIL_MAILBOX_STATUS_EMPTY_MASK | AXIL_MAILBOX_STATUS_FULL_MASK |
        AXIL_MAILBOX_STATUS_WRITE_LEVEL_ABOVE_THRESH_MASK |
        AXIL_MAILBOX_STATUS_READ_LEVEL_ABOVE_THRESH_MASK;
    MBX_ERROR: return AXIL_MAILBOX_ERROR_READ_ERROR_MASK | AXIL_MAILBOX_ERROR_WRITE_ERROR_MASK;
    MBX_WIRQT: return AXIL_MAILBOX_WIRQT_WIRQT_MASK;
    MBX_RIRQT: return AXIL_MAILBOX_RIRQT_RIRQT_MASK;
    MBX_IRQS: return AXIL_MAILBOX_IRQS_WTIRQ_MASK | AXIL_MAILBOX_IRQS_RTIRQ_MASK |
        AXIL_MAILBOX_IRQS_EIRQ_MASK;
    MBX_IRQEN: return AXIL_MAILBOX_IRQEN_WTIRQ_MASK | AXIL_MAILBOX_IRQEN_RTIRQ_MASK |
        AXIL_MAILBOX_IRQEN_EIRQ_MASK;
    MBX_CTRL: return AXIL_MAILBOX_CTRL_WFLUSH_MASK | AXIL_MAILBOX_CTRL_RFLUSH_MASK;
    default: return 0;
  endcase
endfunction

function automatic bit [63:0] smc_mailbox_default(smc_mailbox_reg_e reg_kind);
  case (reg_kind)
    MBX_STATUS: return AXIL_MAILBOX_STATUS_REG_DEFAULT;
    MBX_ERROR: return AXIL_MAILBOX_ERROR_REG_DEFAULT;
    MBX_IRQEN: return AXIL_MAILBOX_IRQEN_REG_DEFAULT;
    MBX_WIRQT: return AXIL_MAILBOX_WIRQT_REG_DEFAULT;
    MBX_RIRQT: return AXIL_MAILBOX_RIRQT_REG_DEFAULT;
    MBX_IRQS: return AXIL_MAILBOX_IRQS_REG_DEFAULT;
    default: return 0;
  endcase
endfunction

// Sequential full-width accesses reach comparison regardless of response.
// The model derives responses and side effects from request history, never
// from observed responses. IRQS data and data of reads answered SLVERR
// are not predicted; successful ERROR reads are predicted and clear flags.
function automatic bit smc_is_mailbox_fifo_access(ocah_axi_item t);
  int unsigned mailbox, offset;
  bit inbound;
  if (!smc_mailbox_decode(t.address, mailbox, inbound, offset)) return 0;
  if (offset >= SmcMailboxPortBytes || smc_mailbox_mask(offset) == 0) return 0;
  if (t.direction == OCAH_AXI_DIR_READ && offset == MBX_WRITE_DATA) return 0;
  if (t.direction == OCAH_AXI_DIR_WRITE &&
      (offset == MBX_READ_DATA || offset == MBX_STATUS || offset == MBX_ERROR))
    return 0;
  return t.address % SmcMemBytes == 0 && t.size == SmcMemSize &&
      t.expected_beats == 1 && t.beat_count() == 1 && t.data_words.size() == 1 &&
      (t.direction == OCAH_AXI_DIR_READ ||
       (t.strobes.size() == 1 && t.strobes[0] == 8'hFF));
endfunction
