<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: smc_cla
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/dfd/regs/dfd.rdl
-->

## smc_cla address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8FF8

|Offset|         Identifier        |Name|
|------|---------------------------|----|
|0x0198|         CDbgMuxSel        |  — |
|0x01A0|          CDfdCsr          |  — |
|0x0200|         Timestamp         |  — |
|0x0208|       TimestampSync       |  — |
|0x0210|      TimeStampConfig      |  — |
|0x1000|        Trdstcontrol       |  — |
|0x1004|         Trdstimpl         |  — |
|0x1008|     Trdstinstfeatures     |  — |
|0x11A0|     CDbgDebugTraceCfg     |  — |
|0x3100|     CDbgClaCounter0Cfg    |  — |
|0x3108|     CDbgClaCounter1Cfg    |  — |
|0x3110|     CDbgClaCounter2Cfg    |  — |
|0x3118|     CDbgClaCounter3Cfg    |  — |
|0x3120|       CDbgNode0Eap0       |  — |
|0x3128|       CDbgNode0Eap1       |  — |
|0x3130|       CDbgNode1Eap0       |  — |
|0x3138|       CDbgNode1Eap1       |  — |
|0x3140|       CDbgNode2Eap0       |  — |
|0x3148|       CDbgNode2Eap1       |  — |
|0x3150|       CDbgNode3Eap0       |  — |
|0x3158|       CDbgNode3Eap1       |  — |
|0x3160|      CDbgSignalMask0      |  — |
|0x3168|      CDbgSignalMatch0     |  — |
|0x3170|      CDbgSignalMask1      |  — |
|0x3178|      CDbgSignalMatch1     |  — |
|0x3180|  CDbgSignalEdgeDetectCfg  |  — |
|0x3188|       CDbgEapStatus       |  — |
|0x3190|     CDbgClaCtrlStatus     |  — |
|0x3198|         CDbgRsvd0         |  — |
|0x31A0|         CDbgRsvd1         |  — |
|0x31A8|         CDbgRsvd2         |  — |
|0x31B0|     CDbgTransitionMask    |  — |
|0x31B8|  CDbgTransitionFromValue  |  — |
|0x31C0|   CDbgTransitionToValue   |  — |
|0x31C8|     CDbgOnesCountMask     |  — |
|0x31D0|     CDbgOnesCountValue    |  — |
|0x31D8|       CDbgAnyChange       |  — |
|0x31E0|CDbgSignalSnapshotNode0Eap0|  — |
|0x31E8|CDbgSignalSnapshotNode0Eap1|  — |
|0x31F0|CDbgSignalSnapshotNode1Eap0|  — |
|0x31F8|CDbgSignalSnapshotNode1Eap1|  — |
|0x3200|CDbgSignalSnapshotNode2Eap0|  — |
|0x3208|CDbgSignalSnapshotNode2Eap1|  — |
|0x3210|CDbgSignalSnapshotNode3Eap0|  — |
|0x3218|CDbgSignalSnapshotNode3Eap1|  — |
|0x3220|      CDbgClaTimeMatch     |  — |
|0x3228|      CDbgSignalMask2      |  — |
|0x3230|      CDbgSignalMatch2     |  — |
|0x3238|      CDbgSignalMask3      |  — |
|0x3240|      CDbgSignalMatch3     |  — |
|0x3248|       CDbgNode0Eap2       |  — |
|0x3250|       CDbgNode0Eap3       |  — |
|0x3258|       CDbgNode1Eap2       |  — |
|0x3260|       CDbgNode1Eap3       |  — |
|0x3268|       CDbgNode2Eap2       |  — |
|0x3270|       CDbgNode2Eap3       |  — |
|0x3278|       CDbgNode3Eap2       |  — |
|0x3280|       CDbgNode3Eap3       |  — |
|0x3288|CDbgSignalSnapshotNode0Eap2|  — |
|0x3290|CDbgSignalSnapshotNode0Eap3|  — |
|0x3298|CDbgSignalSnapshotNode1Eap2|  — |
|0x32A0|CDbgSignalSnapshotNode1Eap3|  — |
|0x32A8|CDbgSignalSnapshotNode2Eap2|  — |
|0x32B0|CDbgSignalSnapshotNode2Eap3|  — |
|0x32B8|CDbgSignalSnapshotNode3Eap2|  — |
|0x32C0|CDbgSignalSnapshotNode3Eap3|  — |
|0x32C8|   CDbgSignalDelayMuxSel   |  — |
|0x32D0|    CDbgClaTimestampsync   |  — |
|0x32D8| CDbgClaXtriggerTimestretch|  — |
|0x33F0|        CrScratchpad       |  — |
|0x33F8|          Scratch          |  — |
|0x4000|      Trfunnelcontrol      |  — |
|0x4004|        Trfunnelimpl       |  — |
|0x4008|      Trfunneldisinput     |  — |
|0x5000|        Trramcontrol       |  — |
|0x5004|         Trramimpl         |  — |
|0x5010|       Trramstartlow       |  — |
|0x5014|       Trramstarthigh      |  — |
|0x5018|       Trramlimitlow       |  — |
|0x501C|       Trramlimithigh      |  — |
|0x5020|         Trramwplow        |  — |
|0x5024|        Trramwphigh        |  — |
|0x5028|         Trramrplow        |  — |
|0x502C|        Trramrphigh        |  — |
|0x5040|         Trramdata         |  — |
|0x5E00|  Trcustomramsmemlimitlow  |  — |
|0x6000|      Trdstramcontrol      |  — |
|0x6004|        Trdstramimpl       |  — |
|0x6010|      Trdstramstartlow     |  — |
|0x6014|     Trdstramstarthigh     |  — |
|0x6018|      Trdstramlimitlow     |  — |
|0x601C|     Trdstramlimithigh     |  — |
|0x6020|       Trdstramwplow       |  — |
|0x6024|       Trdstramwphigh      |  — |
|0x6028|       Trdstramrplow       |  — |
|0x602C|       Trdstramrphigh      |  — |
|0x6040|        Trdstramdata       |  — |
|0x7FF8|    TrClusterFuseCfgLow    |  — |
|0x7FFC|     TrClusterFuseCfgHi    |  — |
|0x8FE8|        TrScratchLo        |  — |
|0x8FEC|        TrScratchHi        |  — |
|0x8FF0|       TrScratchpadLo      |  — |
|0x8FF4|       TrScratchpadHi      |  — |

