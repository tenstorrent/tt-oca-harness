<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: key_manager
  - hw/ip/km/regs/km.rdl
-->

## key_manager address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1B044

<p>Complete memory map for the Key Manager subsystem, including ROM, SRAM,
control/status registers, mailbox, and external crypto engine ports.
This address map is from the perspective of the KM CPU (PicoRV32).</p>

| Offset|   Identifier   |                  Name                  |
|-------|----------------|----------------------------------------|
|0x0D000|       kpv      |     Key and Policy Vault (KM Port)     |
|0x0E000|      kmcsr     |Key Manager Control and Status Registers|
|0x0F000|  drbg_sampler  |              DRBG Sampler              |
|0x10000|   mailbox_km   |       Key Manager Mailbox KM Side      |
|0x18000|otbn_wrapper_key|       OTBN Wrapper Key Registers       |
|0x19000| aes_wrapper_key|        AES Wrapper Key Registers       |
|0x1A000|kmac_wrapper_key|       KMAC Wrapper Key Registers       |
|0x1B000|hmac_wrapper_key|       HMAC Wrapper Key Registers       |

## kpv address map

- Absolute Address: 0xD000
- Base Offset: 0xD000
- Size: 0x888

<p>Key entry storage and KM control registers. Access conditioned by lock_write/lock_use.</p>

|Offset|    Identifier    |       Name       |
|------|------------------|------------------|
| 0x000|   KEY_ENTRY[0]   |     KEY_ENTRY    |
| 0x040|   KEY_ENTRY[1]   |     KEY_ENTRY    |
| 0x080|   KEY_ENTRY[2]   |     KEY_ENTRY    |
| 0x0C0|   KEY_ENTRY[3]   |     KEY_ENTRY    |
| 0x100|   KEY_ENTRY[4]   |     KEY_ENTRY    |
| 0x140|   KEY_ENTRY[5]   |     KEY_ENTRY    |
| 0x180|   KEY_ENTRY[6]   |     KEY_ENTRY    |
| 0x1C0|   KEY_ENTRY[7]   |     KEY_ENTRY    |
| 0x200|   KEY_ENTRY[8]   |     KEY_ENTRY    |
| 0x240|   KEY_ENTRY[9]   |     KEY_ENTRY    |
| 0x280|   KEY_ENTRY[10]  |     KEY_ENTRY    |
| 0x2C0|   KEY_ENTRY[11]  |     KEY_ENTRY    |
| 0x300|   KEY_ENTRY[12]  |     KEY_ENTRY    |
| 0x340|   KEY_ENTRY[13]  |     KEY_ENTRY    |
| 0x380|   KEY_ENTRY[14]  |     KEY_ENTRY    |
| 0x3C0|   KEY_ENTRY[15]  |     KEY_ENTRY    |
| 0x400|   KEY_ENTRY[16]  |     KEY_ENTRY    |
| 0x440|   KEY_ENTRY[17]  |     KEY_ENTRY    |
| 0x480|   KEY_ENTRY[18]  |     KEY_ENTRY    |
| 0x4C0|   KEY_ENTRY[19]  |     KEY_ENTRY    |
| 0x500|   KEY_ENTRY[20]  |     KEY_ENTRY    |
| 0x540|   KEY_ENTRY[21]  |     KEY_ENTRY    |
| 0x580|   KEY_ENTRY[22]  |     KEY_ENTRY    |
| 0x5C0|   KEY_ENTRY[23]  |     KEY_ENTRY    |
| 0x600|   KEY_ENTRY[24]  |     KEY_ENTRY    |
| 0x640|   KEY_ENTRY[25]  |     KEY_ENTRY    |
| 0x680|   KEY_ENTRY[26]  |     KEY_ENTRY    |
| 0x6C0|   KEY_ENTRY[27]  |     KEY_ENTRY    |
| 0x700|   KEY_ENTRY[28]  |     KEY_ENTRY    |
| 0x740|   KEY_ENTRY[29]  |     KEY_ENTRY    |
| 0x780|   KEY_ENTRY[30]  |     KEY_ENTRY    |
| 0x7C0|   KEY_ENTRY[31]  |     KEY_ENTRY    |
| 0x800|      CTRL[0]     |       CTRL       |
| 0x804|      CTRL[1]     |       CTRL       |
| 0x808|      CTRL[2]     |       CTRL       |
| 0x80C|      CTRL[3]     |       CTRL       |
| 0x810|      CTRL[4]     |       CTRL       |
| 0x814|      CTRL[5]     |       CTRL       |
| 0x818|      CTRL[6]     |       CTRL       |
| 0x81C|      CTRL[7]     |       CTRL       |
| 0x820|      CTRL[8]     |       CTRL       |
| 0x824|      CTRL[9]     |       CTRL       |
| 0x828|     CTRL[10]     |       CTRL       |
| 0x82C|     CTRL[11]     |       CTRL       |
| 0x830|     CTRL[12]     |       CTRL       |
| 0x834|     CTRL[13]     |       CTRL       |
| 0x838|     CTRL[14]     |       CTRL       |
| 0x83C|     CTRL[15]     |       CTRL       |
| 0x840|     CTRL[16]     |       CTRL       |
| 0x844|     CTRL[17]     |       CTRL       |
| 0x848|     CTRL[18]     |       CTRL       |
| 0x84C|     CTRL[19]     |       CTRL       |
| 0x850|     CTRL[20]     |       CTRL       |
| 0x854|     CTRL[21]     |       CTRL       |
| 0x858|     CTRL[22]     |       CTRL       |
| 0x85C|     CTRL[23]     |       CTRL       |
| 0x860|     CTRL[24]     |       CTRL       |
| 0x864|     CTRL[25]     |       CTRL       |
| 0x868|     CTRL[26]     |       CTRL       |
| 0x86C|     CTRL[27]     |       CTRL       |
| 0x870|     CTRL[28]     |       CTRL       |
| 0x874|     CTRL[29]     |       CTRL       |
| 0x878|     CTRL[30]     |       CTRL       |
| 0x87C|     CTRL[31]     |       CTRL       |
| 0x880| KPV_SCRAMBLER_KEY| KPV_SCRAMBLER_KEY|
| 0x884|KPV_SCRAMBLER_CTRL|KPV_SCRAMBLER_CTRL|

## KEY_ENTRY register file

- Absolute Address: 0xD000
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD000
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD004
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD008
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD00C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD010
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD014
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD018
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD01C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD020
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD024
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD028
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD02C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD030
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD034
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD038
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD03C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD040
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD040
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD044
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD048
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD04C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD050
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD054
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD058
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD05C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD060
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD064
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD068
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD06C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD070
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD074
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD078
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD07C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD080
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD080
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD084
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD088
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD08C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD090
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD094
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD098
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD09C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD0C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD0C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD0FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD100
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD100
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD104
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD108
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD10C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD110
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD114
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD118
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD11C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD120
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD124
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD128
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD12C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD130
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD134
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD138
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD13C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD140
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD140
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD144
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD148
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD14C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD150
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD154
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD158
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD15C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD160
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD164
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD168
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD16C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD170
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD174
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD178
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD17C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD180
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD180
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD184
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD188
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD18C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD190
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD194
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD198
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD19C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD1C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD1C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD1FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD200
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD200
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD204
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD208
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD20C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD210
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD214
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD218
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD21C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD220
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD224
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD228
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD22C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD230
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD234
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD238
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD23C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD240
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD240
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD244
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD248
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD24C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD250
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD254
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD258
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD25C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD260
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD264
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD268
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD26C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD270
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD274
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD278
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD27C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD280
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD280
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD284
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD288
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD28C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD290
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD294
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD298
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD29C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD2C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD2C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD2FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD300
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD300
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD304
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD308
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD30C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD310
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD314
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD318
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD31C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD320
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD324
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD328
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD32C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD330
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD334
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD338
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD33C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD340
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD340
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD344
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD348
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD34C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD350
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD354
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD358
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD35C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD360
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD364
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD368
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD36C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD370
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD374
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD378
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD37C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD380
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD380
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD384
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD388
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD38C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD390
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD394
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD398
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD39C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD3C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD3C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD3FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD400
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD400
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD404
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD408
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD40C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD410
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD414
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD418
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD41C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD420
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD424
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD428
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD42C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD430
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD434
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD438
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD43C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD440
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD440
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD444
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD448
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD44C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD450
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD454
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD458
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD45C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD460
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD464
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD468
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD46C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD470
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD474
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD478
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD47C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD480
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD480
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD484
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD488
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD48C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD490
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD494
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD498
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD49C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD4C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD4C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD4FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD500
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD500
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD504
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD508
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD50C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD510
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD514
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD518
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD51C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD520
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD524
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD528
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD52C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD530
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD534
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD538
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD53C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD540
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD540
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD544
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD548
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD54C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD550
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD554
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD558
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD55C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD560
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD564
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD568
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD56C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD570
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD574
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD578
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD57C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD580
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD580
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD584
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD588
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD58C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD590
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD594
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD598
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD59C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD5C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD5C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD5FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD600
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD600
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD604
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD608
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD60C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD610
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD614
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD618
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD61C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD620
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD624
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD628
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD62C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD630
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD634
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD638
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD63C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD640
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD640
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD644
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD648
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD64C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD650
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD654
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD658
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD65C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD660
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD664
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD668
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD66C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD670
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD674
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD678
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD67C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD680
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD680
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD684
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD688
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD68C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD690
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD694
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD698
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD69C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD6C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD6C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD6FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD700
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD700
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD704
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD708
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD70C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD710
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD714
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD718
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD71C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD720
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD724
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD728
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD72C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD730
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD734
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD738
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD73C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD740
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD740
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD744
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD748
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD74C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD750
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD754
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD758
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD75C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD760
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD764
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD768
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD76C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD770
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD774
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD778
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD77C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD780
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD780
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD784
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD788
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD78C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD790
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD794
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD798
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD79C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7A0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7A4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7A8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7AC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7B0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7B4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7B8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7BC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

