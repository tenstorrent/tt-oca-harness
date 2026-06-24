<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: secure_dma
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/secure_dma/regs/secure_dma.rdl
-->

## secure_dma address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x150

<p>Register map for the Secure DMA controller. This DMA supports memory-to-memory transfers, inline SHA2 hashing, hardware handshake mode, and interrupt source clearing.</p>

|Offset|        Identifier        |Name|
|------|--------------------------|----|
| 0x000|        INTR_STATE        |  — |
| 0x004|        INTR_ENABLE       |  — |
| 0x008|         INTR_TEST        |  — |
| 0x00C|        ALERT_TEST        |  — |
| 0x010|        SRC_ADDR_LO       |  — |
| 0x014|        SRC_ADDR_HI       |  — |
| 0x018|        DST_ADDR_LO       |  — |
| 0x01C|        DST_ADDR_HI       |  — |
| 0x020|       ADDR_SPACE_ID      |  — |
| 0x024| ENABLED_MEMORY_RANGE_BASE|  — |
| 0x028|ENABLED_MEMORY_RANGE_LIMIT|  — |
| 0x02C|        RANGE_VALID       |  — |
| 0x030|       RANGE_REGWEN       |  — |
| 0x034|        CFG_REGWEN        |  — |
| 0x038|      TOTAL_DATA_SIZE     |  — |
| 0x03C|      CHUNK_DATA_SIZE     |  — |
| 0x040|      TRANSFER_WIDTH      |  — |
| 0x044|          CONTROL         |  — |
| 0x048|        SRC_CONFIG        |  — |
| 0x04C|        DST_CONFIG        |  — |
| 0x050|          STATUS          |  — |
| 0x054|        ERROR_CODE        |  — |
| 0x058|       SHA2_DIGEST_0      |  — |
| 0x05C|       SHA2_DIGEST_1      |  — |
| 0x060|       SHA2_DIGEST_2      |  — |
| 0x064|       SHA2_DIGEST_3      |  — |
| 0x068|       SHA2_DIGEST_4      |  — |
| 0x06C|       SHA2_DIGEST_5      |  — |
| 0x070|       SHA2_DIGEST_6      |  — |
| 0x074|       SHA2_DIGEST_7      |  — |
| 0x078|       SHA2_DIGEST_8      |  — |
| 0x07C|       SHA2_DIGEST_9      |  — |
| 0x080|      SHA2_DIGEST_10      |  — |
| 0x084|      SHA2_DIGEST_11      |  — |
| 0x088|      SHA2_DIGEST_12      |  — |
| 0x08C|      SHA2_DIGEST_13      |  — |
| 0x090|      SHA2_DIGEST_14      |  — |
| 0x094|      SHA2_DIGEST_15      |  — |
| 0x098|   HANDSHAKE_INTR_ENABLE  |  — |
| 0x09C|      CLEAR_INTR_SRC      |  — |
| 0x0A0|      CLEAR_INTR_BUS      |  — |
| 0x0A4|      INTR_SRC_ADDR_0     |  — |
| 0x0A8|      INTR_SRC_ADDR_1     |  — |
| 0x0AC|      INTR_SRC_ADDR_2     |  — |
| 0x0B0|      INTR_SRC_ADDR_3     |  — |
| 0x0B4|      INTR_SRC_ADDR_4     |  — |
| 0x0B8|      INTR_SRC_ADDR_5     |  — |
| 0x0BC|      INTR_SRC_ADDR_6     |  — |
| 0x0C0|      INTR_SRC_ADDR_7     |  — |
| 0x0C4|      INTR_SRC_ADDR_8     |  — |
| 0x0C8|      INTR_SRC_ADDR_9     |  — |
| 0x0CC|     INTR_SRC_ADDR_10     |  — |
| 0x124|     INTR_SRC_WR_VAL_0    |  — |
| 0x128|     INTR_SRC_WR_VAL_1    |  — |
| 0x12C|     INTR_SRC_WR_VAL_2    |  — |
| 0x130|     INTR_SRC_WR_VAL_3    |  — |
| 0x134|     INTR_SRC_WR_VAL_4    |  — |
| 0x138|     INTR_SRC_WR_VAL_5    |  — |
| 0x13C|     INTR_SRC_WR_VAL_6    |  — |
| 0x140|     INTR_SRC_WR_VAL_7    |  — |
| 0x144|     INTR_SRC_WR_VAL_8    |  — |
| 0x148|     INTR_SRC_WR_VAL_9    |  — |
| 0x14C|    INTR_SRC_WR_VAL_10    |  — |