### CDbgMuxSel register

- Absolute Address: 0x198
- Base Offset: 0x198
- Size: 0x8



| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 1:0 |  Dbmmode |  rw  | 0x0 |  — |
| 7:2 |   Dbmid  |  rw  | 0x0 |  — |
| 15:8|  Rsvd158 |  rw  | 0x0 |  — |
|21:16|Muxselseg0|  rw  | 0x0 |  — |
|27:22|Muxselseg1|  rw  | 0x0 |  — |
|33:28|Muxselseg2|  rw  | 0x0 |  — |
|39:34|Muxselseg3|  rw  | 0x0 |  — |
|45:40|Muxselseg4|  rw  | 0x0 |  — |
|51:46|Muxselseg5|  rw  | 0x0 |  — |
|57:52|Muxselseg6|  rw  | 0x0 |  — |
|63:58|Muxselseg7|  rw  | 0x0 |  — |

#### Dbmmode field

<p>Mode selection, 0: DBM off, 1: Normal debug mode, 2: DBM ID output mode, 3: Toggle Mode</p>

#### Dbmid field

<p>Unique DBM ID of the DBM instance</p>

#### Muxselseg0 field

<p>Mux Select Bits for Lane 0. Split debug bus into 16 bit segments. Seg0 = debug bus [15:0], Seg1 = debug bus[31:16],.... If all bits are 0, Lane0 = Seg0, if bit[0] = 1, Lane0 = Seg4, if bit[1] =1, Lane0 = Seg5,...</p>

#### Muxselseg1 field

<p>Mux Select Bits for Lane 1. Split debug bus into 16 bit segments. Seg0 = debug bus [15:0], Seg1 = debug bus[31:16],.... If all bits are 0, Lane1= Seg1, if bit[0] = 1, Lane1 = Seg4, if bit[1] =1, Lane1 = Seg5,...</p>

#### Muxselseg2 field

<p>Mux Select Bits for Lane 2. Split debug bus into 16 bit segments. Seg0 = debug bus [15:0], Seg1 = debug bus[31:16],.... If all bits are 0, Lane2= Seg2, if bit[0] = 1, Lane2 = Seg4, if bit[1] =1, Lane2 = Seg5,...</p>

#### Muxselseg3 field

<p>Mux Select Bits for Lane 3. Split debug bus into 16 bit segments. Seg0 = debug bus [15:0], Seg1 = debug bus[31:16],.... If all bits are 0, Lane3= Seg3, if bit[0] = 1, Lane3 = Seg4, if bit[1] =1, Lane3 = Seg5,...</p>

### CDfdCsr register

- Absolute Address: 0x1A0
- Base Offset: 0x1A0
- Size: 0x8



|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |DfdMmrLock|  rw  | 0x1 |  — |
|62:1|  Rsvd621 |   r  | 0x0 |  — |
| 63 |   DfdEn  |  rw  | 0x0 |  — |

### Timestamp register

- Absolute Address: 0x200
- Base Offset: 0x200
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| Timestamp|  rw  | 0x0 |  — |

#### Timestamp field

<p>Timestamp value</p>

### TimestampSync register

- Absolute Address: 0x208
- Base Offset: 0x208
- Size: 0x8

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|63:0|TimestampSync|  rw  | 0x0 |  — |

#### TimestampSync field

<p>TimestampSync value</p>

### TimeStampConfig register

- Absolute Address: 0x210
- Base Offset: 0x210
- Size: 0x4

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |   TsSync  |  rw  | 0x0 |  — |
| 8:1|DebugMarker|  rw  | 0x0 |  — |
|31:9|    Rsvd   |  rw  | 0x0 |  — |

#### TsSync field

<p>TS Sync</p>

#### DebugMarker field

<p>Debug Marker</p>

#### Rsvd field

<p>Rsvd</p>

### Trdstcontrol register

- Absolute Address: 0x1000
- Base Offset: 0x1000
- Size: 0x4



| Bits|       Identifier       |Access|Reset|Name|
|-----|------------------------|------|-----|----|
|  0  |       Trdstactive      |  rw  | 0x0 |  — |
|  1  |       Trdstenable      |  rw  | 0x0 |  — |
|  2  |    Trdstinsttracing    |  rw  | 0x0 |  — |
|  3  |       Trdstempty       |   r  | 0x1 |  — |
| 6:4 |      Trdstinstmode     |   r  | 0x6 |  — |
|  9  |      Trdstcontext      |   r  | 0x0 |  — |
|  11 | Trdstinsttriggerenable |  rw  | 0x0 |  — |
|  12 |Trdstinststalloroverflow|   r  | 0x0 |  — |
|  13 |    Trdstinststallena   |   r  | 0x0 |  — |
|  15 |     Trdstinhibitsrc    |   r  | 0x0 |  — |
|17:16|      Trdstsyncmode     |  rw  | 0x0 |  — |
|23:20|      Trdstsyncmax      |  rw  | 0x0 |  — |
|26:24|       Trdstformat      |  rw  | 0x3 |  — |

#### Trdstsyncmode field

<p>When the field is set tp 2'b10, sent timestamp. All other vlaues not NA.</p>

#### Trdstsyncmax field

<p>When trDstSyncMode is set to 2'b10, timestamp will be sent for every 2^(trDstSyncMax + 4) Cluster clocks.</p>

#### Trdstformat field

<p>bit[0]: XOR Enable, bit[1]: VLT Enable. Supported values : 2'b3 (XOR+VLT Compression), 2'b1 (XOR Compresion), 2'b0 (No Compression)</p>

### Trdstimpl register

- Absolute Address: 0x1004
- Base Offset: 0x1004
- Size: 0x4



| Bits|       Identifier      |Access|Reset|Name|
|-----|-----------------------|------|-----|----|
| 3:0 |     Trdstvermajor     |   r  | 0x1 |  — |
| 7:4 |     Trdstverminor     |   r  | 0x0 |  — |
| 11:8|     Trdstcomptype     |   r  | 0x1 |  — |
|19:16|   Trdstprotocolmajor  |   r  | 0x1 |  — |
|23:20|   Trdstprotocolminor  |   r  | 0x0 |  — |
|27:24| Trdstvendorframelength|  rw  | 0x1 |  — |
|30:28|Trdstvendorstreamlength|  rw  | 0x4 |  — |