## KEY_ENTRY register file

- Absolute Address: 0xD7C0
- Base Offset: 0x0
- Size: 0x40
- Array Dimensions: [32]
- Array Stride: 0x40
- Total Size: 0x800

<p>One key entry (16 x 32-bit words = 512 bits)</p>

|Offset|Identifier|  Name  |
|------|----------|--------|
| 0x00 |  WORD[0] |KEY_WORD|
| 0x04 |  WORD[1] |KEY_WORD|
| 0x08 |  WORD[2] |KEY_WORD|
| 0x0C |  WORD[3] |KEY_WORD|
| 0x10 |  WORD[4] |KEY_WORD|
| 0x14 |  WORD[5] |KEY_WORD|
| 0x18 |  WORD[6] |KEY_WORD|
| 0x1C |  WORD[7] |KEY_WORD|
| 0x20 |  WORD[8] |KEY_WORD|
| 0x24 |  WORD[9] |KEY_WORD|
| 0x28 | WORD[10] |KEY_WORD|
| 0x2C | WORD[11] |KEY_WORD|
| 0x30 | WORD[12] |KEY_WORD|
| 0x34 | WORD[13] |KEY_WORD|
| 0x38 | WORD[14] |KEY_WORD|
| 0x3C | WORD[15] |KEY_WORD|

### WORD register

- Absolute Address: 0xD7C0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7C4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7C8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7CC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7D0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7D4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7D8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7DC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7E0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7E4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7E8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7EC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7F0
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7F4
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7F8
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### WORD register

- Absolute Address: 0xD7FC
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>One 32-bit word of a key entry (512-bit key = 16 words). No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |DATA|

#### data field

<p>32-bit key data word. No reset for security; power-up value undefined.
Actual storage is in km_kpv_regfile; CSR field is a protocol placeholder.</p>

### CTRL register

- Absolute Address: 0xD800
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD804
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD808
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD80C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD810
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD814
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD818
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD81C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD820
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD824
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD828
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD82C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD830
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD834
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD838
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD83C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD840
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD844
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD848
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD84C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD850
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD854
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD858
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD85C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD860
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD864
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD868
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD86C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD870
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD874
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD878
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### CTRL register

- Absolute Address: 0xD87C
- Base Offset: 0x800
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Per-slot control: lock bits (W1S), Extend, Dest_valid, Last_dword</p>

| Bits|Identifier|  Access |Reset|   Name   |
|-----|----------|---------|-----|----------|
|  0  |lock_write|rw, woset| 0x0 |LOCK_WRITE|
|  1  | lock_use |rw, woset| 0x0 | LOCK_USE |
|  2  |unlock_sep|rw, woset| 0x0 |UNLOCK_SEP|
|  3  |  rsvd_3  |    r    | 0x0 |  RSVD_3  |
| 6:4 |  extend  |    rw   | 0x0 |  EXTEND  |
| 8:7 | rsvd_8_7 |    r    | 0x0 | RSVD_8_7 |
| 16:9|dest_valid|    rw   | 0x0 |DEST_VALID|
|20:17|last_dword|    rw   | 0x0 |LAST_DWORD|
|31:21|rsvd_31_21|    r    | 0x0 |RSVD_31_21|

#### lock_write field

<p>Prevents KM write to this key entry data and control until reset. Read-any, write-1-only.</p>

#### lock_use field

<p>Prevents KM read of this key entry data until reset. Read-any, write-1-only.</p>

#### unlock_sep field

<p>Allows SEP (KPVLP) to write this slot when lock_write==0. Read-any, write-1-only.</p>

#### rsvd_3 field

<p>Reserved</p>

#### extend field

<p>Zero-indexed number of additional slots for wide keys. Firmware enforced.</p>

#### rsvd_8_7 field

<p>Reserved</p>

#### dest_valid field

<p>Which crypto block may consume this key. Firmware enforced.</p>

#### last_dword field

<p>Last valid key word index [0,15]. Hardware returns 0 for reads beyond this.</p>

#### rsvd_31_21 field

<p>Reserved</p>

### KPV_SCRAMBLER_KEY register

- Absolute Address: 0xD880
- Base Offset: 0x880
- Size: 0x4

<p>32-bit key for KPV key entry scrambling. No reset; powers up random. Locked when KPV_SCRAMBLER_CTRL.LOCK=1.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|    key   |  rw  |  —  | KEY|

#### key field

<p>Scrambler key. No reset for security. HW clears to 0 on wipe via hwclr (FR-0000-143).</p>

### KPV_SCRAMBLER_CTRL register

- Absolute Address: 0xD884
- Base Offset: 0x884
- Size: 0x4

<p>KPV scrambler enable and lock. Reset to 0 on KM reset. LOCK is write-one-only.</p>

|Bits|Identifier|  Access |Reset| Name |
|----|----------|---------|-----|------|
|  0 |  enable  |    rw   | 0x0 |ENABLE|
|  1 |   lock   |rw, woset| 0x0 | LOCK |
|31:2|   rsvd   |    r    | 0x0 | RSVD |

#### enable field

<p>1 = scramble key entry data on write, descramble on read; 0 = passthrough.</p>

#### lock field

<p>Write-one-only. When 1, key and ENABLE cannot be modified until KM reset.</p>

#### rsvd field

<p>Reserved</p>

## kmcsr address map

- Absolute Address: 0xE000
- Base Offset: 0xE000
- Size: 0x200

<p>Control and status registers for the Key Manager MVP subsystem</p>