### INTR_STATE register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Interrupt State Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|  0 |   DMA_DONE   |   r  | 0x0 |  — |
|  1 |DMA_CHUNK_DONE|   r  | 0x0 |  — |
|  2 |   DMA_ERROR  |   r  | 0x0 |  — |

#### DMA_DONE field

<p>DMA operation has been completed.</p>

#### DMA_CHUNK_DONE field

<p>Indicates the transfer of a single chunk has been completed.</p>

#### DMA_ERROR field

<p>DMA error has occurred. DMA_STATUS.error_code register shows the details.</p>

### INTR_ENABLE register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|  0 |   DMA_DONE   |  rw  | 0x0 |  — |
|  1 |DMA_CHUNK_DONE|  rw  | 0x0 |  — |
|  2 |   DMA_ERROR  |  rw  | 0x0 |  — |

#### DMA_DONE field

<p>Enable interrupt when INTR_STATE.DMA_DONE is set.</p>

#### DMA_CHUNK_DONE field

<p>Enable interrupt when INTR_STATE.DMA_CHUNK_DONE is set.</p>

#### DMA_ERROR field

<p>Enable interrupt when INTR_STATE.DMA_ERROR is set.</p>

### INTR_TEST register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|  0 |   DMA_DONE   |   w  | 0x0 |  — |
|  1 |DMA_CHUNK_DONE|   w  | 0x0 |  — |
|  2 |   DMA_ERROR  |   w  | 0x0 |  — |

#### DMA_DONE field

<p>Write 1 to force INTR_STATE.DMA_DONE to 1.</p>

#### DMA_CHUNK_DONE field

<p>Write 1 to force INTR_STATE.DMA_CHUNK_DONE to 1.</p>

#### DMA_ERROR field

<p>Write 1 to force INTR_STATE.DMA_ERROR to 1.</p>

### ALERT_TEST register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>Alert Test Register</p>

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |FATAL_FAULT|   w  | 0x0 |  — |

#### FATAL_FAULT field

<p>Write 1 to trigger one alert event of this kind.</p>

### SRC_ADDR_LO register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Lower 32 bits of the physical or virtual address of memory location within SoC memory address map or physical address within OT non-secure memory space. Data is read from this location in a copy operation. The address may be an IO virtual address. Must be aligned to the transfer width. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Lower 32 bits of the source address. Must be aligned to the transfer width.</p>

### SRC_ADDR_HI register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Upper 32 bits of the source address. Must be aligned to the transfer width. Source and destination address must have the same alignment. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Upper 32 bits of the physical or virtual address of memory location within SoC memory address map or physical address within OT non-secure memory space. Must be aligned to the transfer width. Source and destination address must have the same alignment.</p>

### DST_ADDR_LO register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Lower 32 bits of the physical or virtual address of memory location within SoC memory address map or physical address within OT non-secure memory space. Data is written to this location in a copy operation. The address may be an IO virtual address. Must be aligned to the transfer width. Source and destination address must have the same alignment. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Lower 32 bits of the destination address. Must be aligned to the transfer width. Source and destination address must have the same alignment.</p>

### DST_ADDR_HI register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

<p>Upper 32 bits of the destination address. Must be aligned to the transfer width. Source and destination address must have the same alignment. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Upper 32 bits of the physical or virtual address of memory location within SoC memory address map or physical address within OT non-secure memory space. Must be aligned to the transfer width. Source and destination address must have the same alignment.</p>

### ADDR_SPACE_ID register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

<p>Address spaces that source and destination pointers refer to. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 3:0| SRC_ASID |  rw  | 0x7 |  — |
| 7:4| DST_ASID |  rw  | 0x7 |  — |

#### SRC_ASID field