#### Trdstvendorframelength field

<p>Specify frame length. Frame Length = trDstVendorFrameLength* 64 ; Frame Length should be a multiple of Bank Data Width.</p>

#### Trdstvendorstreamlength field

<p>Specify Stream length. A stream starts with "no compressed packet". Stream length specifies number of frames before a non-compressed packet is sent.Stream Length = 32* 2^(trDstVendorStreamLength + 1)</p>

### Trdstinstfeatures register

- Absolute Address: 0x1008
- Base Offset: 0x1008
- Size: 0x4



| Bits|        Identifier        |Access|Reset|Name|
|-----|--------------------------|------|-----|----|
|  0  |    Trdstinstnoaddrdiff   |   r  | 0x0 |  — |
|  1  |    Trdstinstnotrapaddr   |   r  | 0x0 |  — |
|  8  |Trdstinstenrepeatedhistory|   r  | 0x0 |  — |
|27:16|        Trdstsrcid        |  rw  | 0x0 |  — |
|31:28|       Trdstsrcbits       |  rw  | 0x4 |  — |

### CDbgDebugTraceCfg register

- Absolute Address: 0x11A0
- Base Offset: 0x11A0
- Size: 0x4



| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
| 3:0 |   TraceSourceId  |  rw  | 0x0 |  — |
| 11:4|TraceFrameFillByte|  rw  | 0x81|  — |
|15:12|FrameLenghtInBytes|  rw  | 0x2 |  — |
|  20 |  FrameModeEnable |  rw  | 0x1 |  — |
|  21 | FrameClosureMode |  rw  | 0x1 |  — |

#### TraceSourceId field

<p>Trace Source ID (FIXME: Base Address, Tool Issue)</p>

#### TraceFrameFillByte field

<p>Use "Filler Packet" to align a stream of trace packets within a frame boundary.</p>

#### FrameLenghtInBytes field

<p>Use trDstImpl[trDstVendorFrameLength] for Frame Length programming. Register field ZBB-ed.</p>

#### FrameModeEnable field

<p>Enable Frame Mode (Frame Mode: Always pack "frame length" number of bytes for trace transmission). If flush to memory is stalled (due to silicon bug), we can have incomplete packets in memory. Frame Mode will help SW decoder to avoid reading incomplete trasnmitted packets. In Frame Mode, SW will get a memory pointer that is aligned to Frame Length. HW will ensure  there are no incomplete packets incluced in the region pointed by memory pointer.</p>

#### FrameClosureMode field

<p>Closure Mode: 1: Close frame with a packet no larger than max packet size  before any overflow (due to packets crossing frame boundary). 0: Close frame when packets cross boundary. Push back packet crossing frame boundary to packet generator.</p>

### CDbgClaCounter0Cfg register

- Absolute Address: 0x3100
- Base Offset: 0x3100
- Size: 0x8

<p>Configure CLA counter0. One of the 4 counters used for counting cycles after a event match, and trigger a action on match.</p>

| Bits|  Identifier |Access|Reset|Name|
|-----|-------------|------|-----|----|
| 15:0|   Counter   |  rw  | 0x0 |  — |
|31:16|    Target   |  rw  | 0x0 |  — |
|  32 |ResetOnTarget|  rw  | 0x0 |  — |
|47:33| UpperCounter|  rw  | 0x0 |  — |
|62:48| UpperTarget |  rw  | 0x0 |  — |
|  63 |     Rsvd    |   r  | 0x0 |  — |

#### ResetOnTarget field

<p>When Counter = {upper_target,target} reset to 0.  With this bit set, counter will provide a periodic tick w/ frequency of (target +1) if the action is set to Auto Incr. The periodic tick will continue till Stop Auto Incr or Clear Counter action.</p>

### CDbgClaCounter1Cfg register

- Absolute Address: 0x3108
- Base Offset: 0x3108
- Size: 0x8

<p>Configure CLA counter1. One of the 4 counters used for counting cycles after a event match, and trigger a action on match.</p>

| Bits|  Identifier |Access|Reset|Name|
|-----|-------------|------|-----|----|
| 15:0|   Counter   |  rw  | 0x0 |  — |
|31:16|    Target   |  rw  | 0x0 |  — |
|  32 |ResetOnTarget|  rw  | 0x0 |  — |
|47:33| UpperCounter|  rw  | 0x0 |  — |
|62:48| UpperTarget |  rw  | 0x0 |  — |
|  63 |     Rsvd    |   r  | 0x0 |  — |

#### ResetOnTarget field

<p>When Counter = {upper_targe,target}, reset to 0.  With this bit set, counter will provide a periodic tick w/ frequency of (target +1) if the action is set to Auto Incr. The periodic tick will continue till Stop Auto Incr or Clear Counter action.</p>

### CDbgClaCounter2Cfg register

- Absolute Address: 0x3110
- Base Offset: 0x3110
- Size: 0x8

<p>Configure CLA counter2. One of the 4 counters used for counting cycles after a event match, and trigger a action on match.</p>

| Bits|  Identifier |Access|Reset|Name|
|-----|-------------|------|-----|----|
| 15:0|   Counter   |  rw  | 0x0 |  — |
|31:16|    Target   |  rw  | 0x0 |  — |
|  32 |ResetOnTarget|  rw  | 0x0 |  — |
|47:33| UpperCounter|  rw  | 0x0 |  — |
|62:48| UpperTarget |  rw  | 0x0 |  — |
|  63 |     Rsvd    |   r  | 0x0 |  — |

#### ResetOnTarget field

<p>When Counter = {upper_target,target}, reset to 0.  With this bit set, counter will provide a periodic tick w/ frequency of (target +1) if the action is set to Auto Incr. The periodic tick will continue till Stop Auto Incr or Clear Counter action.</p>

### CDbgClaCounter3Cfg register

- Absolute Address: 0x3118
- Base Offset: 0x3118
- Size: 0x8

<p>Configure CLA counter3. One of the 4 counters used for counting cycles after a event match, and trigger a action on match.</p>

