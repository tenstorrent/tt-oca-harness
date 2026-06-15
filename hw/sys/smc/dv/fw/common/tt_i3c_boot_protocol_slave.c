// // tt_i3c_boot_protocol_slave.c
// #include <cdn_errno.h>
// #include <cdn_stdtypes.h>
// #include "cpu.h"
// #include "i3c_obj_if.h"
// #include "tt_i3c_boot_protocol.h"
// #include "tt_i3c.h"
// #include "tt_smc_interrupts.h"
// #include "virt_console.h"

// // Dummy slave memory for read/write operations.
// #define SLAVE_MEM_SIZE 1024
// static uint8_t slave_memory[SLAVE_MEM_SIZE];

// static I3C_Error slave_write_memory(uint64_t address, const uint8_t* data, uint8_t size) {
//     if (address + size > SLAVE_MEM_SIZE) {
//         return I3C_ERR_ACCESS;
//     }
//     for (uint8_t i = 0; i < size; i++) {
//         slave_memory[address + i] = data[i];
//     }
//     return I3C_SUCCESS;
// }

// static I3C_Error slave_read_memory(uint64_t address, uint8_t* data, uint8_t size) {
//     if (address + size > SLAVE_MEM_SIZE) {
//         return I3C_ERR_ACCESS;
//     }
//     for (uint8_t i = 0; i < size; i++) {
//         data[i] = slave_memory[address + i];
//     }
//     return I3C_SUCCESS;
// }

// /**
//  * Handle a boot protocol command received from the master.
//  * The request payload is in pPayload->sdr_payload (with size payloadSize).
//  * The response will be built in pResponse->ddr_payload.
//  */
// I3C_Error i3c_boot_protocol_slave_handle_command(const I3C_PayloadData* pPayload,
//                                                  I3C_PayloadData* pResponse)
// {
//     if (!pPayload || !pResponse || !pPayload->sdr_payload) {
//         return I3C_ERR_ACCESS;
//     }
//     uint8_t command = pPayload->sdr_payload[0];
//     switch (command) {
//         case I3C_CMD_WRITE:
//         {
//             // Format:
//             // Byte 0: I3C_CMD_WRITE
//             // Bytes 1-8: 64-bit destination address (little-endian)
//             // Byte 9: write_size
//             // Bytes 10...: Data to write
//             uint64_t address = 0;
//             for (int i = 0; i < 8; i++) {
//                 address |= ((uint64_t)pPayload->sdr_payload[1 + i]) << (8 * i);
//             }
//             uint8_t write_size = pPayload->sdr_payload[9];
//             const uint8_t* data = &pPayload->sdr_payload[10];
//             I3C_Error err = slave_write_memory(address, data, write_size);
//             if (pResponse->ddr_payload) {
//                 pResponse->ddr_payload[0] = (err == I3C_SUCCESS) ? 0 : 1;
//             }
//             break;
//         }
//         case I3C_CMD_READ:
//         {
//             // Format:
//             // Byte 0: I3C_CMD_READ
//             // Bytes 1-8: 64-bit source address (little-endian)
//             // Byte 9: read_size
//             uint64_t address = 0;
//             for (int i = 0; i < 8; i++) {
//                 address |= ((uint64_t)pPayload->sdr_payload[1 + i]) << (8 * i);
//             }
//             uint8_t read_size = pPayload->sdr_payload[9];
//             uint8_t readData[read_size];
//             I3C_Error err = slave_read_memory(address, readData, read_size);
//             if (pResponse->ddr_payload) {
//                 for (uint8_t i = 0; i < read_size; i++) {
//                     pResponse->ddr_payload[i] = readData[i];
//                 }
//                 pResponse->ddr_payload[read_size] = (err == I3C_SUCCESS) ? 0 : 1;
//             }
//             break;
//         }
//         // Add additional command handling as needed...
//         default:
//             if (pResponse->ddr_payload) {
//                 pResponse->ddr_payload[0] = I3C_ERR_INVALID_CMD;
//             }
//             break;
//     }
//     return I3C_SUCCESS;
// }

// // --- Slave Driver and Callbacks ---

// I3C_ALIGNED_BUFFER(i3cSlaveMemory);
// static I3C_PrivData *slavePrivateData = (I3C_PrivData *)i3cSlaveMemory;
// static I3C_OBJ *i3cSlaveDriver = NULL;
// static I3C_EventState gSlaveEvents = {0};

