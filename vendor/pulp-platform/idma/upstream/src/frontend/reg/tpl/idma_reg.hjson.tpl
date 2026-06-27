// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51

// Authors:
// - Michael Rogenmoser <michaero@iis.ee.ethz.ch>
// - Thomas Benz <tbenz@iis.ee.ethz.ch>

{
  name: "idma_${identifier}",
  clock_primary: "clk_i",
  reset_primary: "rst_ni",
  bus_interfaces: [
    { protocol: "reg_iface",
      direction: "device"
    }
  ],
  regwidth: "32",
  param_list: [
${params}
  ],
  registers: [
    { name: "conf",
      desc: "Configuration Register for DMA settings",
      swaccess: "rw",
      hwaccess: "hro",
      fields: [
        { bits: "0",
          name: "decouple_aw",
          desc: "Decouple R-AW"
        },
        { bits: "1",
          name: "decouple_rw",
          desc: "Decouple R-W"
        },
        { bits: "2",
          name: "src_reduce_len",
          desc: "Reduce maximal source burst length"
        },
        { bits: "3",
          name: "dst_reduce_len",
          desc: "Reduce maximal destination burst length"
        }
        { bits: "6:4",
          name: "src_max_llen",
          desc: "Maximal logarithmic source burst length"
        }
        { bits: "9:7",
          name: "dst_max_llen",
          desc: "Maximal logarithmic destination burst length"
        }
        { bits: "${dim_range}",
          name: "enable_nd",
          desc: "ND-extension enabled"
        }
        { bits: "${src_prot_range}",
          name: "src_protocol",
          desc: "Selection of the source protocol"
        }
        { bits: "${dst_prot_range}",
          name: "dst_protocol",
          desc: "Selection of the destination protocol"
        }
      ]
    },
    { multireg:
      { name: "status",
        desc: "DMA Status",
        swaccess: "ro",
        hwaccess: "hwo",
        count: "16",
        cname: "status",
        hwext: "true",
        compact: "false",
        fields: [
          { bits: "9:0",
            name: "busy",
            desc: "DMA busy"
          }
        ]
      }
    },
    { skipto: "0x48" },
    { name: "next_id_0"
      desc: "Next ID 0, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_0",
          desc: "Next ID 0, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x50" },
    { name: "next_id_1"
      desc: "Next ID 1, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_1",
          desc: "Next ID 1, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x58" },
    { name: "next_id_2"
      desc: "Next ID 2, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_2",
          desc: "Next ID 2, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x60" },
    { name: "next_id_3"
      desc: "Next ID 3, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_3",
          desc: "Next ID 3, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x68" },
    { name: "next_id_4"
      desc: "Next ID 4, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_4",
          desc: "Next ID 4, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x70" },
    { name: "next_id_5"
      desc: "Next ID 5, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_5",
          desc: "Next ID 5, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x78" },
    { name: "next_id_6"
      desc: "Next ID 6, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_6",
          desc: "Next ID 6, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x80" },
    { name: "next_id_7"
      desc: "Next ID 7, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_7",
          desc: "Next ID 7, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x88" },
    { name: "next_id_8"
      desc: "Next ID 8, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_8",
          desc: "Next ID 8, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x90" },
    { name: "next_id_9"
      desc: "Next ID 9, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_9",
          desc: "Next ID 9, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0x98" },
    { name: "next_id_10"
      desc: "Next ID 10, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_10",
          desc: "Next ID 10, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xA0" },
    { name: "next_id_11"
      desc: "Next ID 11, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_11",
          desc: "Next ID 11, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xA8" },
    { name: "next_id_12"
      desc: "Next ID 12, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_12",
          desc: "Next ID 12, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xB0" },
    { name: "next_id_13"
      desc: "Next ID 13, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_13",
          desc: "Next ID 13, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xB8" },
    { name: "next_id_14"
      desc: "Next ID 14, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_14",
          desc: "Next ID 14, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xC0" },
    { name: "next_id_15"
      desc: "Next ID 15, launches transfer, returns 0 if transfer not set up properly.",
      swaccess: "ro",
      hwaccess: "hrw",
      hwre: "true",
      hwext: "true",
      fields: [
        { bits: "31:0",
          name: "next_id_15",
          desc: "Next ID 15, launches transfer, returns 0 if transfer not set up properly.",
          resval: "0"
        }
      ]
    },
    { skipto: "0xC8" },
    { multireg:
      { name: "done_id",
        desc: "Get ID of finished transactions.",
        swaccess: "ro",
        hwaccess: "hwo",
        count: "16",
        cname: "done_id",
        hwext: "true",
        fields: [
          { bits: "31:0",
            name: "done_id",
            desc: "Get ID of finished transactions."
          }
        ]
      }
    },
${registers}
  ]
}