| Bits|  Identifier |Access|Reset|Name|
|-----|-------------|------|-----|----|
| 15:0|   Counter   |  rw  | 0x0 |  — |
|31:16|    Target   |  rw  | 0x0 |  — |
|  32 |ResetOnTarget|  rw  | 0x0 |  — |
|47:33| UpperCounter|  rw  | 0x0 |  — |
|62:48| UpperTarget |  rw  | 0x0 |  — |
|  63 |     Rsvd    |   r  | 0x0 |  — |

#### ResetOnTarget field

<p>When Counter = {upper_target,target}, reset to 0.  With this bit set, counter will provide a periodic tick w/ frequency of (target +1) if the action is set to Auto Incr. The periodic tick will continue till Stop Auto Incr or Clear Counter action.</p>

### CDbgNode0Eap0 register

- Absolute Address: 0x3120
- Base Offset: 0x3120
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode0Eap1 register

- Absolute Address: 0x3128
- Base Offset: 0x3128
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode1Eap0 register

- Absolute Address: 0x3130
- Base Offset: 0x3130
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode1Eap1 register

- Absolute Address: 0x3138
- Base Offset: 0x3138
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode2Eap0 register

- Absolute Address: 0x3140
- Base Offset: 0x3140
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode2Eap1 register

- Absolute Address: 0x3148
- Base Offset: 0x3148
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode3Eap0 register

- Absolute Address: 0x3150
- Base Offset: 0x3150
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgNode3Eap1 register

- Absolute Address: 0x3158
- Base Offset: 0x3158
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (Two EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|63:52|        Rsvd       |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

### CDbgSignalMask0 register

- Absolute Address: 0x3160
- Base Offset: 0x3160
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x2) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Mask to be applied to debug bus before match</p>

### CDbgSignalMatch0 register

- Absolute Address: 0x3168
- Base Offset: 0x3168
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x2) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value used for debug bus match.</p>

### CDbgSignalMask1 register

- Absolute Address: 0x3170
- Base Offset: 0x3170
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x4) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Mask to be applied to debug bus before match</p>

### CDbgSignalMatch1 register

- Absolute Address: 0x3178
- Base Offset: 0x3178
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x4) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value used for debug bus match.</p>

### CDbgSignalEdgeDetectCfg register

- Absolute Address: 0x3180
- Base Offset: 0x3180
- Size: 0x8

<p>Register to configure debug bus for edge triggers.</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
| 5:0| Signal0Select|  rw  | 0x0 |  — |
|  6 |PosEdgeSignal0|  rw  | 0x0 |  — |
|12:7| Signal1Select|  rw  | 0x0 |  — |
| 13 |PosEdgeSignal1|  rw  | 0x0 |  — |

#### Signal0Select field

<p>Define which signal to select for edge detection.</p>

#### PosEdgeSignal0 field

<p>Defines which edge to detect for singal from signal0_select. 1: Pos edge, 0: Neg Edge</p>

#### Signal1Select field

<p>Define which signal to select for edge detection.</p>

#### PosEdgeSignal1 field

<p>Defines which edge to detect for singal from signal1_select. 1: Pos edge, 0: Neg Edge</p>

### CDbgEapStatus register

- Absolute Address: 0x3188
- Base Offset: 0x3188
- Size: 0x8

<p>Register to indicate if EAP Pair was activated. Use the corresponding w2c register to reset the status. There are 2 bits for each EAP. The bit corresponds to action-0 and action-1 of the EAP. The register is used by SW to know if an action was taken (ex: NMI ISR needs to know which of the EAP triggered the NMI)</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|  0 |  Node0Eap0 |   r  | 0x0 |  — |
|  1 |  Node0Eap1 |   r  | 0x0 |  — |
|  2 |  Node1Eap0 |   r  | 0x0 |  — |
|  3 |  Node1Eap1 |   r  | 0x0 |  — |
|  4 |  Node2Eap0 |   r  | 0x0 |  — |
|  5 |  Node2Eap1 |   r  | 0x0 |  — |
|  6 |  Node3Eap0 |   r  | 0x0 |  — |
|  7 |  Node3Eap1 |   r  | 0x0 |  — |
|31:8|   Rsvd318  |   r  | 0x0 |  — |
| 32 |Node0Eap0W2C|  rw  | 0x0 |  — |
| 33 |Node0Eap1W2C|  rw  | 0x0 |  — |
| 34 |Node1Eap0W2C|  rw  | 0x0 |  — |
| 35 |Node1Eap1W2C|  rw  | 0x0 |  — |
| 36 |Node2Eap0W2C|  rw  | 0x0 |  — |
| 37 |Node2Eap1W2C|  rw  | 0x0 |  — |
| 38 |Node3Eap0W2C|  rw  | 0x0 |  — |
| 39 |Node3Eap1W2C|  rw  | 0x0 |  — |

### CDbgClaCtrlStatus register

- Absolute Address: 0x3190
- Base Offset: 0x3190
- Size: 0x8

<p>Ctrl/Status register to Enable EAP after EAP programming is complete, and read the current node.</p>

|Bits|      Identifier      |Access|Reset|Name|
|----|----------------------|------|-----|----|
| 1:0|      CurrentNode     |   r  | 0x0 |  — |
|  5 |       EnableEap      |  rw  | 0x0 |  — |
|  6 |       EnableCla      |  rw  | 0x0 |  — |
|13:7|   ClaChainLoopDelay  |  rw  | 0x36|  — |
| 14 |DisableGlobalClockHalt|  rw  | 0x0 |  — |
| 15 | DisableLocalClockHalt|  rw  | 0x0 |  — |

#### CurrentNode field

<p>Read the current node.</p>

#### EnableEap field

<p>Set Enable EAP to 1 after EAP programming is complete</p>

#### EnableCla field

<p>Set this bit to 1 to enable CLA. If this bit is set, CLA is clock gated (save pwr)</p>

#### ClaChainLoopDelay field

<p>Creates a window in which we don’t forward the incoming Xtrigger and Clock_Halt signal</p>

#### DisableGlobalClockHalt field

<p>If this bit is set, clock halt action is not applied to global clocks</p>

#### DisableLocalClockHalt field