<p>Target address space that the source address pointer refers to.</p>

#### DST_ASID field

<p>Target address space that the destination address pointer refers to.</p>

### ENABLED_MEMORY_RANGE_BASE register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

<p>Base Address to mark the start of the DMA enabled memory range within the OT internal memory space. Register enable: RANGE_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   BASE   |  rw  | 0x0 |  — |

#### BASE field

<p>Base Address to mark the start of the DMA enabled memory range within the OT internal memory space.</p>

### ENABLED_MEMORY_RANGE_LIMIT register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

<p>Limit Address to mark the end of the DMA enabled memory range within the OT internal memory space; address is inclusive. Register enable: RANGE_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   LIMIT  |  rw  | 0x0 |  — |

#### LIMIT field

<p>Limit Address to mark the end of the DMA enabled memory range within the OT internal memory space; inclusive.</p>

### RANGE_VALID register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

<p>Indicates that the ENABLED_MEMORY_RANGE_BASE and _LIMIT registers have been programmed to restrict DMA accesses within the OT internal address space. Register enable: RANGE_REGWEN.</p>

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |RANGE_VALID|  rw  | 0x0 |  — |

#### RANGE_VALID field

<p>Once set the enabled memory base and limit registers are valid.</p>

### RANGE_REGWEN register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

<p>Used to lock the DMA enabled memory range configuration registers.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 3:0|  REGWEN  |  rw  | 0x6 |  — |

#### REGWEN field

<p>Used by firmware to lock the DMA enabled memory range configuration registers from further modification. Once this register is set to kMultiBitBool4False (0x9), it can only be set to kMultiBitBool4True (0x6) through a reset event. Default Value = kMultiBitBool4True (0x6) -&gt; Unlocked at reset. Software can only clear bits (rw0c behavior).</p>

### CFG_REGWEN register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

<p>Indicates whether the configuration registers are locked because the DMA controller is operating. In the idle state, this register is set to kMultiBitBool4True. When the DMA is performing an operation, i.e. the DMA is busy, this register is set to kMultiBitBool4False. During the DMA operation, the CONTROL and STATUS registers remain usable. The comportable registers (the interrupt and alert configuration) are NOT locked during the DMA operation and can still be updated. When the DMA reaches an interrupt or alert condition, it will perform the action according to the current register configuration.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 3:0|  REGWEN  |   r  | 0x6 |  — |

#### REGWEN field

<p>Used by hardware to lock the DMA configuration registers. This register is purely managed by hardware and only software readable.</p>

### TOTAL_DATA_SIZE register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

<p>Total size (in bytes) of the data to be transferred. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   SIZE   |  rw  | 0x0 |  — |

#### SIZE field

<p>Total size (in bytes) of the data to be transferred. The complete transfer operation may consist of multiple chunks of data as specified by the CHUNK_DATA_SIZE register. Minimum: 1 byte. Maximum: May be restricted to a maximum pre-defined size based on OT DMA enabled memory space allocation. Works in conjunction with the TRANSFER_WIDTH register.</p>

### CHUNK_DATA_SIZE register

- Absolute Address: 0x3C
- Base Offset: 0x3C
- Size: 0x4

<p>Number of bytes to be transferred in response to each interrupt/firmware request. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   SIZE   |  rw  | 0x0 |  — |

#### SIZE field

<p>Size (in bytes) for a single DMA transfer. In hardware handshake mode, the DMA reads in chunks of CHUNK_DATA_SIZE from the peripheral. For a single memory transfer CHUNK_DATA_SIZE and TOTAL_DATA_SIZE are set to the same value. Minimum: 1 byte. Maximum: May be restricted to a maximum pre-defined size based on OT DMA enabled memory space allocation. Works in conjunction with the TRANSFER_WIDTH register.</p>

### TRANSFER_WIDTH register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4

<p>Denotes the width of each transaction that the DMA shall issue. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 1:0|   WIDTH  |  rw  | 0x2 |  — |

#### WIDTH field