|Offset|        Identifier       |           Name          |
|------|-------------------------|-------------------------|
| 0x000|         VERSION         |         VERSION         |
| 0x004|           CTRL          |           CTRL          |
| 0x008|      SOFT_RST_CODE      |      SOFT_RST_CODE      |
| 0x00C|        IRQ_STATUS       |        IRQ_STATUS       |
| 0x010|        IRQ_ENABLE       |        IRQ_ENABLE       |
| 0x014|      SCRAMBLER_KEY      |      SCRAMBLER_KEY      |
| 0x018|      SCRAMBLER_CTRL     |      SCRAMBLER_CTRL     |
| 0x01C|        SRAM_LOCK        |        SRAM_LOCK        |
| 0x020|         IRQ_SET         |         IRQ_SET         |
| 0x024|SRAM_WRITE_LOCK_VIOLATION|SRAM_WRITE_LOCK_VIOLATION|
| 0x028|     RECOVERABLE_ERR     |     RECOVERABLE_ERR     |
| 0x02C|       BOOT_STATUS       |       BOOT_STATUS       |
| 0x030|      OTP_LIFE_CYCLE     |      OTP_LIFE_CYCLE     |
| 0x034|    OTP_DEMOTION_STATE   |    OTP_DEMOTION_STATE   |
| 0x038|    OTP_CHIPLET_UID_0    |   OTP_CHIPLET_UID_BYTE  |
| 0x03C|    OTP_CHIPLET_UID_1    |   OTP_CHIPLET_UID_BYTE  |
| 0x040|    OTP_CHIPLET_UID_2    |   OTP_CHIPLET_UID_BYTE  |
| 0x044|    OTP_CHIPLET_UID_3    |   OTP_CHIPLET_UID_BYTE  |
| 0x048|    OTP_CHIPLET_UID_4    |   OTP_CHIPLET_UID_BYTE  |
| 0x04C|    OTP_CHIPLET_UID_5    |   OTP_CHIPLET_UID_BYTE  |
| 0x050|    OTP_CHIPLET_UID_6    |   OTP_CHIPLET_UID_BYTE  |
| 0x054|    OTP_CHIPLET_UID_7    |   OTP_CHIPLET_UID_BYTE  |
| 0x058|    OTP_CHIPLET_UID_8    |   OTP_CHIPLET_UID_BYTE  |
| 0x05C|    OTP_CHIPLET_UID_9    |   OTP_CHIPLET_UID_BYTE  |
| 0x060|    OTP_CHIPLET_UID_10   |   OTP_CHIPLET_UID_BYTE  |
| 0x064|    OTP_CHIPLET_UID_11   |   OTP_CHIPLET_UID_BYTE  |
| 0x068|    OTP_CHIPLET_UID_12   |   OTP_CHIPLET_UID_BYTE  |
| 0x06C|    OTP_CHIPLET_UID_13   |   OTP_CHIPLET_UID_BYTE  |
| 0x070|    OTP_CHIPLET_UID_14   |   OTP_CHIPLET_UID_BYTE  |
| 0x074|    OTP_CHIPLET_UID_15   |   OTP_CHIPLET_UID_BYTE  |
| 0x078|    OTP_CHIPLET_UID_16   |   OTP_CHIPLET_UID_BYTE  |
| 0x07C|    OTP_CHIPLET_UID_17   |   OTP_CHIPLET_UID_BYTE  |
| 0x080|    OTP_CHIPLET_UID_18   |   OTP_CHIPLET_UID_BYTE  |
| 0x084|    OTP_CHIPLET_UID_19   |   OTP_CHIPLET_UID_BYTE  |
| 0x088|    OTP_CHIPLET_UID_20   |   OTP_CHIPLET_UID_BYTE  |
| 0x08C|    OTP_CHIPLET_UID_21   |   OTP_CHIPLET_UID_BYTE  |
| 0x090|    OTP_CHIPLET_UID_22   |   OTP_CHIPLET_UID_BYTE  |
| 0x094|    OTP_CHIPLET_UID_23   |   OTP_CHIPLET_UID_BYTE  |
| 0x098|    OTP_CHIPLET_UID_24   |   OTP_CHIPLET_UID_BYTE  |
| 0x09C|    OTP_CHIPLET_UID_25   |   OTP_CHIPLET_UID_BYTE  |
| 0x0A0|    OTP_CHIPLET_UID_26   |   OTP_CHIPLET_UID_BYTE  |
| 0x0A4|    OTP_CHIPLET_UID_27   |   OTP_CHIPLET_UID_BYTE  |
| 0x0A8|    OTP_CHIPLET_UID_28   |   OTP_CHIPLET_UID_BYTE  |
| 0x0AC|    OTP_CHIPLET_UID_29   |   OTP_CHIPLET_UID_BYTE  |
| 0x0B0|    OTP_CHIPLET_UID_30   |   OTP_CHIPLET_UID_BYTE  |
| 0x0B4|    OTP_CHIPLET_UID_31   |   OTP_CHIPLET_UID_BYTE  |
| 0x0B8|      IRQ_ENTRY_ADDR     |      IRQ_ENTRY_ADDR     |
| 0x0BC|      IRQ_ENTRY_LOCK     |      IRQ_ENTRY_LOCK     |
| 0x100|         VUART_TX        |         VUART_TX        |
| 0x104|         VUART_RX        |         VUART_RX        |
| 0x108|       VUART_STATUS      |       VUART_STATUS      |
| 0x110|        TB_RESULT        |        TB_RESULT        |
| 0x114|       TB_SIGNATURE      |       TB_SIGNATURE      |
| 0x118|        TB_ERRCODE       |        TB_ERRCODE       |
| 0x11C|        TB_SUBTEST       |        TB_SUBTEST       |
| 0x120|          TB_CMD         |          TB_CMD         |
| 0x124|        TB_CMD_ARG       |        TB_CMD_ARG       |
| 0x128|      TB_CMD_STATUS      |      TB_CMD_STATUS      |
| 0x12C|      TB_CMD_RESULT      |      TB_CMD_RESULT      |
| 0x1FC|          DEBUG          |          DEBUG          |

### VERSION register

- Absolute Address: 0xE000
- Base Offset: 0x0
- Size: 0x4

<p>Hardware version register (semantic versioning: major.minor.patch)</p>

| Bits|Identifier|Access|Reset| Name|
|-----|----------|------|-----|-----|
| 7:0 |   patch  |   r  | 0x0 |PATCH|
| 15:8|   minor  |   r  | 0x0 |MINOR|
|23:16|   major  |   r  | 0x1 |MAJOR|
|31:24|   rsvd   |   r  | 0x0 | RSVD|

#### patch field

<p>Patch version number</p>

#### minor field

<p>Minor version number</p>

#### major field

<p>Major version number</p>

#### rsvd field

<p>Reserved; must read as zero</p>

### CTRL register

- Absolute Address: 0xE004
- Base Offset: 0x4
- Size: 0x4

<p>Control register (reserved for future use)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   rsvd   |   r  | 0x0 |RSVD|

#### rsvd field

<p>Reserved</p>

### SOFT_RST_CODE register

- Absolute Address: 0xE008
- Base Offset: 0x8
- Size: 0x4

<p>Software reset code register. Write 0x53525354 ('SRST') to trigger soft reset. Any other value has no effect.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   code   |  rw  | 0x0 |CODE|

#### code field

<p>32-bit reset code. Write 0x53525354 to trigger soft reset.</p>

### IRQ_STATUS register

- Absolute Address: 0xE00C
- Base Offset: 0xC
- Size: 0x4

<p>Interrupt status register. Sticky bits cleared by writing 1.</p>

|Bits|     Identifier    |  Access |Reset|        Name       |
|----|-------------------|---------|-----|-------------------|
|  0 |   rom_parity_err  |rw, woclr| 0x0 |   ROM_PARITY_ERR  |
|  1 |  sram_parity_err  |rw, woclr| 0x0 |  SRAM_PARITY_ERR  |
|  2 |   rom_write_err   |rw, woclr| 0x0 |   ROM_WRITE_ERR   |
|  3 |sram_write_lock_err|rw, woclr| 0x0 |SRAM_WRITE_LOCK_ERR|
|  4 |     axi_slverr    |rw, woclr| 0x0 |     AXI_SLVERR    |
|  5 |     axi_decerr    |rw, woclr| 0x0 |     AXI_DECERR    |
|  6 |      drbg_err     |rw, woclr| 0x0 |      DRBG_ERR     |
|  7 |     wipe_state    |rw, woclr| 0x0 |     WIPE_STATE    |
|31:8|        rsvd       |    r    | 0x0 |        RSVD       |

#### rom_parity_err field

<p>ROM parity error detected. Sticky, write 1 to clear.</p>

#### sram_parity_err field

<p>SRAM parity error detected. Sticky, write 1 to clear.</p>

#### rom_write_err field

<p>ROM write attempt detected (ROM is read-only). Sticky, write 1 to clear.</p>

#### sram_write_lock_err field

<p>SRAM write attempt to a write-locked region detected. Sticky, write 1 to clear.</p>

#### axi_slverr field

<p>AXI SLVERR (slave error) response detected on CPU bus transaction. Sticky, write 1 to clear.</p>

#### axi_decerr field

<p>AXI DECERR (decode error) response detected on CPU bus transaction. Sticky, write 1 to clear.</p>

#### drbg_err field

<p>DRBG Sampler error (timeout or AXI-Stream error). Sticky, write 1 to clear.</p>

#### wipe_state field

<p>Wipe state event (rising edge of wipe_state input). Sticky, write 1 to clear.</p>

#### rsvd field

<p>Reserved</p>

### IRQ_ENABLE register

- Absolute Address: 0xE010
- Base Offset: 0x10
- Size: 0x4

<p>Interrupt enable/mask register</p>