<p>If this bit is set, clock halt action is not applied to local clocks</p>

### CDbgRsvd0 register

- Absolute Address: 0x3198
- Base Offset: 0x3198
- Size: 0x8

<p>Reserved Register that can be changed.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value of reserved register.</p>

### CDbgRsvd1 register

- Absolute Address: 0x31A0
- Base Offset: 0x31A0
- Size: 0x8

<p>Reserved Register that can be changed.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value of reserved register.</p>

### CDbgRsvd2 register

- Absolute Address: 0x31A8
- Base Offset: 0x31A8
- Size: 0x8

<p>Reserved Register that can be changed.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value of reserved register.</p>

### CDbgTransitionMask register

- Absolute Address: 0x31B0
- Base Offset: 0x31B0
- Size: 0x8

<p>3 registers to configure "transition event". This register is to select the signals of interest using a mask.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

### CDbgTransitionFromValue register

- Absolute Address: 0x31B8
- Base Offset: 0x31B8
- Size: 0x8

<p>3 registers to configure "transition event". The event is triggered on transition from Value A to Value B. This register specifies Value A.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

### CDbgTransitionToValue register

- Absolute Address: 0x31C0
- Base Offset: 0x31C0
- Size: 0x8

<p>3 registers to configure "transition event". The event is triggered on transition from Value A to Value B. This register specifies Value B.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

### CDbgOnesCountMask register

- Absolute Address: 0x31C8
- Base Offset: 0x31C8
- Size: 0x8

<p>2 registers to configure "ones count" event. This register is to select the signals of interest using a mask.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

### CDbgOnesCountValue register

- Absolute Address: 0x31D0
- Base Offset: 0x31D0
- Size: 0x8

<p>2 registers to configure "ones count" event. Event triggered when the sum of the signals match the value specified in this register.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

### CDbgAnyChange register

- Absolute Address: 0x31D8
- Base Offset: 0x31D8
- Size: 0x8

<p>Event triggered when a subset of debug signals change. The mask is used to select the subset of the debug signals.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Mask   |  rw  | 0x0 |  — |

### CDbgSignalSnapshotNode0Eap0 register

- Absolute Address: 0x31E0
- Base Offset: 0x31E0
- Size: 0x8

<p>debug Bus Value when Node0 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode0Eap1 register

- Absolute Address: 0x31E8
- Base Offset: 0x31E8
- Size: 0x8

<p>debug Bus Value when Node0 Eap1 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode1Eap0 register

- Absolute Address: 0x31F0
- Base Offset: 0x31F0
- Size: 0x8

<p>debug Bus Value when Node1 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode1Eap1 register

- Absolute Address: 0x31F8
- Base Offset: 0x31F8
- Size: 0x8

<p>debug Bus Value when Node1 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode2Eap0 register

- Absolute Address: 0x3200
- Base Offset: 0x3200
- Size: 0x8

<p>debug Bus Value when Node0 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode2Eap1 register

- Absolute Address: 0x3208
- Base Offset: 0x3208
- Size: 0x8

<p>debug Bus Value when Node0 Eap1 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode3Eap0 register

- Absolute Address: 0x3210
- Base Offset: 0x3210
- Size: 0x8

<p>debug Bus Value when Node1 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode3Eap1 register

- Absolute Address: 0x3218
- Base Offset: 0x3218
- Size: 0x8

<p>debug Bus Value when Node1 Eap0 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgClaTimeMatch register

- Absolute Address: 0x3220
- Base Offset: 0x3220
- Size: 0x8

<p>This value is compared (greater than or equal to the programmed value) against the internal time register value of the core, and is used to generate a time match event for CLA. Needs to be non zero for the time match event signal to trigger. The event will only trigger an action if the EAP programming is done. Requires writing 0 to this register to stop the match event.</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|63:0|TimeMatchVal|  rw  | 0x0 |  — |

### CDbgSignalMask2 register

- Absolute Address: 0x3228
- Base Offset: 0x3228
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x1C) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Mask to be applied to debug bus before match</p>

### CDbgSignalMatch2 register

- Absolute Address: 0x3230
- Base Offset: 0x3230
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x1C) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value used for debug bus match.</p>

### CDbgSignalMask3 register

- Absolute Address: 0x3238
- Base Offset: 0x3238
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x1D) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Mask to be applied to debug bus before match</p>

### CDbgSignalMatch3 register

- Absolute Address: 0x3240
- Base Offset: 0x3240
- Size: 0x8

<p>Used to define debug bus match event. Match event (0x1D) is triggered when debug_bus &amp; mask = match.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |  rw  | 0x0 |  — |

#### Value field

<p>Value used for debug bus match.</p>

### CDbgNode0Eap2 register

- Absolute Address: 0x3248
- Base Offset: 0x3248
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode0Eap3 register

- Absolute Address: 0x3250
- Base Offset: 0x3250
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode1Eap2 register

- Absolute Address: 0x3258
- Base Offset: 0x3258
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode1Eap3 register

- Absolute Address: 0x3260
- Base Offset: 0x3260
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode2Eap2 register

- Absolute Address: 0x3268
- Base Offset: 0x3268
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode2Eap3 register

- Absolute Address: 0x3270
- Base Offset: 0x3270
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode3Eap2 register

- Absolute Address: 0x3278
- Base Offset: 0x3278
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgNode3Eap3 register

- Absolute Address: 0x3280
- Base Offset: 0x3280
- Size: 0x8

<p>CLA Action(s) are tied to events(s) using "event-action pairing" registers. One of he 8 EAPs (4 EAPs per Node).</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
| 1:0 |      DestNode     |  rw  | 0x0 |  — |
| 7:2 |      Action0      |  rw  | 0x0 |  — |
| 13:8|      Action1      |  rw  | 0x0 |  — |
|15:14|     LogicalOp     |  rw  | 0x0 |  — |
|21:16|     EventType0    |  rw  | 0x0 |  — |
|27:22|     EventType1    |  rw  | 0x0 |  — |
|31:28|   CustomAction0   |  rw  | 0x0 |  — |
|35:32|   CustomAction1   |  rw  | 0x0 |  — |
|  36 |CustomAction0Enable|  rw  | 0x0 |  — |
|  37 |CustomAction1Enable|  rw  | 0x0 |  — |
|43:38|     EventType2    |  rw  | 0x0 |  — |
|51:44|        Udf        |  rw  | 0x0 |  — |
|57:52|      Action2      |  rw  | 0x0 |  — |
|63:58|      Action3      |  rw  | 0x0 |  — |