<p>Denotes the width of each transaction that the DMA shall issue during the data movement. Multiple transactions of this width will be issued until TOTAL_DATA_SIZE bytes have been transferred. Note that firmware may need to set a different value if a receiving IP supports a read / write transaction width that is less than 1 DWORD. This does not affect the wrap-around mechanism. Note that the value 3 for this register represents an invalid configuration that leads to an error.</p>

### CONTROL register

- Absolute Address: 0x44
- Base Offset: 0x44
- Size: 0x4

<p>Control register for DMA data movement.</p>

|Bits|        Identifier       |Access|Reset|Name|
|----|-------------------------|------|-----|----|
| 3:0|          OPCODE         |  rw  | 0x0 |  — |
|  4 |HARDWARE_HANDSHAKE_ENABLE|  rw  | 0x0 |  — |
|  5 |       DIGEST_SWAP       |  rw  | 0x0 |  — |
|  8 |     INITIAL_TRANSFER    |  rw  | 0x0 |  — |
| 27 |          ABORT          |   w  | 0x0 |  — |
| 31 |            GO           |  rw  | 0x0 |  — |

#### OPCODE field

<p>Defines the type of DMA operations.</p>

#### HARDWARE_HANDSHAKE_ENABLE field

<p>Enable hardware handshake mode. Used to clear FIFOs from low speed IO peripherals receiving data, e.g., I3C receive buffer. Listen to an input trigger signal. Read data from source address location. Copy to destination address. Number of bytes specified in size register. Note assumption is the peripheral lowers input once FIFO is cleared. No explicit clearing necessary.</p>

#### DIGEST_SWAP field

<p>Digest register byte swap. If 1 the value in each digest output register is converted to big-endian byte order. This setting does not affect the order of the digest output registers, SHA2_DIGEST_0 still contains the first 4 bytes of the digest.</p>

#### INITIAL_TRANSFER field

<p>Marks the initial transfer to initialize the DMA and SHA engine for one transfer that can span over multiple single DMA transfers. Used for hardware handshake and ordinary transfers, in which multiple transfers contribute to a final digest. Note, for non-handshake transfers with inline hashing mode enabled, this bit must be set to also mark the first transfer.</p>

#### ABORT field

<p>Aborts the DMA operation if this bit is set. Sets the corresponding bit in the status register once abort operation is complete. Any OpenTitan-internal transactions are guaranteed to complete, but there are no guarantees on the SoC interface.</p>

#### GO field

<p>Setting this bit triggers the DMA operation. For normal operation, the DMA engine clears the go bit automatically after the configured operation is complete. For Hardware handshake operation, DMA engine does not auto clear the Go bit. Firmware shall clear the Go bit when it intends to stop the hardware handshake operation.</p>

### SRC_CONFIG register

- Absolute Address: 0x48
- Base Offset: 0x48
- Size: 0x4

<p>Defines the addressing behavior of the DMA for the source address. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | INCREMENT|  rw  | 0x0 |  — |
|  1 |   WRAP   |  rw  | 0x0 |  — |

#### INCREMENT field

<p>Defines the increment behavior after every DMA read. When 0: Source address is not changed. All reads are done from the same address. When 1: Source address is incremented by transfer_width after each read.</p>

#### WRAP field

<p>When 0: Chunks occupy contiguous ascending addresses. When 1: Source address wraps back to the starting address when finishing a chunk.</p>

### DST_CONFIG register

- Absolute Address: 0x4C
- Base Offset: 0x4C
- Size: 0x4

<p>Defines the addressing behavior of the DMA for the destination address. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | INCREMENT|  rw  | 0x0 |  — |
|  1 |   WRAP   |  rw  | 0x0 |  — |

#### INCREMENT field

<p>Defines the increment behavior after every DMA write. When 0: Destination address is not changed. All writes are done to the same address. When 1: Destination address is incremented by transfer_width after each write.</p>

#### WRAP field

<p>When 0: Chunks occupy contiguous ascending addresses. When 1: Destination address wraps back to the starting address when finishing a chunk.</p>

### STATUS register

- Absolute Address: 0x50
- Base Offset: 0x50
- Size: 0x4

<p>Status indication for DMA data movement.</p>