|Bits|    Identifier    |Access|Reset|       Name       |
|----|------------------|------|-----|------------------|
|  0 |   rom_parity_en  |  rw  | 0x0 |   ROM_PARITY_EN  |
|  1 |  sram_parity_en  |  rw  | 0x0 |  SRAM_PARITY_EN  |
|  2 |   rom_write_en   |  rw  | 0x0 |   ROM_WRITE_EN   |
|  3 |sram_write_lock_en|  rw  | 0x0 |SRAM_WRITE_LOCK_EN|
|  4 |   axi_slverr_en  |  rw  | 0x0 |   AXI_SLVERR_EN  |
|  5 |   axi_decerr_en  |  rw  | 0x0 |   AXI_DECERR_EN  |
|  6 |    drbg_err_en   |  rw  | 0x0 |    DRBG_ERR_EN   |
|  7 |   wipe_state_en  |  rw  | 0x0 |   WIPE_STATE_EN  |
|31:8|       rsvd       |   r  | 0x0 |       RSVD       |

#### rom_parity_en field

<p>Enable ROM parity error interrupt</p>

#### sram_parity_en field

<p>Enable SRAM parity error interrupt</p>

#### rom_write_en field

<p>Enable ROM write error interrupt</p>

#### sram_write_lock_en field

<p>Enable SRAM write-lock violation interrupt</p>

#### axi_slverr_en field

<p>Enable AXI SLVERR error interrupt</p>

#### axi_decerr_en field

<p>Enable AXI DECERR error interrupt</p>

#### drbg_err_en field

<p>Enable DRBG Sampler error interrupt</p>

#### wipe_state_en field

<p>Enable wipe state interrupt</p>

#### rsvd field

<p>Reserved</p>

### SCRAMBLER_KEY register

- Absolute Address: 0xE014
- Base Offset: 0x14
- Size: 0x4

<p>32-bit scrambler key for SRAM address/data scrambling. When locked: writes ignored, reads return 0. No reset; powers up random.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|    key   |  rw  |  —  | KEY|

#### key field

<p>Scrambler key value. Not readable when SCRAMBLER_CTRL.LOCK=1 (returns 0). No reset for security; power-up value undefined.</p>

### SCRAMBLER_CTRL register

- Absolute Address: 0xE018
- Base Offset: 0x18
- Size: 0x4

<p>Scrambler control register</p>

|Bits|Identifier|Access|Reset| Name |
|----|----------|------|-----|------|
|  0 |  enable  |  rw  | 0x0 |ENABLE|
|  1 |   lock   |  rw  | 0x0 | LOCK |
|31:2|   rsvd   |   r  | 0x0 | RSVD |

#### enable field

<p>Enable SRAM scrambling. When 0, data passes through unmodified. Locked when LOCK=1 (security requirement).</p>

#### lock field

<p>Lock scrambler key and enable bit. Once set, key and enable cannot be modified until reset. Write-once (0-&gt;1 only). Security requirement: prevents disabling scrambling after key provisioning.</p>

#### rsvd field

<p>Reserved</p>

### SRAM_LOCK register

- Absolute Address: 0xE01C
- Base Offset: 0x1C
- Size: 0x4

<p>SRAM write-lock bits. Bit<i>=1 locks region i (512 bytes each, 32 regions). Write-1-only: writing 1 sets the bit, writing 0 has no effect. Cleared only by full reset.</p>

|Bits|Identifier|  Access |Reset|   Name  |
|----|----------|---------|-----|---------|
|31:0| lock_bits|rw, woset| 0x0 |LOCK_BITS|

#### lock_bits field

<p>One bit per 512-byte SRAM region. Region 0 = 0x4000-0x41FF, region 31 = 0x7E00-0x7FFF. Write 1 to lock; 0 has no effect.</p>

### IRQ_SET register

- Absolute Address: 0xE020
- Base Offset: 0x20
- Size: 0x4

<p>Interrupt set register. Write 1 to trigger corresponding interrupt (for ISR testing). Write-only, reads return 0.</p>

|Bits|       Identifier      |Access|Reset|          Name         |
|----|-----------------------|------|-----|-----------------------|
|  0 |   rom_parity_err_set  |   w  | 0x0 |   ROM_PARITY_ERR_SET  |
|  1 |  sram_parity_err_set  |   w  | 0x0 |  SRAM_PARITY_ERR_SET  |
|  2 |   rom_write_err_set   |   w  | 0x0 |   ROM_WRITE_ERR_SET   |
|  3 |sram_write_lock_err_set|   w  | 0x0 |SRAM_WRITE_LOCK_ERR_SET|
|  4 |     axi_slverr_set    |   w  | 0x0 |     AXI_SLVERR_SET    |
|  5 |     axi_decerr_set    |   w  | 0x0 |     AXI_DECERR_SET    |
|  6 |      drbg_err_set     |   w  | 0x0 |      DRBG_ERR_SET     |
|  7 |     wipe_state_set    |   w  | 0x0 |     WIPE_STATE_SET    |
|31:8|          rsvd         |   w  | 0x0 |          RSVD         |

#### rom_parity_err_set field

<p>Write 1 to set IRQ_STATUS.ROM_PARITY_ERR (triggers ROM parity interrupt for testing)</p>

#### sram_parity_err_set field

<p>Write 1 to set IRQ_STATUS.SRAM_PARITY_ERR (triggers SRAM parity interrupt for testing)</p>

#### rom_write_err_set field

<p>Write 1 to set IRQ_STATUS.ROM_WRITE_ERR (triggers ROM write interrupt for testing)</p>

#### sram_write_lock_err_set field

<p>Write 1 to set IRQ_STATUS.SRAM_WRITE_LOCK_ERR (triggers SRAM write-lock interrupt for testing)</p>

#### axi_slverr_set field

<p>Write 1 to set IRQ_STATUS.AXI_SLVERR (triggers AXI SLVERR interrupt for testing)</p>

#### axi_decerr_set field

<p>Write 1 to set IRQ_STATUS.AXI_DECERR (triggers AXI DECERR interrupt for testing)</p>

#### drbg_err_set field

<p>Write 1 to set IRQ_STATUS.DRBG_ERR (triggers DRBG Sampler interrupt for testing)</p>

#### wipe_state_set field

<p>Write 1 to set IRQ_STATUS.WIPE_STATE (triggers wipe state interrupt for testing)</p>

#### rsvd field

<p>Reserved (write-only; reads trigger SLVERR via err_if_bad_rw)</p>

### SRAM_WRITE_LOCK_VIOLATION register

- Absolute Address: 0xE024
- Base Offset: 0x24
- Size: 0x4

<p>Which SRAM region(s) had write attempts while locked. Bit<i>=region i. Sticky, write 1 to clear each bit.</p>

|Bits|  Identifier  |  Access |Reset|     Name     |
|----|--------------|---------|-----|--------------|
|31:0|violation_bits|rw, woclr| 0x0 |VIOLATION_BITS|

#### violation_bits field

<p>Bit<i>=1 if region i had attempted write while locked. Sticky, write 1 to clear each bit.</p>

### RECOVERABLE_ERR register

- Absolute Address: 0xE028
- Base Offset: 0x28
- Size: 0x4

<p>Recoverable error status. Firmware writes 1 to set (after recovering in ISR), writes 0 to clear (e.g. when SEP requests clear). Drives recoverable error event output.</p>

|Bits|   Identifier  |Access|Reset|      Name     |
|----|---------------|------|-----|---------------|
|  0 |recoverable_err|  rw  | 0x0 |RECOVERABLE_ERR|
|31:1|      rsvd     |   r  | 0x0 |      RSVD     |

#### recoverable_err field

<p>1 = recoverable fault occurred and was handled by ISR; 0 = clear. Write 1 to set, write 0 to clear.</p>

#### rsvd field

<p>Reserved</p>

### BOOT_STATUS register

- Absolute Address: 0xE02C
- Base Offset: 0x2C
- Size: 0x4

<p>Boot status. Firmware writes 1 to COLD_BOOT_DONE after cold-boot init completes; bit remains set until next cold reset.</p>

|Bits|  Identifier  |  Access |Reset|     Name     |
|----|--------------|---------|-----|--------------|
|  0 |cold_boot_done|rw, woset| 0x0 |COLD_BOOT_DONE|
|31:1|     rsvd     |    r    | 0x0 |     RSVD     |

#### cold_boot_done field

<p>Write-1-only: set by ROM firmware at end of cold boot. Reads 0 after cold reset; reads 1 after firmware sets it. Sticky until next cold reset (preserved across warm resets).</p>

#### rsvd field

<p>Reserved</p>

### OTP_LIFE_CYCLE register

- Absolute Address: 0xE030
- Base Offset: 0x30
- Size: 0x4

<p>Life cycle state. 8-bit (4-bit value differentially encoded). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit life cycle state from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_DEMOTION_STATE register

- Absolute Address: 0xE034
- Base Offset: 0x34
- Size: 0x4

<p>Demotion state. 2-bit, differentially encoded. Read-through from OTP port; no reset.</p>