#### DestNode field

<p>Select Destination Node</p>

#### Action0 field

<p>Select an Action</p>

#### Action1 field

<p>Select an Action</p>

#### LogicalOp field

<p>Relation to be satisfied among events to activate the actions</p>

#### EventType0 field

<p>Select a trigger event</p>

#### EventType1 field

<p>Select a trigger event</p>

#### CustomAction0 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction1 field

<p>Select the bit position of custom action bus to be set when EAP trigger is met. External blocks can define and implement the specifc action for a given bit.</p>

#### CustomAction0Enable field

<p>custom_action0 is valid only if custom_action0_enable is set</p>

#### CustomAction1Enable field

<p>custom_action1 is valid only if custom_action1_enable is set</p>

#### EventType2 field

<p>Select a trigger event</p>

#### Udf field

<p>User Defined Function with event type 0, 1, and 2 as arguments</p>

#### Action2 field

<p>Select an Action</p>

#### Action3 field

<p>Select an Action</p>

### CDbgSignalSnapshotNode0Eap2 register

- Absolute Address: 0x3288
- Base Offset: 0x3288
- Size: 0x8

<p>debug Bus Value when Node0 Eap2 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode0Eap3 register

- Absolute Address: 0x3290
- Base Offset: 0x3290
- Size: 0x8

<p>debug Bus Value when Node0 Eap3 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode1Eap2 register

- Absolute Address: 0x3298
- Base Offset: 0x3298
- Size: 0x8

<p>debug Bus Value when Node1 Eap2 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode1Eap3 register

- Absolute Address: 0x32A0
- Base Offset: 0x32A0
- Size: 0x8

<p>debug Bus Value when Node1 Eap3 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode2Eap2 register

- Absolute Address: 0x32A8
- Base Offset: 0x32A8
- Size: 0x8

<p>debug Bus Value when Node2 Eap2 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode2Eap3 register

- Absolute Address: 0x32B0
- Base Offset: 0x32B0
- Size: 0x8

<p>debug Bus Value when Node2 Eap3 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode3Eap2 register

- Absolute Address: 0x32B8
- Base Offset: 0x32B8
- Size: 0x8

<p>debug Bus Value when Node3 Eap2 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalSnapshotNode3Eap3 register

- Absolute Address: 0x32C0
- Base Offset: 0x32C0
- Size: 0x8

<p>debug Bus Value when Node3 Eap3 Trigger is met.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Value  |   r  | 0x0 |  — |

### CDbgSignalDelayMuxSel register

- Absolute Address: 0x32C8
- Base Offset: 0x32C8
- Size: 0x8



| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 1:0 |Muxselseg0|  rw  | 0x0 |  — |
| 3:2 |Muxselseg1|  rw  | 0x0 |  — |
| 5:4 |Muxselseg2|  rw  | 0x0 |  — |
| 7:6 |Muxselseg3|  rw  | 0x0 |  — |
| 9:8 |Muxselseg4|  rw  | 0x0 |  — |
|11:10|Muxselseg5|  rw  | 0x0 |  — |
|13:12|Muxselseg6|  rw  | 0x0 |  — |
|15:14|Muxselseg7|  rw  | 0x0 |  — |
|63:16|   Rsvd   |  rw  | 0x0 |  — |

#### Muxselseg0 field

<p>Dbg Mux Shifted signals Select Bits for Lane 0</p>

#### Muxselseg1 field

<p>Dbg Mux Shifted signals Select Bits for Lane 1</p>

#### Muxselseg2 field

<p>Dbg Mux Shifted signals Select Bits for Lane 2</p>

#### Muxselseg3 field

<p>Dbg Mux Shifted signals Select Bits for Lane 3</p>

#### Muxselseg4 field

<p>Dbg Mux Shifted signals Select Bits for Lane 4</p>

#### Muxselseg5 field

<p>Dbg Mux Shifted signals Select Bits for Lane 5</p>

#### Muxselseg6 field

<p>Dbg Mux Shifted signals Select Bits for Lane 6</p>

#### Muxselseg7 field

<p>Dbg Mux Shifted signals Select Bits for Lane 7</p>

### CDbgClaTimestampsync register

- Absolute Address: 0x32D0
- Base Offset: 0x32D0
- Size: 0x8

<p>This value is loaded to the finegrain timestamp counter based on a cross trigger to sync the time value across the multiple cluster's CLA blocks</p>

|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
|62:0|     Timestamp    |  rw  | 0x0 |  — |
| 63 |Timesyncmodeenable|  rw  | 0x0 |  — |

### CDbgClaXtriggerTimestretch register

- Absolute Address: 0x32D8
- Base Offset: 0x32D8
- Size: 0x8

<p>This value determines the time stretched pulse duration for the cross trigger. 8 bits for each of the two triggers.</p>

| Bits|   Identifier   |Access|Reset|Name|
|-----|----------------|------|-----|----|
| 7:0 |Xtrigger0Stretch|  rw  | 0x0 |  — |
| 15:8|Xtrigger1Stretch|  rw  | 0x0 |  — |
|63:16|      Rsvd      |  rw  | 0x0 |  — |

### CrScratchpad register

- Absolute Address: 0x33F0
- Base Offset: 0x33F0
- Size: 0x8

<p>Scratchpad register for DV</p>

|Bits|Identifier|Access|       Reset      |Name|
|----|----------|------|------------------|----|
|63:0|   Data   |  rw  |0xBFBFBFBFBFBFBFBF|  — |

### Scratch register

- Absolute Address: 0x33F8
- Base Offset: 0x33F8
- Size: 0x8

<p>Additional scratch register for DV and potential ECO usage</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   Data   |  rw  | 0x0 |  — |

### Trfunnelcontrol register

- Absolute Address: 0x4000
- Base Offset: 0x4000
- Size: 0x4