|Bits|    Identifier   |  Access |Reset|Name|
|----|-----------------|---------|-----|----|
|  0 |       BUSY      |    r    | 0x0 |  — |
|  1 |       DONE      |rw, woclr| 0x0 |  — |
|  2 |     ABORTED     |rw, woclr| 0x0 |  — |
|  3 |      ERROR      |rw, woclr| 0x0 |  — |
|  4 |SHA2_DIGEST_VALID|    r    | 0x0 |  — |
|  5 |    CHUNK_DONE   |rw, woclr| 0x0 |  — |

#### BUSY field

<p>DMA operation is active if this bit is set. DMA engine clears this bit when operation is complete. This bit may be set as long as hardware handshake mode is active and triggered.</p>

#### DONE field

<p>Configured DMA operation is complete. Cleared automatically by the hardware when starting a new transfer.</p>

#### ABORTED field

<p>Set once aborted operation drains.</p>

#### ERROR field

<p>Error occurred during the operation. ERROR_CODE register denotes the source of the error.</p>

#### SHA2_DIGEST_VALID field

<p>Indicates whether the SHA2_DIGEST register contains a valid digest. This value is cleared on the initial transfer and set when the digest is written.</p>

#### CHUNK_DONE field

<p>Transfer of a single chunk is complete. Only raised for multi-chunk memory-to-memory transfers. Cleared automatically by the hardware when starting the transfer of a new chunk.</p>

### ERROR_CODE register

- Absolute Address: 0x54
- Base Offset: 0x54
- Size: 0x4

<p>Denotes the source of the operational error. The error is cleared by writing the RW1C STATUS.error register.</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |  SRC_ADDR_ERROR |   r  | 0x0 |  — |
|  1 |  DST_ADDR_ERROR |   r  | 0x0 |  — |
|  2 |   OPCODE_ERROR  |   r  | 0x0 |  — |
|  3 |    SIZE_ERROR   |   r  | 0x0 |  — |
|  4 |    BUS_ERROR    |   r  | 0x0 |  — |
|  5 | BASE_LIMIT_ERROR|   r  | 0x0 |  — |
|  6 |RANGE_VALID_ERROR|   r  | 0x0 |  — |
|  7 |    ASID_ERROR   |   r  | 0x0 |  — |

#### SRC_ADDR_ERROR field

<p>Source address is invalid.</p>

#### DST_ADDR_ERROR field

<p>Destination address is invalid.</p>

#### OPCODE_ERROR field

<p>Opcode is invalid.</p>

#### SIZE_ERROR field

<p>TRANSFER_WIDTH encodes an invalid value, TOTAL_DATA_SIZE or CHUNK_SIZE are zero, or inline hashing is not using 32-bit transfer width</p>

#### BUS_ERROR field

<p>The bus transfer returned an error.</p>

#### BASE_LIMIT_ERROR field

<p>The base and limit addresses contain an invalid value.</p>

#### RANGE_VALID_ERROR field

<p>The DMA enabled memory range is not configured.</p>

#### ASID_ERROR field

<p>The source or destination ASID contains an invalid value.</p>

### SHA2_DIGEST_0 register

- Absolute Address: 0x58
- Base Offset: 0x58
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_1 register

- Absolute Address: 0x5C
- Base Offset: 0x5C
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_2 register

- Absolute Address: 0x60
- Base Offset: 0x60
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_3 register

- Absolute Address: 0x64
- Base Offset: 0x64
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_4 register

- Absolute Address: 0x68
- Base Offset: 0x68
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_5 register

- Absolute Address: 0x6C
- Base Offset: 0x6C
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_6 register

- Absolute Address: 0x70
- Base Offset: 0x70
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_7 register

- Absolute Address: 0x74
- Base Offset: 0x74
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_8 register

- Absolute Address: 0x78
- Base Offset: 0x78
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_9 register

- Absolute Address: 0x7C
- Base Offset: 0x7C
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_10 register

- Absolute Address: 0x80
- Base Offset: 0x80
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_11 register

- Absolute Address: 0x84
- Base Offset: 0x84
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_12 register

- Absolute Address: 0x88
- Base Offset: 0x88
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_13 register

- Absolute Address: 0x8C
- Base Offset: 0x8C
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_14 register