|Bits|  Identifier  |Access|Reset| Name|
|----|--------------|------|-----|-----|
| 1:0|demote_1_value|   r  |  —  |VALUE|
| 3:2|demote_2_value|   r  |  —  |VALUE|
|31:4|     rsvd     |   r  | 0x0 | RSVD|

#### demote_1_value field

<p>2-bit demotion 1 state from OTP. No reset; power-up value undefined.</p>

#### demote_2_value field

<p>2-bit demotion 2 state from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_0 register

- Absolute Address: 0xE038
- Base Offset: 0x38
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_1 register

- Absolute Address: 0xE03C
- Base Offset: 0x3C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_2 register

- Absolute Address: 0xE040
- Base Offset: 0x40
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_3 register

- Absolute Address: 0xE044
- Base Offset: 0x44
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_4 register

- Absolute Address: 0xE048
- Base Offset: 0x48
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_5 register

- Absolute Address: 0xE04C
- Base Offset: 0x4C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_6 register

- Absolute Address: 0xE050
- Base Offset: 0x50
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_7 register

- Absolute Address: 0xE054
- Base Offset: 0x54
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_8 register

- Absolute Address: 0xE058
- Base Offset: 0x58
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_9 register

- Absolute Address: 0xE05C
- Base Offset: 0x5C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_10 register

- Absolute Address: 0xE060
- Base Offset: 0x60
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_11 register

- Absolute Address: 0xE064
- Base Offset: 0x64
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_12 register

- Absolute Address: 0xE068
- Base Offset: 0x68
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_13 register

- Absolute Address: 0xE06C
- Base Offset: 0x6C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_14 register

- Absolute Address: 0xE070
- Base Offset: 0x70
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_15 register

- Absolute Address: 0xE074
- Base Offset: 0x74
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_16 register

- Absolute Address: 0xE078
- Base Offset: 0x78
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_17 register

- Absolute Address: 0xE07C
- Base Offset: 0x7C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_18 register

- Absolute Address: 0xE080
- Base Offset: 0x80
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_19 register

- Absolute Address: 0xE084
- Base Offset: 0x84
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_20 register

- Absolute Address: 0xE088
- Base Offset: 0x88
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_21 register

- Absolute Address: 0xE08C
- Base Offset: 0x8C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_22 register

- Absolute Address: 0xE090
- Base Offset: 0x90
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_23 register

- Absolute Address: 0xE094
- Base Offset: 0x94
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_24 register

- Absolute Address: 0xE098
- Base Offset: 0x98
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_25 register

- Absolute Address: 0xE09C
- Base Offset: 0x9C
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_26 register

- Absolute Address: 0xE0A0
- Base Offset: 0xA0
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_27 register

- Absolute Address: 0xE0A4
- Base Offset: 0xA4
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_28 register

- Absolute Address: 0xE0A8
- Base Offset: 0xA8
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_29 register

- Absolute Address: 0xE0AC
- Base Offset: 0xAC
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_30 register

- Absolute Address: 0xE0B0
- Base Offset: 0xB0
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### OTP_CHIPLET_UID_31 register

- Absolute Address: 0xE0B4
- Base Offset: 0xB4
- Size: 0x4

<p>One byte of Device Unique Identifier (256 bits total across 32 regs). Read-through from OTP port; no reset.</p>

|Bits|Identifier|Access|Reset| Name|
|----|----------|------|-----|-----|
| 7:0|   value  |   r  |  —  |VALUE|
|31:8|   rsvd   |   r  | 0x0 | RSVD|

#### value field

<p>8-bit UID byte from OTP. No reset; power-up value undefined.</p>

#### rsvd field

<p>Reserved</p>

### IRQ_ENTRY_ADDR register

- Absolute Address: 0xE0B8
- Base Offset: 0xB8
- Size: 0x4

<p>Effective IRQ entry address for subsequent interrupts. Writable while unlocked; any 32-bit value accepted.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   addr   |  rw  | 0x10|ADDR|

#### addr field

<p>IRQ handler entry PC. Reset matches ROM vector at 0x10. When locked, SW writes do not update storage.</p>

### IRQ_ENTRY_LOCK register

- Absolute Address: 0xE0BC
- Base Offset: 0xBC
- Size: 0x4

<p>Write-one-only lock for IRQ_ENTRY_ADDR. Separate readable register; cleared only on KM reset.</p>

|Bits|Identifier|  Access |Reset|Name|
|----|----------|---------|-----|----|
|  0 |   lock   |rw, woset| 0x0 |LOCK|
|31:1|   rsvd   |    r    | 0x0 |RSVD|

#### lock field

<p>Write 1 to set; write 0 has no effect; sticky until reset.</p>

#### rsvd field

<p>Reserved; reads as zero.</p>

### VUART_TX register

- Absolute Address: 0xE100
- Base Offset: 0x100
- Size: 0x4

<p>Virtual UART transmit register. Write a byte to send to testbench. DATA_VALID is set on write and self-clears.</p>

|Bits|Identifier|Access|Reset|   Name   |
|----|----------|------|-----|----------|
| 7:0|  tx_byte |  rw  | 0x0 |  TX_BYTE |
|30:8|   rsvd0  |   r  | 0x0 |   RSVD0  |
| 31 |data_valid|  rw  | 0x0 |DATA_VALID|

#### tx_byte field

<p>Byte to transmit (write to send character to testbench)</p>

#### rsvd0 field

<p>Reserved</p>

#### data_valid field

<p>Data valid strobe. Set by firmware on write, cleared by hardware after one cycle.</p>

### VUART_RX register

- Absolute Address: 0xE104
- Base Offset: 0x104
- Size: 0x4

<p>Virtual UART receive register. Testbench writes bytes here for firmware to read.</p>

|Bits|Identifier|Access|Reset|   Name   |
|----|----------|------|-----|----------|
| 7:0|  rx_byte |   r  | 0x0 |  RX_BYTE |
|30:8|   rsvd0  |   r  | 0x0 |   RSVD0  |
| 31 |data_valid|   r  | 0x0 |DATA_VALID|

#### rx_byte field

<p>Received byte from testbench</p>

#### rsvd0 field

<p>Reserved</p>

#### data_valid field

<p>RX data valid. Set by testbench, cleared by firmware read.</p>

### VUART_STATUS register

- Absolute Address: 0xE108
- Base Offset: 0x108
- Size: 0x4

<p>Virtual UART status register for flow control</p>

|Bits| Identifier |Access|Reset|    Name    |
|----|------------|------|-----|------------|
|  0 |  tx_ready  |   r  | 0x1 |  TX_READY  |
|  1 |  rx_valid  |   r  | 0x0 |  RX_VALID  |
|  2 |print_enable|   r  | 0x0 |PRINT_ENABLE|
|31:3|    rsvd    |   r  | 0x0 |    RSVD    |

#### tx_ready field

<p>TX ready to accept data (always 1 in simulation)</p>

#### rx_valid field

<p>RX has valid data available</p>

#### print_enable field

<p>Enable VUART printing. Set by testbench to enable printf output. Disabled by default to save simulation time.</p>

#### rsvd field

<p>Reserved</p>

### TB_RESULT register

- Absolute Address: 0xE110
- Base Offset: 0x110
- Size: 0x4

<p>Test result register. Firmware writes 0=fail, 1=pass.</p>

|Bits|Identifier|Access|Reset| Name |
|----|----------|------|-----|------|
|31:0|  result  |  rw  | 0x0 |RESULT|

#### result field

<p>Test result: 0=fail, 1=pass</p>

### TB_SIGNATURE register

- Absolute Address: 0xE114
- Base Offset: 0x114
- Size: 0x4

<p>Test completion signature. Firmware writes 0x600D600D (pass) or 0xBADBADBA (fail).</p>

|Bits|Identifier|Access|Reset|   Name  |
|----|----------|------|-----|---------|
|31:0| signature|  rw  | 0x0 |SIGNATURE|

#### signature field

<p>Completion signature value</p>

### TB_ERRCODE register

- Absolute Address: 0xE118
- Base Offset: 0x118
- Size: 0x4

<p>Test error code register. Firmware writes optional error code for debugging.</p>

|Bits|Identifier|Access|Reset|  Name |
|----|----------|------|-----|-------|
|31:0|  errcode |  rw  | 0x0 |ERRCODE|

#### errcode field

<p>Error code value</p>

### TB_SUBTEST register

- Absolute Address: 0xE11C
- Base Offset: 0x11C
- Size: 0x4

<p>Current subtest number register. Firmware increments for each subtest.</p>