|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|  0 |Trfunnelactive|  rw  | 0x0 |  — |
|  1 |Trfunnelenable|  rw  | 0x0 |  — |
|  3 | Trfunnelempty|   r  | 0x1 |  — |

### Trfunnelimpl register

- Absolute Address: 0x4004
- Base Offset: 0x4004
- Size: 0x4



|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
| 3:0|Trfunnelvermajor|   r  | 0x1 |  — |
| 7:4|Trfunnelverminor|   r  | 0x0 |  — |
|11:8|Trfunnelcomptype|   r  | 0x8 |  — |

#### Trfunnelverminor field

<p>e</p>

### Trfunneldisinput register

- Absolute Address: 0x4008
- Base Offset: 0x4008
- Size: 0x4



|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|15:0|Trfunneldisinput|  rw  | 0x0 |  — |

#### Trfunneldisinput field

<p>Bits 7:0 are reserved for N-trace srcs and 15:8 for Dst sources</p>

### Trramcontrol register

- Absolute Address: 0x5000
- Base Offset: 0x5000
- Size: 0x4



|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|  0 |  Trramactive  |  rw  | 0x0 |  — |
|  1 |  Trramenable  |  rw  | 0x0 |  — |
|  3 |   Trramempty  |   r  | 0x1 |  — |
|  4 |   Trrammode   |  rw  | 0x0 |  — |
|  8 |Trramstoponwrap|  rw  | 0x0 |  — |

### Trramimpl register

- Absolute Address: 0x5004
- Base Offset: 0x5004
- Size: 0x4



| Bits|      Identifier      |Access|Reset|Name|
|-----|----------------------|------|-----|----|
| 3:0 |     Trramvermajor    |   r  | 0x1 |  — |
| 7:4 |     Trramverminor    |   r  | 0x0 |  — |
| 11:8|     Trramcomptype    |   r  | 0x9 |  — |
|  12 |     Trramhassram     |   r  | 0x1 |  — |
|  13 |     Trramhassmem     |   r  | 0x1 |  — |
|27:24|Trramvendorframelength|  rw  | 0x1 |  — |

### Trramstartlow register

- Absolute Address: 0x5010
- Base Offset: 0x5010
- Size: 0x4



|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 1:0|    Rsvd10   |   r  | 0x0 |  — |
|31:2|Trramstartlow|  rw  | 0x0 |  — |

### Trramstarthigh register

- Absolute Address: 0x5014
- Base Offset: 0x5014
- Size: 0x4



|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|Trramstarthigh|  rw  | 0x0 |  — |

### Trramlimitlow register

- Absolute Address: 0x5018
- Base Offset: 0x5018
- Size: 0x4



|Bits|  Identifier |Access| Reset|Name|
|----|-------------|------|------|----|
| 1:0|    Rsvd10   |   r  |  0x0 |  — |
|31:2|Trramlimitlow|  rw  |0x2000|  — |

### Trramlimithigh register

- Absolute Address: 0x501C
- Base Offset: 0x501C
- Size: 0x4



|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|Trramlimithigh|  rw  | 0x0 |  — |

### Trramwplow register

- Absolute Address: 0x5020
- Base Offset: 0x5020
- Size: 0x4



|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | Trramwrap|   r  | 0x0 |  — |
|31:2|Trramwplow|  rw  | 0x0 |  — |

### Trramwphigh register

- Absolute Address: 0x5024
- Base Offset: 0x5024
- Size: 0x4



|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|31:0|Trramwphigh|  rw  | 0x0 |  — |

### Trramrplow register

- Absolute Address: 0x5028
- Base Offset: 0x5028
- Size: 0x4



|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 1:0|  Rsvd10  |   r  | 0x0 |  — |
|31:2|Trramrplow|  rw  | 0x0 |  — |

### Trramrphigh register

- Absolute Address: 0x502C
- Base Offset: 0x502C
- Size: 0x4



|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|31:0|Trramrphigh|  rw  | 0x0 |  — |

### Trramdata register

- Absolute Address: 0x5040
- Base Offset: 0x5040
- Size: 0x4



|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| Trramdata|   r  | 0x0 |  — |

### Trcustomramsmemlimitlow register

- Absolute Address: 0x5E00
- Base Offset: 0x5E00
- Size: 0x4



|Bits|       Identifier      |Access| Reset|Name|
|----|-----------------------|------|------|----|
| 1:0|         Rsvd10        |   r  |  0x0 |  — |
|31:2|Trcustomramsmemlimitlow|  rw  |0x1000|  — |

### Trdstramcontrol register

- Absolute Address: 0x6000
- Base Offset: 0x6000
- Size: 0x4



|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
|  0 |  Trdstramactive  |  rw  | 0x0 |  — |
|  1 |  Trdstramenable  |  rw  | 0x0 |  — |
|  3 |   Trdstramempty  |   r  | 0x1 |  — |
|  4 |   Trdstrammode   |  rw  | 0x0 |  — |
|  8 |Trdstramstoponwrap|  rw  | 0x0 |  — |

### Trdstramimpl register

- Absolute Address: 0x6004
- Base Offset: 0x6004
- Size: 0x4



| Bits|        Identifier       |Access|Reset|Name|
|-----|-------------------------|------|-----|----|
| 3:0 |     Trdstramvermajor    |   r  | 0x1 |  — |
| 7:4 |     Trdstramverminor    |   r  | 0x0 |  — |
| 11:8|     Trdstramcomptype    |   r  | 0x9 |  — |
|  12 |     Trdstramhassram     |   r  | 0x1 |  — |
|  13 |     Trdstramhassmem     |   r  | 0x1 |  — |
|27:24|Trdstramvendorframelength|  rw  | 0x1 |  — |

### Trdstramstartlow register

- Absolute Address: 0x6010
- Base Offset: 0x6010
- Size: 0x4



|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
| 1:0|     Rsvd10     |   r  | 0x0 |  — |
|31:2|Trdstramstartlow|  rw  | 0x0 |  — |

### Trdstramstarthigh register

- Absolute Address: 0x6014
- Base Offset: 0x6014
- Size: 0x4



|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|31:0|Trdstramstarthigh|  rw  | 0x0 |  — |

### Trdstramlimitlow register

- Absolute Address: 0x6018
- Base Offset: 0x6018
- Size: 0x4