// #define I3C_SLAVE_INTERRUPT_ID I3C_1_INTERRUPT_ID

// static I3C_Config slaveConfig = {
//     .regsBase = (MIPI_I3cRegs *)SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_1_CADENCE_I3C_REG_MAP_BASE_ADDR,
//     .sysClk = 100000000,
//     .sdrFreq = 12500000,
//     .i2cFreq = 400000,
//     .txFifoSize = 64,
//     .rxFifoSize = 64,
// };

// // The modified SDR Write Complete callback now handles boot protocol commands.
// void slv_sdr_write_comp_cb(I3C_PrivData *pd) {
//   simputs("slv_sdr_write cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_SDR_WRITE_COMPLETE;

//   // Determine how many bytes were received.
//   uint32_t rxCount = i3cSlaveDriver->slaveGetRxCount(slavePrivateData);
//   if (rxCount == 0 || rxCount > 64) {  // Limit size for safety.
//     simputs("Invalid RX count\n");
//     return;
//   }
//   uint8_t rxBuffer[64] = {0};
//   i3cSlaveDriver->slaveRead(slavePrivateData, rxBuffer, rxCount);

//   // Prepare request and response payload structures.
//   I3C_PayloadData requestPayload = {
//       .sdr_payload = rxBuffer,
//       .ddr_payload = NULL,
//       .payloadSize = rxCount
//   };

//   // Allocate a fixed–size response buffer (adjust size as needed).
//   uint8_t responseBuffer[64] = {0};
//   I3C_PayloadData responsePayload = {
//       .sdr_payload = NULL,
//       .ddr_payload = responseBuffer,
//       .payloadSize = sizeof(responseBuffer)
//   };

//   I3C_Error err = i3c_boot_protocol_slave_handle_command(&requestPayload, &responsePayload);
//   if (err != I3C_SUCCESS) {
//       simputs("Error handling boot protocol command\n");
//   }
//   // Write the response back over DDR. (This API call is assumed;
//   // adjust according to your actual slave driver’s interface.)
//   i3cSlaveDriver->slaveWrite(slavePrivateData, responsePayload.ddr_payload, responsePayload.payloadSize);

//   // Clear the event to be ready for the next command.
//   tt_i3c_clear_events(&gSlaveEvents, I3C_SLAVE_EVENT_SDR_WRITE_COMPLETE);
// }

// void slv_sdr_read_comp_cb(I3C_PrivData *pd) {
//   simputs("slv_sdr_read cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_SDR_READ_COMPLETE;
// }

// void slv_ddr_read_comp_cb(I3C_PrivData *pd) {
//   simputs("slv_ddr_read cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_DDR_READ_COMPLETE;
// }

// void slv_ddr_write_comp_cb(I3C_PrivData *pd) {
//   simputs("slv_ddr_write cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_DDR_WRITE_COMPLETE;
// }

// void slv_test_mode_cb(I3C_PrivData *pd) {
//   simputs("test_mode cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_TEST_MODE;
// }
// void slv_ibi_done_cb(I3C_PrivData *pd) {
//   simputs("slv_ibi_done cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_IBI_DONE;
// }

// void slv_sdrError_cb(I3C_PrivData *pd) {
//   simputs("slv_sdrError cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_SDR_ERROR;
// }

// void slv_mwlChange_cb(I3C_PrivData *pd) {
//   simputs("slv_mwlChange cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_MWL_CHANGE;
// }

// void slv_mrlChange_cb(I3C_PrivData *pd) {
//   simputs("slv_mrlChange cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_MRL_CHANGE;
// }

// void slv_busconUp_cb(I3C_PrivData *pd) {
//   simputs("slv_busconUp cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_BUSCON_UP;
// }

// void slv_flushDone_cb(I3C_PrivData *pd) {
//   simputs("slv_flushDone cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_FLUSH_DONE;
// }

// void slv_resetDaa_cb(I3C_PrivData *pd) {
//   simputs("slv_resetDaa cb\n");
//   (void)pd;
//   gSlaveEvents.events |= I3C_SLAVE_EVENT_RESET_DAA;
// }