|Bits|Identifier|Access|Reset|  Name |
|----|----------|------|-----|-------|
|31:0|  subtest |  rw  | 0x0 |SUBTEST|

#### subtest field

<p>Current subtest number</p>

### TB_CMD register

- Absolute Address: 0xE120
- Base Offset: 0x120
- Size: 0x4

<p>Testbench command register. Firmware writes command, testbench reads and clears.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|    cmd   |  rw  | 0x0 | CMD|

#### cmd field

<p>Command code (0=NOP, 1=ROM_PARITY_EN, 2=ROM_PARITY_DIS, 3=SRAM_PARITY_EN, 4=SRAM_PARITY_DIS)</p>

### TB_CMD_ARG register

- Absolute Address: 0xE124
- Base Offset: 0x124
- Size: 0x4

<p>Testbench command argument register. Firmware writes optional argument.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|    arg   |  rw  | 0x0 | ARG|

#### arg field

<p>Command argument value</p>

### TB_CMD_STATUS register

- Absolute Address: 0xE128
- Base Offset: 0x128
- Size: 0x4

<p>Testbench command status register. Testbench writes status, firmware reads.</p>

|Bits|Identifier|Access|Reset| Name |
|----|----------|------|-----|------|
|31:0|  status  |  rw  | 0x0 |STATUS|

#### status field

<p>Command status: 0=IDLE, 1=ACK, 0xFFFFFFFF=ERR</p>

### TB_CMD_RESULT register

- Absolute Address: 0xE12C
- Base Offset: 0x12C
- Size: 0x4

<p>Testbench command result register. Testbench writes result value.</p>

|Bits|Identifier|Access|Reset| Name |
|----|----------|------|-----|------|
|31:0|  result  |   r  | 0x0 |RESULT|

#### result field

<p>Command result value</p>

### DEBUG register

- Absolute Address: 0xE1FC
- Base Offset: 0x1FC
- Size: 0x4

<p>Debug register with known constant value for verification</p>

|Bits|Identifier|Access|   Reset  | Name|
|----|----------|------|----------|-----|
|31:0|   magic  |   r  |0xCAFEBEEF|MAGIC|

#### magic field

<p>Magic constant: 0xCAFEBEEF</p>

## drbg_sampler address map

- Absolute Address: 0xF000
- Base Offset: 0xF000
- Size: 0x10

<p>DRBG random data interface and configuration/status registers</p>

|Offset|  Identifier |     Name    |
|------|-------------|-------------|
|  0x0 |     DATA    |     DATA    |
|  0x4 |     CFG     |     CFG     |
|  0x8 |    STATUS   |    STATUS   |
|  0xC |PREFETCH_DATA|PREFETCH_DATA|

### DATA register

- Absolute Address: 0xF000
- Base Offset: 0x0
- Size: 0x4

<p>One word of random data. Read triggers request or returns prefetch. Writes return SLVERR. No reset.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   r  |  —  |DATA|

#### data field

<p>32-bit random data from DRBG. No reset for security; power-up value undefined.</p>

### CFG register

- Absolute Address: 0xF004
- Base Offset: 0x4
- Size: 0x4

<p>Configuration: PREFETCH enable, TIMEOUT cycles for active CPU read.</p>

| Bits|Identifier|Access|Reset|  Name  |
|-----|----------|------|-----|--------|
|  0  | prefetch |  rw  | 0x0 |PREFETCH|
| 15:1|   rsvd   |  rw  | 0x0 |  RSVD  |
|31:16|  timeout |  rw  |0x100| TIMEOUT|

#### prefetch field

<p>Enable prefetch. When 0, prefetch data register is cleared.</p>

#### rsvd field

<p>Reserved</p>

#### timeout field

<p>Cycles to wait for DRBG on active CPU read; 0 = disable. Default 256.</p>

### STATUS register

- Absolute Address: 0xF008
- Base Offset: 0x8
- Size: 0x4

<p>Status: DRBG_READY, PREFETCHED, TIMEOUT_ERR (W1C), STREAM_ERR (W1C), COUNT_BAD, COUNT_GOOD.</p>

| Bits| Identifier|  Access |Reset|    Name   |
|-----|-----------|---------|-----|-----------|
|  0  | drbg_ready|    r    | 0x0 | DRBG_READY|
|  1  | prefetched|    r    | 0x0 | PREFETCHED|
|  2  |timeout_err|rw, woclr| 0x0 |TIMEOUT_ERR|
|  3  | stream_err|rw, woclr| 0x0 | STREAM_ERR|
| 7:4 |    rsvd   |    r    | 0x0 |    RSVD   |
| 15:8| count_bad |    r    | 0x0 | COUNT_BAD |
|31:16| count_good|    r    | 0x0 | COUNT_GOOD|

#### drbg_ready field

<p>TVALID asserted from DRBG</p>

#### prefetched field

<p>Prefetched data available</p>

#### timeout_err field

<p>Set when a DRBG read from the KM CPU times out. Write 1 to clear.</p>

#### stream_err field

<p>Set when there is an error on the DRBG AXI-Stream interface (e.g. TVALID deasserted before TREADY). Write 1 to clear.</p>

#### rsvd field

<p>Reserved</p>

#### count_bad field

<p>Failed transactions (timeout or error). Saturates at 0xFF.</p>

#### count_good field

<p>Successful words transferred to CPU. Saturates at 0xFFFF.</p>

### PREFETCH_DATA register

- Absolute Address: 0xF00C
- Base Offset: 0xC
- Size: 0x4

<p>Prefetched word (read-only, for debugging). Cleared when PREFETCH=0. No reset; power-up undefined.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   r  |  —  |DATA|

#### data field

<p>Prefetched 32-bit random data. No reset for security; power-up value undefined.</p>

## mailbox_km address map

- Absolute Address: 0x10000
- Base Offset: 0x10000
- Size: 0x1C

<p>Register interface for KM CPU to access mailbox (write to outbound FIFO, read from inbound FIFO)</p>

|Offset|    Identifier    |      Name     |
|------|------------------|---------------|
| 0x00 |   KM_WRITE_DATA  |   WRITE_DATA  |
| 0x04 |KM_WRITE_SEPARATOR|WRITE_SEPARATOR|
| 0x08 |   KM_READ_DATA   |   READ_DATA   |
| 0x0C |     KM_STATUS    |     STATUS    |
| 0x10 |   KM_IRQ_STATUS  |   IRQ_STATUS  |
| 0x14 |   KM_IRQ_ENABLE  |   IRQ_ENABLE  |
| 0x18 |      KM_CTRL     |      CTRL     |

### KM_WRITE_DATA register

- Absolute Address: 0x10000
- Base Offset: 0x0
- Size: 0x4

<p>Write data to outbound FIFO (KM→SEP messages)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  | 0x0 |DATA|

#### data field

<p>32-bit data word to write to outbound FIFO</p>

### KM_WRITE_SEPARATOR register

- Absolute Address: 0x10004
- Base Offset: 0x4
- Size: 0x4

<p>Write 1 to set message separator on next outbound (KM→SEP) write. Cleared by hardware when that write completes.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    set   |  rw  | 0x0 | SET|
|31:1|   rsvd   |   r  | 0x0 |RSVD|

#### set field

<p>Write 1 to set message separator on next outbound write. Cleared by hardware when that write completes.</p>

#### rsvd field

<p>Reserved</p>

### KM_READ_DATA register

- Absolute Address: 0x10008
- Base Offset: 0x8
- Size: 0x4

<p>Read data from inbound FIFO (SEP→KM messages)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   r  | 0x0 |DATA|

#### data field

<p>32-bit data word read from inbound FIFO</p>

### KM_STATUS register

- Absolute Address: 0x1000C
- Base Offset: 0xC
- Size: 0x4

<p>FIFO status information</p>

| Bits|    Identifier    |  Access |Reset|       Name       |
|-----|------------------|---------|-----|------------------|
|  0  |   inbound_empty  |    r    | 0x1 |   INBOUND_EMPTY  |
|  1  |   inbound_full   |    r    | 0x0 |   INBOUND_FULL   |
|  2  |  outbound_empty  |    r    | 0x1 |  OUTBOUND_EMPTY  |
|  3  |   outbound_full  |    r    | 0x0 |   OUTBOUND_FULL  |
| 11:4|   inbound_depth  |    r    | 0x0 |   INBOUND_DEPTH  |
|19:12|  outbound_depth  |    r    | 0x0 |  OUTBOUND_DEPTH  |
|  20 | inbound_overflow |rw, woclr| 0x0 | INBOUND_OVERFLOW |
|  21 | outbound_overflow|rw, woclr| 0x0 | OUTBOUND_OVERFLOW|
|  22 | inbound_underflow|rw, woclr| 0x0 | INBOUND_UNDERFLOW|
|  23 |outbound_underflow|rw, woclr| 0x0 |OUTBOUND_UNDERFLOW|
|  24 | inbound_separator|    r    | 0x0 | INBOUND_SEPARATOR|
|  25 |outbound_separator|    r    | 0x0 |OUTBOUND_SEPARATOR|
|31:26|       rsvd       |    r    | 0x0 |       RSVD       |

