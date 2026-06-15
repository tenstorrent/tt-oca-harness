<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: efuse_mmr
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/efuse/regs/efuse.rdl
-->

## efuse_mmr address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x70

|Offset|       Identifier      |Name|
|------|-----------------------|----|
| 0x00 |   RMA_SIP_TOKEN_I[0]  |  — |
| 0x04 |   RMA_SIP_TOKEN_I[1]  |  — |
| 0x08 |   RMA_SIP_TOKEN_I[2]  |  — |
| 0x0C |   RMA_SIP_TOKEN_I[3]  |  — |
| 0x10 |   RMA_SIP_TOKEN_I[4]  |  — |
| 0x14 |   RMA_SIP_TOKEN_I[5]  |  — |
| 0x18 |   RMA_SIP_TOKEN_I[6]  |  — |
| 0x1C |   RMA_SIP_TOKEN_I[7]  |  — |
| 0x20 | RMA_CHIPLET_TOKEN_I[0]|  — |
| 0x24 | RMA_CHIPLET_TOKEN_I[1]|  — |
| 0x28 | RMA_CHIPLET_TOKEN_I[2]|  — |
| 0x2C | RMA_CHIPLET_TOKEN_I[3]|  — |
| 0x30 | RMA_CHIPLET_TOKEN_I[4]|  — |
| 0x34 | RMA_CHIPLET_TOKEN_I[5]|  — |
| 0x38 | RMA_CHIPLET_TOKEN_I[6]|  — |
| 0x3C | RMA_CHIPLET_TOKEN_I[7]|  — |
| 0x40 | SEC_DISABLE_TOKEN_I[0]|  — |
| 0x44 | SEC_DISABLE_TOKEN_I[1]|  — |
| 0x48 | SEC_DISABLE_TOKEN_I[2]|  — |
| 0x4C | SEC_DISABLE_TOKEN_I[3]|  — |
| 0x50 | SEC_DISABLE_TOKEN_I[4]|  — |
| 0x54 | SEC_DISABLE_TOKEN_I[5]|  — |
| 0x58 | SEC_DISABLE_TOKEN_I[6]|  — |
| 0x5C | SEC_DISABLE_TOKEN_I[7]|  — |
| 0x60 |       TOKEN_EOP       |  — |
| 0x64 |  RMA_SIP_TOKEN_MATCH  |  — |
| 0x68 |RMA_CHIPLET_TOKEN_MATCH|  — |
| 0x6C |SEC_DISABLE_TOKEN_MATCH|  — |

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0xC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x10
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x14
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x18
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_SIP_TOKEN_I register

- Absolute Address: 0x1C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x24
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x28
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x2C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x30
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x34
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x38
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### RMA_CHIPLET_TOKEN_I register

- Absolute Address: 0x3C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable RMA token word. The assembled token is hashed and compared against the fused value to authorize lifecycle (LC) state transitions.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of RMA_*_TOKEN, hashed, and compared with fused value to allow LC to change states.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x44
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x48
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x4C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x50
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x54
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x58
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### SEC_DISABLE_TOKEN_I register

- Absolute Address: 0x5C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>Software-writeable security-disable token word. The assembled token is hashed and compared against the post-silicon injected value to authorize security_disable.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   token  |  rw  |  —  |  — |

#### token field

<p>Portion of writeable version of SEC_DISABLE_TOKEN, hashed, and compared with the post silicon injected values to allow security_disable.</p>

### TOKEN_EOP register

- Absolute Address: 0x60
- Base Offset: 0x60
- Size: 0x4

<p>Token end-of-packet control. Writing the per-token go bit signals that all token words have been written and triggers a pulse to begin token hashing.</p>

|Bits|       Identifier      |Access|Reset|Name|
|----|-----------------------|------|-----|----|
|  0 |    rma_sip_token_go   |   w  | 0x0 |  — |
|  8 |  rma_chiplet_token_go |   w  | 0x0 |  — |
| 16 |secure_disable_token_go|   w  | 0x0 |  — |

#### rma_sip_token_go field

<p>Write 1 to indicate that all token data has been written; this generates a pulse to begin token hashing.</p>

#### rma_chiplet_token_go field

<p>Write 1 to indicate that all token data has been written; this generates a pulse to begin token hashing.</p>

#### secure_disable_token_go field

<p>Write 1 to indicate that all token data has been written; this generates a pulse to begin token hashing.</p>

### RMA_SIP_TOKEN_MATCH register

- Absolute Address: 0x64
- Base Offset: 0x64
- Size: 0x4

<p>Token match status. Reports the result of the token hash comparison (match, mismatch, or error).</p>

|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
| 5:0|token_match_status|   r  | 0x0 |  — |

#### token_match_status field

<p>Store the status of the token match.  Match = 6'b010101, Mismatch = 6'b101010, Error = 6'b111111</p>

### RMA_CHIPLET_TOKEN_MATCH register

- Absolute Address: 0x68
- Base Offset: 0x68
- Size: 0x4

<p>Token match status. Reports the result of the token hash comparison (match, mismatch, or error).</p>

|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
| 5:0|token_match_status|   r  | 0x0 |  — |

#### token_match_status field

<p>Store the status of the token match.  Match = 6'b010101, Mismatch = 6'b101010, Error = 6'b111111</p>

### SEC_DISABLE_TOKEN_MATCH register

- Absolute Address: 0x6C
- Base Offset: 0x6C
- Size: 0x4

<p>Token match status. Reports the result of the token hash comparison (match, mismatch, or error).</p>

|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
| 5:0|token_match_status|   r  | 0x0 |  — |

#### token_match_status field

<p>Store the status of the token match.  Match = 6'b010101, Mismatch = 6'b101010, Error = 6'b111111</p>
