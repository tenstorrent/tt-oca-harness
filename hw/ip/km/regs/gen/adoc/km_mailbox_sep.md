<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: km_mailbox_sep
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/km/regs/km_mailbox_sep.rdl
-->

## km_mailbox_sep address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1C

<p>Register interface for SEP host to access mailbox (write to inbound FIFO, read from outbound FIFO)</p>

|Offset|     Identifier    |      Name     |
|------|-------------------|---------------|
| 0x00 |   SEP_WRITE_DATA  |   WRITE_DATA  |
| 0x04 |SEP_WRITE_SEPARATOR|WRITE_SEPARATOR|
| 0x08 |   SEP_READ_DATA   |   READ_DATA   |
| 0x0C |     SEP_STATUS    |     STATUS    |
| 0x10 |   SEP_IRQ_STATUS  |   IRQ_STATUS  |
| 0x14 |   SEP_IRQ_ENABLE  |   IRQ_ENABLE  |
| 0x18 |      SEP_CTRL     |      CTRL     |

### SEP_WRITE_DATA register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Write data to inbound FIFO (SEP→KM messages)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   w  | 0x0 |DATA|

#### data field

<p>32-bit data word to write to inbound FIFO</p>

### SEP_WRITE_SEPARATOR register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Write 1 to set message separator on next inbound (SEP→KM) write. Cleared by hardware when that write completes.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    set   |  rw  | 0x0 | SET|
|31:1|   rsvd   |   r  | 0x0 |RSVD|

#### set field

<p>Write 1 to set message separator on next inbound write. Cleared by hardware when that write completes.</p>

#### rsvd field

<p>Reserved</p>

### SEP_READ_DATA register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Read data from outbound FIFO (KM→SEP messages)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |   r  | 0x0 |DATA|

#### data field

<p>32-bit data word read from outbound FIFO</p>

### SEP_STATUS register

- Absolute Address: 0xC
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

<p>Inbound FIFO is full (cannot write more data)</p>

#### outbound_empty field

<p>Outbound FIFO is empty (no data available for SEP to read)</p>

#### outbound_full field

<p>Outbound FIFO is full</p>

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

### SEP_IRQ_STATUS register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Interrupt status register</p>

|Bits|        Identifier       |  Access |Reset|           Name          |
|----|-------------------------|---------|-----|-------------------------|
|  0 | outbound_read_data_avail|    r    | 0x0 | OUTBOUND_READ_DATA_AVAIL|
|  1 |inbound_write_space_avail|    r    | 0x0 |INBOUND_WRITE_SPACE_AVAIL|
|  2 |     inbound_overflow    |rw, woclr| 0x0 |     INBOUND_OVERFLOW    |
|  3 |    outbound_underflow   |rw, woclr| 0x0 |    OUTBOUND_UNDERFLOW   |
|  4 |      flushed_by_km      |rw, woclr| 0x0 |      FLUSHED_BY_KM      |
|31:5|           rsvd          |    r    | 0x0 |           RSVD          |

#### outbound_read_data_avail field

<p>Outbound FIFO has data available for SEP to read (level-sensitive). 1 = data available, 0 = empty.</p>

#### inbound_write_space_avail field

<p>Inbound FIFO has space available for SEP to write (level-sensitive). 1 = space available, 0 = full.</p>

#### inbound_overflow field

<p>Inbound FIFO overflow detected. Sticky, write 1 to clear.</p>

#### outbound_underflow field

<p>Outbound FIFO underflow detected. Sticky, write 1 to clear.</p>

#### flushed_by_km field

<p>KM performed a mailbox flush. Sticky, write 1 to clear.</p>

#### rsvd field

<p>Reserved</p>

### SEP_IRQ_ENABLE register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt enable register for SEP host</p>

|Bits|         Identifier         |Access|Reset|            Name            |
|----|----------------------------|------|-----|----------------------------|
|  0 | outbound_read_data_avail_en|  rw  | 0x0 | OUTBOUND_READ_DATA_AVAIL_EN|
|  1 |inbound_write_space_avail_en|  rw  | 0x0 |INBOUND_WRITE_SPACE_AVAIL_EN|
|  2 |     inbound_overflow_en    |  rw  | 0x0 |     INBOUND_OVERFLOW_EN    |
|  3 |    outbound_underflow_en   |  rw  | 0x0 |    OUTBOUND_UNDERFLOW_EN   |
|  4 |      flushed_by_km_en      |  rw  | 0x0 |      FLUSHED_BY_KM_EN      |
|31:5|            rsvd            |   r  | 0x0 |            RSVD            |

#### outbound_read_data_avail_en field

<p>Enable interrupt to SEP when outbound FIFO has data available (KM-&gt;SEP messages)</p>

#### inbound_write_space_avail_en field

<p>Enable interrupt to SEP when inbound FIFO has space available (SEP-&gt;KM messages)</p>

#### inbound_overflow_en field

<p>Enable interrupt to SEP when inbound FIFO overflow is detected</p>

#### outbound_underflow_en field

<p>Enable interrupt to SEP when outbound FIFO underflow is detected</p>

#### flushed_by_km_en field

<p>Enable interrupt to SEP when KM performs a mailbox flush</p>

#### rsvd field

<p>Reserved</p>

### SEP_CTRL register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Control register for mailbox behavior configuration</p>

|Bits|       Identifier      |Access|Reset|          Name         |
|----|-----------------------|------|-----|-----------------------|
|  0 | inbound_overflow_resp |  rw  | 0x0 | INBOUND_OVERFLOW_RESP |
|  1 |outbound_underflow_resp|  rw  | 0x0 |OUTBOUND_UNDERFLOW_RESP|
|  2 |         flush         |  rw  | 0x0 |         FLUSH         |
|31:3|          rsvd         |   r  | 0x0 |          RSVD         |

#### inbound_overflow_resp field

<p>Response type for inbound FIFO overflow: 0=SLVERR (default), 1=OKAY</p>

#### outbound_underflow_resp field

<p>Response type for outbound FIFO underflow: 0=SLVERR (default), 1=OKAY</p>

#### flush field

<p>Write 1 to flush all mailbox FIFOs (inbound and outbound). Cleared by hardware when flush completes.</p>

#### rsvd field

<p>Reserved</p>