#### inbound_empty field

<p>Inbound FIFO is empty (no data available for KM to read)</p>

#### inbound_full field

<p>Inbound FIFO is full</p>

#### outbound_empty field

<p>Outbound FIFO is empty (no data available for SEP to read)</p>

#### outbound_full field

<p>Outbound FIFO is full (cannot write more data)</p>

#### inbound_depth field

<p>Inbound FIFO fill level (number of words in FIFO)</p>

#### outbound_depth field

<p>Outbound FIFO fill level (number of words in FIFO)</p>

#### inbound_overflow field

<p>Inbound FIFO overflow detected (write attempted when full). Sticky, write 1 to clear.</p>

#### outbound_overflow field

<p>Outbound FIFO overflow detected (write attempted when full). Sticky, write 1 to clear.</p>

#### inbound_underflow field

<p>Inbound FIFO underflow detected (read attempted when empty). Sticky, write 1 to clear.</p>

#### outbound_underflow field

<p>Outbound FIFO underflow detected (read attempted when empty). Sticky, write 1 to clear.</p>

#### inbound_separator field

<p>Message separator: 1 if the last word read from inbound FIFO had the separator bit set (last word of message). Read-only, not sticky.</p>

#### outbound_separator field

<p>Message separator: 1 if the last word read from outbound FIFO had the separator bit set (last word of message). Read-only, not sticky.</p>

#### rsvd field

<p>Reserved</p>

### KM_IRQ_STATUS register

- Absolute Address: 0x10010
- Base Offset: 0x10
- Size: 0x4

<p>Interrupt status register</p>

|Bits|        Identifier        |  Access |Reset|           Name           |
|----|--------------------------|---------|-----|--------------------------|
|  0 |  inbound_read_data_avail |    r    | 0x0 |  INBOUND_READ_DATA_AVAIL |
|  1 |outbound_write_space_avail|    r    | 0x0 |OUTBOUND_WRITE_SPACE_AVAIL|
|  2 |     outbound_overflow    |rw, woclr| 0x0 |     OUTBOUND_OVERFLOW    |
|  3 |     inbound_underflow    |rw, woclr| 0x0 |     INBOUND_UNDERFLOW    |
|  4 |      flushed_by_sep      |rw, woclr| 0x0 |      FLUSHED_BY_SEP      |
|31:5|           rsvd           |    r    | 0x0 |           RSVD           |

#### inbound_read_data_avail field

<p>Inbound FIFO has data available for KM to read (level-sensitive). 1 = data available, 0 = empty.</p>

#### outbound_write_space_avail field

<p>Outbound FIFO has space available for KM to write (level-sensitive). 1 = space available, 0 = full.</p>

#### outbound_overflow field

<p>Outbound FIFO overflow detected. Sticky, write 1 to clear.</p>

#### inbound_underflow field

<p>Inbound FIFO underflow detected. Sticky, write 1 to clear.</p>

#### flushed_by_sep field

<p>SEP performed a mailbox flush. Sticky, write 1 to clear.</p>

#### rsvd field

<p>Reserved</p>

### KM_IRQ_ENABLE register

- Absolute Address: 0x10014
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt enable register for KM CPU</p>

|Bits|          Identifier         |Access|Reset|             Name            |
|----|-----------------------------|------|-----|-----------------------------|
|  0 |  inbound_read_data_avail_en |  rw  | 0x0 |  INBOUND_READ_DATA_AVAIL_EN |
|  1 |outbound_write_space_avail_en|  rw  | 0x0 |OUTBOUND_WRITE_SPACE_AVAIL_EN|
|  2 |     outbound_overflow_en    |  rw  | 0x0 |     OUTBOUND_OVERFLOW_EN    |
|  3 |     inbound_underflow_en    |  rw  | 0x0 |     INBOUND_UNDERFLOW_EN    |
|  4 |      flushed_by_sep_en      |  rw  | 0x0 |      FLUSHED_BY_SEP_EN      |
|31:5|             rsvd            |   r  | 0x0 |             RSVD            |

#### inbound_read_data_avail_en field

<p>Enable interrupt to KM when inbound FIFO has data available (SEP-&gt;KM messages)</p>

#### outbound_write_space_avail_en field

<p>Enable interrupt to KM when outbound FIFO has space available (KM-&gt;SEP messages)</p>

#### outbound_overflow_en field

<p>Enable interrupt to KM when outbound FIFO overflow is detected</p>

#### inbound_underflow_en field

<p>Enable interrupt to KM when inbound FIFO underflow is detected</p>

#### flushed_by_sep_en field

<p>Enable interrupt to KM when SEP performs a mailbox flush</p>

#### rsvd field

<p>Reserved</p>

### KM_CTRL register

- Absolute Address: 0x10018
- Base Offset: 0x18
- Size: 0x4

<p>Control register for mailbox behavior configuration</p>

|Bits|      Identifier      |Access|Reset|         Name         |
|----|----------------------|------|-----|----------------------|
|  0 |outbound_overflow_resp|  rw  | 0x0 |OUTBOUND_OVERFLOW_RESP|
|  1 |inbound_underflow_resp|  rw  | 0x0 |INBOUND_UNDERFLOW_RESP|
|  2 |         flush        |  rw  | 0x0 |         FLUSH        |
|31:3|         rsvd         |   r  | 0x0 |         RSVD         |

#### outbound_overflow_resp field

<p>Response type for outbound FIFO overflow: 0=SLVERR (default), 1=OKAY</p>

#### inbound_underflow_resp field

<p>Response type for inbound FIFO underflow: 0=SLVERR (default), 1=OKAY</p>

#### flush field

<p>Write 1 to flush all mailbox FIFOs (inbound and outbound). Cleared by hardware when flush completes.</p>

#### rsvd field

<p>Reserved</p>

## otbn_wrapper_key address map

- Absolute Address: 0x18000
- Base Offset: 0x18000
- Size: 0x64

<p>Key storage registers for the OTBN sideload interface.
Written by Key Manager CPU, drives keymgr_key_i on the OT OTBN core.</p>

|Offset|  Identifier  |  Name  |
|------|--------------|--------|
| 0x00 | KEY_SHARE0[0]|KEY_WORD|
| 0x04 | KEY_SHARE0[1]|KEY_WORD|
| 0x08 | KEY_SHARE0[2]|KEY_WORD|
| 0x0C | KEY_SHARE0[3]|KEY_WORD|
| 0x10 | KEY_SHARE0[4]|KEY_WORD|
| 0x14 | KEY_SHARE0[5]|KEY_WORD|
| 0x18 | KEY_SHARE0[6]|KEY_WORD|
| 0x1C | KEY_SHARE0[7]|KEY_WORD|
| 0x20 | KEY_SHARE0[8]|KEY_WORD|
| 0x24 | KEY_SHARE0[9]|KEY_WORD|
| 0x28 |KEY_SHARE0[10]|KEY_WORD|
| 0x2C |KEY_SHARE0[11]|KEY_WORD|
| 0x30 | KEY_SHARE1[0]|KEY_WORD|
| 0x34 | KEY_SHARE1[1]|KEY_WORD|
| 0x38 | KEY_SHARE1[2]|KEY_WORD|
| 0x3C | KEY_SHARE1[3]|KEY_WORD|
| 0x40 | KEY_SHARE1[4]|KEY_WORD|
| 0x44 | KEY_SHARE1[5]|KEY_WORD|
| 0x48 | KEY_SHARE1[6]|KEY_WORD|
| 0x4C | KEY_SHARE1[7]|KEY_WORD|
| 0x50 | KEY_SHARE1[8]|KEY_WORD|
| 0x54 | KEY_SHARE1[9]|KEY_WORD|
| 0x58 |KEY_SHARE1[10]|KEY_WORD|
| 0x5C |KEY_SHARE1[11]|KEY_WORD|
| 0x60 |   KEY_CTRL   |KEY_CTRL|

### KEY_SHARE0 register