- Absolute Address: 0x90
- Base Offset: 0x90
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### SHA2_DIGEST_15 register

- Absolute Address: 0x94
- Base Offset: 0x94
- Size: 0x4

<p>Digest register for the inline hashing operation. Depending on the used hashing mode, not all registers are used. SHA256: Digest is stored in registers 0 to 7. SHA384: Digest is stored in registers 0 to 11. SHA512: Digest is stored in registers 0 to 15.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>SHA2 digest data</p>

### HANDSHAKE_INTR_ENABLE register

- Absolute Address: 0x98
- Base Offset: 0x98
- Size: 0x4

<p>Enable bits for incoming handshake interrupt wires. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|10:0|   MASK   |  rw  |0x7FF|  — |

#### MASK field

<p>Enable bits for incoming handshake interrupt wires.</p>

### CLEAR_INTR_SRC register

- Absolute Address: 0x9C
- Base Offset: 0x9C
- Size: 0x4

<p>Valid bits for which interrupt sources need clearing. When HANDSHAKE_INTR_ENABLE is non-zero and corresponding lsio_trigger becomes set, DMA issues writes with address from INTR_SRC_ADDR and write value from INTR_SRC_WR_VAL corresponding to each bit set in this register. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|10:0|  SOURCE  |  rw  | 0x0 |  — |

#### SOURCE field

<p>Source N needs interrupt cleared</p>

### CLEAR_INTR_BUS register

- Absolute Address: 0xA0
- Base Offset: 0xA0
- Size: 0x4

<p>Bus selection bit where the clearing command should be performed. 0: CTN/System fabric. 1: OT-internal crossbar. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|10:0|    BUS   |  rw  | 0x0 |  — |

#### BUS field

<p>Bus selection bit for source N.</p>

### INTR_SRC_ADDR_0 register

- Absolute Address: 0xA4
- Base Offset: 0xA4
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_1 register

- Absolute Address: 0xA8
- Base Offset: 0xA8
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_2 register

- Absolute Address: 0xAC
- Base Offset: 0xAC
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_3 register

- Absolute Address: 0xB0
- Base Offset: 0xB0
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_4 register

- Absolute Address: 0xB4
- Base Offset: 0xB4
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_5 register

- Absolute Address: 0xB8
- Base Offset: 0xB8
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_6 register

- Absolute Address: 0xBC
- Base Offset: 0xBC
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_7 register

- Absolute Address: 0xC0
- Base Offset: 0xC0
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_8 register

- Absolute Address: 0xC4
- Base Offset: 0xC4
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_9 register

- Absolute Address: 0xC8
- Base Offset: 0xC8
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_ADDR_10 register

- Absolute Address: 0xCC
- Base Offset: 0xCC
- Size: 0x4

<p>Destination address for interrupt source clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   ADDR   |  rw  | 0x0 |  — |

#### ADDR field

<p>Destination address for interrupt source clearing write.</p>

### INTR_SRC_WR_VAL_0 register

- Absolute Address: 0x124
- Base Offset: 0x124
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_1 register

- Absolute Address: 0x128
- Base Offset: 0x128
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_2 register

- Absolute Address: 0x12C
- Base Offset: 0x12C
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_3 register

- Absolute Address: 0x130
- Base Offset: 0x130
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_4 register

- Absolute Address: 0x134
- Base Offset: 0x134
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_5 register

- Absolute Address: 0x138
- Base Offset: 0x138
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_6 register

- Absolute Address: 0x13C
- Base Offset: 0x13C
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_7 register

- Absolute Address: 0x140
- Base Offset: 0x140
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_8 register

- Absolute Address: 0x144
- Base Offset: 0x144
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_9 register

- Absolute Address: 0x148
- Base Offset: 0x148
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>

### INTR_SRC_WR_VAL_10 register

- Absolute Address: 0x14C
- Base Offset: 0x14C
- Size: 0x4

<p>Write value for interrupt clearing write. Register enable: CFG_REGWEN.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  WR_VAL  |  rw  | 0x0 |  — |

#### WR_VAL field

<p>Write value for interrupt clearing write.</p>
