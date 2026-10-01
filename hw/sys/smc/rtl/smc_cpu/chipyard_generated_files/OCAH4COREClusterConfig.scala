// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

class OCAH4CORECluster extends Config(

  // following must come after adding cores
  new freechips.rocketchip.subsystem.WithSeperateClockReset ++        // seperates tile clock and reset from the sbus interconnect

  new chipyard.config.WithL2TLBs(0) ++                                // remove TLBs
  new chipyard.config.WithNPerfCounters(4) ++                         // add 4 perf counters per core

  new freechips.rocketchip.subsystem.WithL1DCacheNMMIOs(24) ++ 
  new freechips.rocketchip.subsystem.WithCFlushEnabled ++

  new freechips.rocketchip.rocket.WithL1ICacheECC(dataECC="PARITY", tagECC="PARITY") ++  // add PARITY ECC to L1 instr cache
  new freechips.rocketchip.rocket.WithL1ICacheSets(sets = 32) ++   // 4KB ICache
  new freechips.rocketchip.rocket.WithL1ICacheWays(ways = 2) ++

  new freechips.rocketchip.rocket.WithL1DCacheECC(dataECC="SECDED", tagECC="SECDED") ++  // add SECDED ECC to L1 data cache
  new freechips.rocketchip.subsystem.WithL1DCacheDataECCBytes(bytes = 8) ++
  new freechips.rocketchip.rocket.WithL1DCacheSets(sets = 32) ++   // 4KB DCache
  new freechips.rocketchip.rocket.WithL1DCacheWays(ways = 2) ++

  new freechips.rocketchip.rocket.WithCustomFastMulDiv(mUnroll = 16, mEarlyOut = true, dUnroll = 1, dEarlyOut = true, dEarlyOutGranularity = 1) ++
  new freechips.rocketchip.rocket.WithCoreClockGatingEnabled() ++  // enable clock gating within the cores
  new freechips.rocketchip.subsystem.WithDCacheClockGatingEnabled() ++  // enable clock gating within the dcache

  new freechips.rocketchip.subsystem.WithDebugSBA ++                      // adds a bus master to the debug unit, allows access to systembus
  new freechips.rocketchip.subsystem.WithDebugImplicitEbreak ++           // enable implicit ebreak instruction at end of program buffer
  new freechips.rocketchip.subsystem.WithDebugHartResets ++               // enable HartResets in the debug module
  new freechips.rocketchip.subsystem.WithL1ICachePrefetch ++              // enable prefetching from the L1 ICache
  new freechips.rocketchip.subsystem.WithConditionalZeroInstrs ++         // enable hardware to handle for conditional zero instructions
  new freechips.rocketchip.subsystem.WithCustomMContextWidth(13) ++       // context width of 13 in machine mode
  new freechips.rocketchip.subsystem.WithBranchPredictionModeCSR ++       // add CSR bit config branch prediction
  new freechips.rocketchip.rocket.WithNBreakpoints(16) ++              // increase to 16 breakpoints
  new freechips.rocketchip.subsystem.WithBPWatchpointsEnabled(enable = true) ++

  new freechips.rocketchip.subsystem.WithCustomPgLevel(pgLevel = 5) ++
  new freechips.rocketchip.rocket.WithZba ++
  new freechips.rocketchip.rocket.WithZbb ++
  new freechips.rocketchip.rocket.WithZbs ++

  new freechips.rocketchip.subsystem.WithCustomFPU(sfmaLatency = 8,
                                                  dfmaLatency = 8,
                                                  fpmuLatency = 2,
                                                  ifpuLatency = 6
                                                  ) ++

  new freechips.rocketchip.subsystem.WithRocketTileCDC(crossingType = NoCrossing) ++   // core and uncore are same clock
  new freechips.rocketchip.subsystem.WithNBigCoresWithBEU(n=4, busErrorUnitAddr=0xC8010000L) ++  // 4 'big' Rocket cores

  new freechips.rocketchip.subsystem.WithNExtTopInterrupts(328) ++

  // add a ROM
  new testchipip.soc.WithTTROM(base = 0xC0040000L,
                               size = 0x00020000,
                               busWhere = MBUS,
                               contentFileName = "./generators/chipyard/src/main/resources/bootrom/bootrom.rv64.img") ++

  // partition splits it by total size    (i.e. partition=2 creates 2 memories, one from 0x0000_0000 to 0x0003_FFFF and one from 0x0004_0000 to 0x0007_FFFF)
  // banks splits up w/ finer granularity (i.e. 0x00-0x3F to bank0, 0x40-0x7F to bank1, etc.)
  // -> Don't split up, we do splitting up ourselves
  // --------------------------------------------------
  // create a 1MB scratchpad with SECDED
  new testchipip.soc.WithScratchpadWithECC(base = 0xC0060000L,
                                           size = 0x00100000L,
                                           banks = 4,
                                           partitions = 8,
                                           subPartitions = 1,
                                           ecc = ECCParams(
                                                   bytes = 8,
                                                   code = Code.fromString("SECDED"),
                                                   notifyErrors = false  // not needed, uncorrectable errors will already be sent back in d channel of TL
                                                 ),
                                           busWhere = MBUS,
                                           buffer = BufferParams.default,
                                           outerBuffer = BufferParams(16)
                                           ) ++

  new chipyard.config.WithCustomWDT(addr     = 0xC0000000L,
                                    size     = 0x400,
                                    offset   = 0x400,
                                    num_wdts = 4) ++

  // add error device to buses to prevent writes into undefined locations in the address map
  //  -> '++'' concatenates the address set sequences together
  new freechips.rocketchip.subsystem.WithCBusErrorDevices(addressSet = AddressSet.misaligned(base = 0xC8014000L, size = 0x1000L),
                                                          maxTransfer = 2048) ++

  //new freechips.rocketchip.subsystem.WithDebugAPB ++                 // set the debug module to expose an APB port
  new freechips.rocketchip.subsystem.WithJtagDTM ++

  new freechips.rocketchip.subsystem.WithoutTLMonitors ++

  // mmio axi
  new freechips.rocketchip.subsystem.WithCustomMMIOPort(base_addr    = 0x00000000L,  // max address of mmio port is 56 bits
                                                        base_size    = 0xC0000000L,  // max address of mmio port is 56 bits
                                                        data_width   = 64,
                                                        id_bits      = 3,
                                                        maxXferBytes = 2048) ++

  // front axi
  new freechips.rocketchip.subsystem.WithCustomSlaveAXI4Port(data_width = 64,
                                                             id_bits = 8) ++

  new freechips.rocketchip.subsystem.WithCoherentBusTopology ++

  new chipyard.TTSystemManagementAbstractConfig)