- Absolute Address: 0x18000
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18004
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18008
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1800C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18010
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18014
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18018
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1801C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18020
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18024
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x18028
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1802C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18030
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18034
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18038
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1803C
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18040
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18044
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18048
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1804C
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18050
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18054
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x18058
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1805C
- Base Offset: 0x30
- Size: 0x4
- Array Dimensions: [12]
- Array Stride: 0x4
- Total Size: 0x30

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_CTRL register

- Absolute Address: 0x18060
- Base Offset: 0x60
- Size: 0x4

<p>Key control register. Writing KEY_VALID=1 asserts the sideload
valid signal to the OTBN core.</p>

|Bits|Identifier|Access|Reset|   Name  |
|----|----------|------|-----|---------|
|  0 | key_valid|  rw  | 0x0 |KEY_VALID|
|31:1|   rsvd   |   r  | 0x0 |   RSVD  |

#### key_valid field

<p>When 1, asserts keymgr_key_i.valid to indicate key is loaded.
Write 0 to invalidate the current key.</p>

#### rsvd field

<p>Reserved</p>

## aes_wrapper_key address map

- Absolute Address: 0x19000
- Base Offset: 0x19000
- Size: 0x44

<p>Key storage registers for the AES sideload interface.
Written by Key Manager CPU, drives keymgr_key_i on the OT AES core.</p>

|Offset|  Identifier |  Name  |
|------|-------------|--------|
| 0x00 |KEY_SHARE0[0]|KEY_WORD|
| 0x04 |KEY_SHARE0[1]|KEY_WORD|
| 0x08 |KEY_SHARE0[2]|KEY_WORD|
| 0x0C |KEY_SHARE0[3]|KEY_WORD|
| 0x10 |KEY_SHARE0[4]|KEY_WORD|
| 0x14 |KEY_SHARE0[5]|KEY_WORD|
| 0x18 |KEY_SHARE0[6]|KEY_WORD|
| 0x1C |KEY_SHARE0[7]|KEY_WORD|
| 0x20 |KEY_SHARE1[0]|KEY_WORD|
| 0x24 |KEY_SHARE1[1]|KEY_WORD|
| 0x28 |KEY_SHARE1[2]|KEY_WORD|
| 0x2C |KEY_SHARE1[3]|KEY_WORD|
| 0x30 |KEY_SHARE1[4]|KEY_WORD|
| 0x34 |KEY_SHARE1[5]|KEY_WORD|
| 0x38 |KEY_SHARE1[6]|KEY_WORD|
| 0x3C |KEY_SHARE1[7]|KEY_WORD|
| 0x40 |   KEY_CTRL  |KEY_CTRL|

### KEY_SHARE0 register

- Absolute Address: 0x19000
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x19004
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x19008
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1900C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x19010
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x19014
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x19018
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1901C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19020
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19024
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19028
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1902C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19030
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19034
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x19038
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1903C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_CTRL register

- Absolute Address: 0x19040
- Base Offset: 0x40
- Size: 0x4

<p>Key control register. Writing KEY_VALID=1 asserts the sideload
valid signal to the AES core.</p>

|Bits|Identifier|Access|Reset|   Name  |
|----|----------|------|-----|---------|
|  0 | key_valid|  rw  | 0x0 |KEY_VALID|
|31:1|   rsvd   |   r  | 0x0 |   RSVD  |

#### key_valid field

<p>When 1, asserts keymgr_key_i.valid to indicate key is loaded.
Write 0 to invalidate the current key.</p>

#### rsvd field

<p>Reserved</p>

## kmac_wrapper_key address map

- Absolute Address: 0x1A000
- Base Offset: 0x1A000
- Size: 0x44

<p>Key storage registers for the KMAC sideload interface.
Written by Key Manager CPU, drives keymgr_key_i on the OT KMAC core.</p>

|Offset|  Identifier |  Name  |
|------|-------------|--------|
| 0x00 |KEY_SHARE0[0]|KEY_WORD|
| 0x04 |KEY_SHARE0[1]|KEY_WORD|
| 0x08 |KEY_SHARE0[2]|KEY_WORD|
| 0x0C |KEY_SHARE0[3]|KEY_WORD|
| 0x10 |KEY_SHARE0[4]|KEY_WORD|
| 0x14 |KEY_SHARE0[5]|KEY_WORD|
| 0x18 |KEY_SHARE0[6]|KEY_WORD|
| 0x1C |KEY_SHARE0[7]|KEY_WORD|
| 0x20 |KEY_SHARE1[0]|KEY_WORD|
| 0x24 |KEY_SHARE1[1]|KEY_WORD|
| 0x28 |KEY_SHARE1[2]|KEY_WORD|
| 0x2C |KEY_SHARE1[3]|KEY_WORD|
| 0x30 |KEY_SHARE1[4]|KEY_WORD|
| 0x34 |KEY_SHARE1[5]|KEY_WORD|
| 0x38 |KEY_SHARE1[6]|KEY_WORD|
| 0x3C |KEY_SHARE1[7]|KEY_WORD|
| 0x40 |   KEY_CTRL  |KEY_CTRL|

### KEY_SHARE0 register

- Absolute Address: 0x1A000
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A004
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A008
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A00C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A010
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A014
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A018
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1A01C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A020
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A024
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A028
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A02C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A030
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A034
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A038
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1A03C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_CTRL register

- Absolute Address: 0x1A040
- Base Offset: 0x40
- Size: 0x4

<p>Key control register. Writing KEY_VALID=1 asserts the sideload
valid signal to the KMAC core.</p>

|Bits|Identifier|Access|Reset|   Name  |
|----|----------|------|-----|---------|
|  0 | key_valid|  rw  | 0x0 |KEY_VALID|
|31:1|   rsvd   |   r  | 0x0 |   RSVD  |

#### key_valid field

<p>When 1, asserts keymgr_key_i.valid to indicate key is loaded.
Write 0 to invalidate the current key.</p>

#### rsvd field

<p>Reserved</p>

## hmac_wrapper_key address map

- Absolute Address: 0x1B000
- Base Offset: 0x1B000
- Size: 0x44

<p>Key storage registers for the HMAC sideload interface.
Written by Key Manager CPU, drives keymgr_key_i on the OT HMAC core.</p>

|Offset|  Identifier |  Name  |
|------|-------------|--------|
| 0x00 |KEY_SHARE0[0]|KEY_WORD|
| 0x04 |KEY_SHARE0[1]|KEY_WORD|
| 0x08 |KEY_SHARE0[2]|KEY_WORD|
| 0x0C |KEY_SHARE0[3]|KEY_WORD|
| 0x10 |KEY_SHARE0[4]|KEY_WORD|
| 0x14 |KEY_SHARE0[5]|KEY_WORD|
| 0x18 |KEY_SHARE0[6]|KEY_WORD|
| 0x1C |KEY_SHARE0[7]|KEY_WORD|
| 0x20 |KEY_SHARE1[0]|KEY_WORD|
| 0x24 |KEY_SHARE1[1]|KEY_WORD|
| 0x28 |KEY_SHARE1[2]|KEY_WORD|
| 0x2C |KEY_SHARE1[3]|KEY_WORD|
| 0x30 |KEY_SHARE1[4]|KEY_WORD|
| 0x34 |KEY_SHARE1[5]|KEY_WORD|
| 0x38 |KEY_SHARE1[6]|KEY_WORD|
| 0x3C |KEY_SHARE1[7]|KEY_WORD|
| 0x40 |   KEY_CTRL  |KEY_CTRL|

### KEY_SHARE0 register

- Absolute Address: 0x1B000
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B004
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B008
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B00C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B010
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B014
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B018
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE0 register

- Absolute Address: 0x1B01C
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B020
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B024
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B028
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B02C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B030
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B034
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B038
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_SHARE1 register

- Absolute Address: 0x1B03C
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [8]
- Array Stride: 0x4
- Total Size: 0x20

<p>One 32-bit word of key data. Write-only; reads return 0.
No reset; powers up with undefined value.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  |  —  |DATA|

#### data field

<p>32-bit key data word. Write-only for security.</p>

### KEY_CTRL register

- Absolute Address: 0x1B040
- Base Offset: 0x40
- Size: 0x4

<p>Key control register. Writing KEY_VALID=1 asserts the sideload
valid signal to the HMAC core.</p>

|Bits|Identifier|Access|Reset|   Name  |
|----|----------|------|-----|---------|
|  0 | key_valid|  rw  | 0x0 |KEY_VALID|
|31:1|   rsvd   |   r  | 0x0 |   RSVD  |

#### key_valid field

<p>When 1, asserts keymgr_key_i.valid to indicate key is loaded.
Write 0 to invalidate the current key.</p>

#### rsvd field

<p>Reserved</p>