|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
| 1:0|     Rsvd10     |   r  | 0x0 |  — |
|31:2|Trdstramlimitlow|  rw  | 0x0 |  — |

### Trdstramlimithigh register

- Absolute Address: 0x601C
- Base Offset: 0x601C
- Size: 0x4



|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|31:0|Trdstramlimithigh|  rw  | 0x0 |  — |

### Trdstramwplow register

- Absolute Address: 0x6020
- Base Offset: 0x6020
- Size: 0x4



|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 | Trdstramwrap|   r  | 0x0 |  — |
|31:2|Trdstramwplow|  rw  | 0x0 |  — |

### Trdstramwphigh register

- Absolute Address: 0x6024
- Base Offset: 0x6024
- Size: 0x4



|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|Trdstramwphigh|  rw  | 0x0 |  — |

### Trdstramrplow register

- Absolute Address: 0x6028
- Base Offset: 0x6028
- Size: 0x4



|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 1:0|    Rsvd10   |   r  | 0x0 |  — |
|31:2|Trdstramrplow|  rw  | 0x0 |  — |

### Trdstramrphigh register

- Absolute Address: 0x602C
- Base Offset: 0x602C
- Size: 0x4



|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|Trdstramrphigh|  rw  | 0x0 |  — |

### Trdstramdata register

- Absolute Address: 0x6040
- Base Offset: 0x6040
- Size: 0x4



|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|31:0|Trdstramdata|   r  | 0x0 |  — |

### TrClusterFuseCfgLow register

- Absolute Address: 0x7FF8
- Base Offset: 0x7FF8
- Size: 0x4



| Bits|  Identifier  |Access|Reset|Name|
|-----|--------------|------|-----|----|
| 7:0 |ScHarvestStrap|  rw  | 0x0 |  — |
|  8  |  TraceEnable |  rw  | 0x0 |  — |
| 10:9|  DebugEnable |  rw  | 0x0 |  — |
|14:11|   Rsvd1411   |  rw  | 0x0 |  — |
|  15 |     Lock     |  rw  | 0x0 |  — |
|  16 |  Core0Enable |  rw  | 0x0 |  — |
|19:17|   Core0Vid   |  rw  | 0x0 |  — |
|  20 |  Core1Enable |  rw  | 0x0 |  — |
|23:21|   Core1Vid   |  rw  | 0x0 |  — |
|  24 |  Core2Enable |  rw  | 0x0 |  — |
|27:25|   Core2Vid   |  rw  | 0x0 |  — |
|  28 |  Core3Enable |  rw  | 0x0 |  — |
|31:29|   Core3Vid   |  rw  | 0x0 |  — |

#### ScHarvestStrap field

<p>1 bit / 4 ways (total 8 bit /32 ways possible) 1: enable 0: disabled</p>

#### TraceEnable field

<p>CLA and Trace enable</p>

#### DebugEnable field

<p>Debug enable. 00 - No Debug  01 - Default (JTAG based debug)  10 - AXI based debug  11 - Support both enabled at same time. Same cycle collision causes error packet</p>

#### Rsvd1411 field

<p>Reserved for future use</p>

#### Lock field

<p>Lock bit</p>

#### Core0Enable field

<p>Physical Core0 availability</p>

#### Core0Vid field

<p>Physical Core0 vid</p>

#### Core1Enable field

<p>Physical Core1 availability</p>

#### Core1Vid field

<p>Physical Core1 vid</p>

#### Core2Enable field

<p>Physical Core2 availability</p>

#### Core2Vid field

<p>Physical Core2 vid</p>

#### Core3Enable field

<p>Physical Core3 availability</p>

#### Core3Vid field

<p>Physical Core3 vid</p>

### TrClusterFuseCfgHi register

- Absolute Address: 0x7FFC
- Base Offset: 0x7FFC
- Size: 0x4



| Bits| Identifier|Access|Reset|Name|
|-----|-----------|------|-----|----|
|  0  |Core4Enable|  rw  | 0x0 |  — |
| 3:1 |  Core4Vid |  rw  | 0x0 |  — |
|  4  |Core5Enable|  rw  | 0x0 |  — |
| 7:5 |  Core5Vid |  rw  | 0x0 |  — |
|  8  |Core6Enable|  rw  | 0x0 |  — |
| 11:9|  Core6Vid |  rw  | 0x0 |  — |
|  12 |Core7Enable|  rw  | 0x0 |  — |
|15:13|  Core7Vid |  rw  | 0x0 |  — |
|31:16|  Rsvd3116 |  rw  | 0x0 |  — |

#### Core4Enable field

<p>Physical Core4 availability</p>

#### Core4Vid field

<p>Physical Core4 vid</p>

#### Core5Enable field

<p>Physical Core5 availability</p>

#### Core5Vid field

<p>Physical Core5 vid</p>

#### Core6Enable field

<p>Physical Core6 availability</p>

#### Core6Vid field

<p>Physical Core6 vid</p>

#### Core7Enable field

<p>Physical core7 availability</p>

#### Core7Vid field

<p>Physical core7 vid</p>

#### Rsvd3116 field

<p>Reserved for future use</p>

### TrScratchLo register

- Absolute Address: 0x8FE8
- Base Offset: 0x8FE8
- Size: 0x4

<p>Additional scratch register for DV and potential ECO usage</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   Data   |  rw  | 0x0 |  — |

### TrScratchHi register

- Absolute Address: 0x8FEC
- Base Offset: 0x8FEC
- Size: 0x4

<p>Additional scratch register for DV and potential ECO usage</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   Data   |  rw  | 0x0 |  — |

### TrScratchpadLo register

- Absolute Address: 0x8FF0
- Base Offset: 0x8FF0
- Size: 0x4

<p>Scratchpad register for DV</p>

|Bits|Identifier|Access|   Reset  |Name|
|----|----------|------|----------|----|
|31:0|   Data   |  rw  |0xEFEFEFEF|  — |

### TrScratchpadHi register

- Absolute Address: 0x8FF4
- Base Offset: 0x8FF4
- Size: 0x4

<p>Scratchpad register for DV</p>

|Bits|Identifier|Access|   Reset  |Name|
|----|----------|------|----------|----|
|31:0|   Data   |  rw  |0xEFEFEFEF|  — |
