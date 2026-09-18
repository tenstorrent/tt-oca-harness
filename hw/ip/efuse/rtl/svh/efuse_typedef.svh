// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Macros to define Fuse Command Request/Response Structs

`ifndef EFUSE_TYPEDEF_SVH_
`define EFUSE_TYPEDEF_SVH_

////////////////////////////////////////////////////////////////////////////////////////////////////
// Fuse Command Request/Response Structs
////////////////////////////////////////////////////////////////////////////////////////////////////

// Usage Example:
// `EFUSE_COMMAND_REQ_T(fuse_command_req_t, addr_t, data_t, access_length_words_t, command_t)
// `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, data_t)

`define EFUSE_COMMAND_REQ_T(fuse_command_req_t, addr_t, data_t, access_length_words_t, command_t)  \
  typedef struct packed {                                       \
    addr_t                    address;                          \
    logic                     program_data;                     \
    access_length_words_t     access_length_words;              \
    command_t                 command;                          \
    logic                     valid;                            \
  } fuse_command_req_t;

`define EFUSE_COMMAND_RESP_T(fuse_command_resp_t, data_t)       \
  typedef struct packed {                                       \
    data_t              data;                                   \
    logic               status;                                 \
    logic               valid;                                  \
  } fuse_command_resp_t;

`endif