// I3C_Callbacks slaveCallbacks = {
//   .slaveSdrRdComplete = slv_sdr_read_comp_cb,
//   .slaveSdrWrComplete = slv_sdr_write_comp_cb,
//   .slaveDdrRdComplete = slv_ddr_read_comp_cb,
//   .slaveDdrWrComplete = slv_ddr_write_comp_cb,
//   .slaveIBIDone = slv_ibi_done_cb,
//   .slaveSdrError = slv_sdrError_cb,
//   .testMode = slv_test_mode_cb,
//   .slaveMwlChange = slv_mwlChange_cb,
//   .slaveMrlChange = slv_mrlChange_cb,
//   .slaveBusconUp = slv_busconUp_cb,
//   .slaveFlushDone = slv_flushDone_cb,
//   .slaveResetDaa = slv_resetDaa_cb
// };

// static const I3C_SlaveInterruptConfig intCfg = {
//     .sdrWrComplete = true,
//     .sdrRdComplete = true,
//     .ddrWrComplete = true,
//     .ddrRdComplete = true,
//     .sdrTxDataFifoOverflow = true,
//     .sdrRxDataFifoUnderflow = true,
//     .ddrTxDataFifoOverflow = true,
//     .ddrRxDataFifoUnderflow = true,
//     .sdrTxFifoThreshold = true,
//     .sdrRxFifoThreshold = true,
//     .ddrTxFifoThreshold = true,
//     .ddrRxFifoThreshold = true,
//     .masterReadAbort = true,
//     .ddrFail = true,
//     .sdrFail = true,
//     .dynamicAddrUpdated = true,
//     .ibiDone = true,
//     .ibiNack = true,
//     .hotJoinDone = true,
//     .hotJoinNack = true,
//     .eventUpdate = true,
//     .protocolError = true,
//     .testMode = true
// };

// static void i3c_s_irq_handler(int id, void *priv) {
//   (void)priv;
//   (void)id;
//   simputs("Interrupt\n");
//   i3cSlaveDriver->isr(slavePrivateData);
// }

// static void slave_init(void) {
//   i3cSlaveDriver = I3C_GetInstance();
//   if (!i3cSlaveDriver) {
//     simputs("Error: I3C Slave driver instance not found\n");
//     test_fail(0);
//   }
//   uint32_t result = i3cSlaveDriver->init(slavePrivateData, &slaveConfig, &slaveCallbacks);
//   if (result != CDN_EOK) {
//     simputs("Error initializing I3C slave\n");
//     test_fail(0);
//   }
//   result = i3cSlaveDriver->start(slavePrivateData);
//   if (result != CDN_EOK) {
//     simputs("Error starting slave driver\n");
//     test_fail(0);
//   }
//   result = i3cSlaveDriver->slaveModeConfigure(slavePrivateData, &intCfg);
//   if (result != CDN_EOK) {
//     simputs("Error configuring slave mode\n");
//     test_fail(0);
//   }
// }

// int main(void) {
//   program_cgm0_functional();
//   SMC_WRAP_PLL_CNTL_AG_MUX_SELECT_reg_u ag_mux_sel;
//   ag_mux_sel.f.cgm_clkmux_sel = 1;
//   ag_mux_sel.f.cgm_ag_mux_sel = 1;
//   ag_mux_sel.f.awm_clkmux_sel = 0;
//   ag_mux_sel.f.awm_ag_mux_sel = 0;
//   write_reg(SMC_WRAP_PLL_CNTL_AG_MUX_SELECT_REG_ADDR, ag_mux_sel.val);
//   simputs("PLL Booted \n");

//   tt_i3c_init_controller(1, SUBORDINATE);
//   write_scratch(0, 1);

//   simputs("Entering PLIC init\n");
//   plic_init(0);
//   tt_i3c_register_irq(I3C_SLAVE_INTERRUPT_ID, i3c_s_irq_handler, slavePrivateData);
//   global_interrupt_enable();
//   simputs("PLIC init done\n");

// #ifdef DEBUG
//   DbgMsgSetLvl(DBG_HIVERB);
// #endif

//   slave_init();
//   simputs("Waiting for events...\n");
//   while (1) {
//     __asm__ volatile("wfi");
//   }
//   return 0;
// }

// int other_main(int hartid) {
//   (void)hartid;
//   while (true) {
//     __asm__("wfi");
//   }
// }

// int secondary_main(void) {
//   int hartid = metal_cpu_get_current_hartid();
//   if (hartid == 0) {
//     return main();
//   } else {
//     return other_main(hartid);
//   }
// }