#include "tt_i3c.h"

#define FIFO_WAIT_TIMEOUT 10000000

typedef union
{
  uint32_t word;
  uint8_t bytes[4];
} I3C_FIFO_Access;

// Forward declarations
static void configure_base_command(CDNSI3C_REG_CMD0_FIFO_reg_u *cmd0,
                                   uint8_t da, size_t length,
                                   I3C_TransmitMode mode, bool is_read);
static I3C_Status i3c_issue_write_cmd(I3C_Driver *drv, uint8_t da,
                                      size_t length);
static I3C_Status i3c_issue_read_cmd(I3C_Driver *drv, uint8_t da,
                                     size_t length);

static I3C_Status I3C_ReceivePayloadStream(I3C_Driver *drv, uint8_t *buffer,
                                           size_t buffer_length,
                                           size_t *bytes_received);

/*--------------------------------------------------------------
  Releases the I3C controller from reset.
---------------------------------------------------------------*/
void i3c_release_reset(uint8_t i3c_controller)
{
  I3C_CTRL_I3C_RESET_CTRL_STATUS_reg_u regval = {
      .val = I3C_CTRL_I3C_RESET_CTRL_STATUS_REG_DEFAULT};
  regval.f.i3c_reset_n_n0_scan = 1;
  regval.f.reg_reset_n_n0_scan = 1;
  regval.f.i3c_enable_n0_scan = 1;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_I3C_RESET_CTRL_STATUS_REG_OFFSET,
                     regval.val);
}

/*--------------------------------------------------------------
  Configures strap registers.
---------------------------------------------------------------*/
void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role)
{
  I3C_CTRL_PINSTRAPS_GROUP_1A_reg_u grp1a = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_1A_REG_DEFAULT};
  grp1a.f.device_role = (uint32_t)role;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_1A_REG_OFFSET,
                     grp1a.val);

  I3C_CTRL_PINSTRAPS_GROUP_1B_reg_u grp1b = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_1B_REG_DEFAULT};
  grp1b.f.mrl = 2080 << 8;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_1B_REG_OFFSET,
                     grp1b.val);

  I3C_CTRL_PINSTRAPS_GROUP_2A_reg_u grp2a = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_2A_REG_DEFAULT};
  grp2a.f.mwl = 2080;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_2A_REG_OFFSET,
                     grp2a.val);

  I3C_CTRL_PINSTRAPS_GROUP_3_reg_u grp3 = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_3_REG_DEFAULT};
  grp3.f.pid_instance_id = device_id;
  grp3.f.bus_avail_timer = 4;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_3_REG_OFFSET,
                     grp3.val);

  I3C_CTRL_PINSTRAPS_GROUP_4_reg_u grp4 = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_4_REG_DEFAULT};
  grp4.f.bus_idle_timer = 8;
  write_i3c_ctrl_reg(i3c_controller,
                     SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_4_REG_OFFSET,
                     grp4.val);

  I3C_CTRL_PINSTRAPS_GROUP_5_reg_u grp5 = {
      .val = I3C_CTRL_PINSTRAPS_GROUP_5_REG_DEFAULT};
  grp5.f.flow_ctrl_pr_dis = 0U;
  grp5.f.flow_ctrl_pw_dis = 1U;
  grp5.f.fpf_pw_sel = 0U;
  grp5.f.alt_mode_en = 1U;
  write_i3c_ctrl_reg(i3c_controller,
                      SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_PINSTRAPS_GROUP_5_REG_OFFSET,
                      grp5.val);
}

/*--------------------------------------------------------------
  Initializes the I3C controller by releasing reset and
  configuring the strap registers.
---------------------------------------------------------------*/
void init_i3c_ctrl(uint8_t controller_id, uint64_t device_id, I3C_Role role)
{
  // SMC_WRAP_RESET_UNIT_MASTER_PERIPHERAL_RESETS_reg_u peripheral_reset_ctrl = {
  //     .val = read_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR)};
  // peripheral_reset_ctrl.f.i3c_reset_n_n0_scan = 1;
  // write_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR, peripheral_reset_ctrl.val);

  cfg_ps(controller_id, (uint8_t)device_id, role);
  i3c_release_reset(controller_id);

  // After reset, the controller latches the straps to create its provisional ID. See section 3.18.7 of user guide.
  // We'll immediately set the PID based on the one provided by software before bus initialization can happen.
  CDNSI3C_REG_DEV_ID0_RR1_reg_u rr1 = {.val = (uint32_t)(device_id >> 16)};
  CDNSI3C_REG_DEV_ID0_RR2_reg_u rr2 = {.val = read_i3c(controller_id,
                                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR2_REG_OFFSET)};
  rr2.f.pid_lsb = (uint32_t)(device_id & 0xFFFF);

  write_i3c(controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR1_REG_OFFSET, rr1.val);
  write_i3c(controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR2_REG_OFFSET, rr2.val);
}

/*--------------------------------------------------------------
  Write data into the TX FIFO.
---------------------------------------------------------------*/
static I3C_Status fifo_write(I3C_Driver *drv, const uint8_t *data,
                             size_t length)
{
  if (drv == NULL || !drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }
  uint8_t controller_id = drv->ctx.controller_id;
  size_t bytes_written = 0;

  while (bytes_written < length)
  {
    uint32_t timeout = FIFO_WAIT_TIMEOUT;
    CDNSI3C_REG_MST_STATUS0_reg_u status;
    while (timeout > 0)
    {
      status.val =
          read_i3c(controller_id,
                   SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET);
      if (!status.f.tx_full)
        break;
      timeout--;
    }
    if (timeout == 0)
    {
      simputs("Timeout waiting for TX FIFO not full\n");
      return I3C_ERR_TIMEOUT;
    }

    size_t bytes_remaining = length - bytes_written;
    size_t bytes_to_copy = (bytes_remaining > 4) ? 4 : bytes_remaining;

    I3C_FIFO_Access converter;
    converter.word = 0;
    for (size_t i = 0; i < bytes_to_copy; ++i)
    {
      converter.bytes[i] = data[bytes_written + i];
    }
    write_i3c(controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_TX_FIFO_REG_OFFSET,
              converter.word);

    bytes_written += bytes_to_copy;
  }
  return I3C_OK;
}

/*--------------------------------------------------------------
  Read data from the RX FIFO, one byte at a time.
---------------------------------------------------------------*/
static I3C_Status fifo_read(I3C_Driver *drv, uint8_t *buffer, size_t length,
                            size_t *bytes_read)
{
  if (drv == NULL || !drv->ctx.initialized || buffer == NULL)
  {
    return I3C_ERR_HW;
  }
  uint8_t controller_id = drv->ctx.controller_id;
  size_t total_bytes_read = 0;

  for (size_t i = 0; i < length; ++i)
  {
    uint32_t timeout = FIFO_WAIT_TIMEOUT;
    CDNSI3C_REG_MST_STATUS0_reg_u status;

    // Wait for at least one byte to be available in the RX FIFO.
    while (timeout > 0)
    {
      status.val =
          read_i3c(controller_id,
                   SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET);
      if (!status.f.rx_emp)
      {
        break;
      }
      timeout--;
    }
    if (timeout == 0)
    {
      simputs("Timeout waiting for data in RX FIFO\n");
      return I3C_ERR_TIMEOUT;
    }

    // Read one byte from the FIFO. The lower 8 bits contain the valid data.
    uint32_t raw = read_i3c(
        controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_REG_OFFSET);
    buffer[i] = (uint8_t)(raw & 0xFF);
    total_bytes_read++;
  }

  if (bytes_read)
  {
    *bytes_read = total_bytes_read;
  }
  return I3C_OK;
}

/*--------------------------------------------------------------
  Wait until the current command completes or timeout.
---------------------------------------------------------------*/
static I3C_Status wait_command(I3C_Driver *drv, uint8_t command_id,
                               uint32_t timeout)
{
  bool enable_timeout = timeout > 0;
  uint32_t timer = false;
  CDNSI3C_REG_MST_STATUS0_reg_u mst_status0;
  CDNSI3C_REG_CMDR_reg_u cmdr;

  while (true)
  {
    mst_status0.val =
        read_i3c(drv->ctx.controller_id,
                 SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET);
    if (command_id == CMD_ID_READ && mst_status0.f.cmdr_emp && !mst_status0.f.rx_emp) {
      return I3C_OK;
    }
    if (mst_status0.f.idle)
    {
      cmdr.val = read_i3c(drv->ctx.controller_id,
                          SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMDR_REG_OFFSET);
      if (cmdr.f.error != 0)
      {
        // too much noise printing all these
        if (!(cmdr.f.cmd_id == CMD_ID_READ && cmdr.f.error == CMDR_ERROR_NACK_RESP))
          decode_cmdr_error(cmdr.f.error);
        return I3C_ERR_CMD_FAILED;
      }
      if (cmdr.f.cmd_id == command_id)
      {
        return I3C_OK;
      }
      else
      {
        simputs("Error: Unexpected command ID\n");
        simputshex32("Expected: ", command_id);
        simputshex32("Received: ", cmdr.f.cmd_id);
        return I3C_ERR_CMD_FAILED;
      }
    }
    if (enable_timeout && timer == 0)
    {
      return I3C_ERR_TIMEOUT;
    }
    if (enable_timeout)
    {
      timer--;
    }
  }
}

/*--------------------------------------------------------------
  Helper for issuing a single write command (CMD1 + CMD0),
  then waiting for completion.
---------------------------------------------------------------*/
static I3C_Status I3C_IssueSETGRPA(I3C_Driver *drv, uint8_t da, uint8_t group_addr)
{
  if (!drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }

  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_TX_FIFO_REG_OFFSET,
            group_addr << 1);

  // CMD1
  CDNSI3C_REG_CMD1_FIFO_reg_u cmd1 = {.val = 0};
  cmd1.f.cmd_id = CMD_ID_SETGRPA;
  cmd1.f.ccc_csraddr0 = CCC_SETGRPA;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD1_FIFO_REG_OFFSET,
            cmd1.val);

  // CMD0
  CDNSI3C_REG_CMD0_FIFO_reg_u cmd0 = {.val = 0};
  cmd0.f.is_ccc = 1;
  cmd0.f.dev_addr = da >> 1;
  cmd0.f.rnw = 0;
  cmd0.f.pl_len = 1;

  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD0_FIFO_REG_OFFSET,
            cmd0.val);

  return I3C_OK;
}

/*--------------------------------------------------------------
  Issue the ENTDAA command (writes the ENTDAA CCC).
---------------------------------------------------------------*/
static I3C_Status I3C_IssueENTDAA(I3C_Driver *drv)
{
  if (!drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }

  CDNSI3C_REG_CMD1_FIFO_reg_u cmd1 = {.val = 0x0};
  cmd1.f.cmd_id = CMD_ID_ENTDAA;
  cmd1.f.ccc_csraddr0 = CCC_ENTDAA;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD1_FIFO_REG_OFFSET,
            cmd1.val);

  CDNSI3C_REG_CMD0_FIFO_reg_u cmd0 = {.val = 0x0};
  cmd0.f.is_ccc = 0x1;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD0_FIFO_REG_OFFSET,
            cmd0.val);

  return I3C_OK;
}

/*--------------------------------------------------------------
  Read discovered device info from internal registers.
---------------------------------------------------------------*/
static I3C_Status I3C_ProcessDevices(I3C_Driver *drv, I3C_DeviceInfo *devices,
                                     size_t max_devices)
{
  if (!drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }

  CDNSI3C_REG_DEVS_CTRL_reg_u devs_ctrl = {
      .val =
          read_i3c(drv->ctx.controller_id,
                   SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEVS_CTRL_REG_OFFSET)};

  drv->ctx.num_devices = 0;
  for (uint8_t i = 0; i < I3C_MAX_DEVICES; i++)
  {
    if (!(devs_ctrl.val & (1 << i)))
    {
      continue;
    }
    I3C_DeviceInfo *info = &drv->ctx.discovered_devices[drv->ctx.num_devices];
    CDNSI3C_REG_DEV_ID0_RR0_reg_u rr0 = {
        .val = read_i3c(
            drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR0_REG_OFFSET +
                (i * 0x10))};
    CDNSI3C_REG_DEV_ID0_RR1_reg_u rr1 = {
        .val = read_i3c(
            drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR1_REG_OFFSET +
                (i * 0x10))};
    CDNSI3C_REG_DEV_ID0_RR2_reg_u rr2 = {
        .val = read_i3c(
            drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEV_ID0_RR2_REG_OFFSET +
                (i * 0x10))};

    info->dynamic_addr = calculate_dynamic_addr(rr0.f.dev_addr);
    info->pid = rr2.f.pid_lsb | ((uint64_t)rr1.f.pid_msb << 16);
    info->bcr = rr2.f.bcr;
    info->dcr = rr2.f.dcr_lvr;
    info->active = true;

    if (devices && drv->ctx.num_devices < max_devices)
    {
      devices[drv->ctx.num_devices] = *info;
    }
    drv->ctx.num_devices++;
  }
  if (drv->ctx.num_devices < 2)
  {
    simputs("No devices found\n");
    return I3C_ERR_NO_DEVICES;
  }
  return I3C_OK;
}

/*--------------------------------------------------------------
  Helper: configure CMD0 for read/write
---------------------------------------------------------------*/
static void configure_base_command(CDNSI3C_REG_CMD0_FIFO_reg_u *cmd0,
                                   uint8_t da, size_t length,
                                   I3C_TransmitMode mode, bool is_read)
{
  cmd0->f.is_ccc = 0;
  cmd0->f.xmit_mode = mode;
  cmd0->f.sbca = 0;
  cmd0->f.dev_addr_msb = 0;
  cmd0->f.dev_addr = da >> 1;
  cmd0->f.pl_len = length;
  cmd0->f.rnw = is_read;
}

/*--------------------------------------------------------------
  Helper for issuing a single write command (CMD1 + CMD0),
  then waiting for completion.
---------------------------------------------------------------*/
static I3C_Status i3c_issue_write_cmd(I3C_Driver *drv, uint8_t da,
                                      size_t length)
{
  // CMD1
  CDNSI3C_REG_CMD1_FIFO_reg_u cmd1 = {.val = 0};
  cmd1.f.cmd_id = CMD_ID_WRITE;
  cmd1.f.csraddr1 = 0;
  cmd1.f.ccc_csraddr0 = RX_FIFO;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD1_FIFO_REG_OFFSET,
            cmd1.val);

  // CMD0
  CDNSI3C_REG_CMD0_FIFO_reg_u cmd0 = {.val = 0};
  configure_base_command(&cmd0, da, length, I3C_CMD_XMIT_MODE_NCA,
                         false);
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD0_FIFO_REG_OFFSET,
            cmd0.val);

  return wait_command(drv, CMD_ID_WRITE, I3C_CMD_TIMEOUT_MS);
}

/*--------------------------------------------------------------
  Helper for issuing a single write command (CMD1 + CMD0),
  then waiting for completion.
---------------------------------------------------------------*/
static I3C_Status i3c_issue_write_stream_cmd(I3C_Driver *drv, uint8_t da,
                                             size_t length)
{

  // CMD1
  CDNSI3C_REG_CMD1_FIFO_reg_u cmd1 = {.val = 0};
  cmd1.f.cmd_id = CMD_ID_WRITE;
  cmd1.f.csraddr1 = 0;
  cmd1.f.ccc_csraddr0 = RX_FIFO;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD1_FIFO_REG_OFFSET,
            cmd1.val);

  // CMD0
  CDNSI3C_REG_CMD0_FIFO_reg_u cmd0 = {.val = 0};

  configure_base_command(&cmd0, da, length, I3C_CMD_XMIT_MODE_NCA,
                         false);
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD0_FIFO_REG_OFFSET,
            cmd0.val);

  //return wait_command(drv, CMD_ID_WRITE, I3C_CMD_TIMEOUT_MS);
  return I3C_OK;
}
/*--------------------------------------------------------------
  Helper for issuing a single read command (CMD1 + CMD0),
  then waiting for completion before we read FIFO data.
---------------------------------------------------------------*/
static I3C_Status i3c_issue_read_cmd(I3C_Driver *drv, uint8_t da,
                                     size_t length)
{
  // CMD1
  CDNSI3C_REG_CMD1_FIFO_reg_u cmd1 = {.val = 0};
  cmd1.f.cmd_id = CMD_ID_READ;
  cmd1.f.csraddr1 = 0;
  cmd1.f.ccc_csraddr0 = TX_FIFO;
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD1_FIFO_REG_OFFSET,
            cmd1.val);

  // CMD0
  CDNSI3C_REG_CMD0_FIFO_reg_u cmd0 = {.val = 0};
  // length + 1 since for single data transfer mode this value actually represents when to abort and setting it
  // to length causes premature abort error. See section 6.8.3.
  configure_base_command(&cmd0, da, length + 1, I3C_CMD_XMIT_MODE_NCA,
                         true);
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD0_FIFO_REG_OFFSET,
            cmd0.val);

  return wait_command(drv, CMD_ID_READ, I3C_CMD_TIMEOUT_MS);
}

/*--------------------------------------------------------------
  Initialize the I3C driver object
---------------------------------------------------------------*/
static I3C_Status I3C_Init(I3C_Driver *drv, uint8_t controller_id, uint64_t device_id,
                           I3C_Role role)
{
  if (drv == NULL || controller_id >= I3C_MAX_DEVICES)
  {
    return I3C_ERR_INVALID_ARG;
  }
  drv->ctx.role = role;
  drv->ctx.controller_id = controller_id;
  init_i3c_ctrl(controller_id, device_id, role);
  drv->ctx.initialized = true;
  return I3C_OK;
}

/*--------------------------------------------------------------
  Start the I3C controller (disable ints, set prescalers, etc.)
---------------------------------------------------------------*/
static I3C_Status I3C_Start(I3C_Driver *drv, int sys_clk_freq)
{
  if (!drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }
  CDNSI3C_REG_MST_IDR_reg_u reg_mst_idr = {.val = 0xFFFFFFFF};
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_IDR_REG_OFFSET,
            reg_mst_idr.val);

  CDNSI3C_REG_PRESCL_CTRL0_reg_u reg_prescl_ctrl0;

  if (sys_clk_freq == 100)
  {
    reg_prescl_ctrl0.f.i2c = 0x13;
    reg_prescl_ctrl0.f.i3c = 0x1;
  }
  else if (sys_clk_freq == 150)
  {
    reg_prescl_ctrl0.f.i2c = 0x4a;
    reg_prescl_ctrl0.f.i3c = 0x2;
  }
  else if (sys_clk_freq == 200)
  {
    reg_prescl_ctrl0.f.i2c = 0x63;
    reg_prescl_ctrl0.f.i3c = 0x3;
  }
  else
  {
    return I3C_ERR_INVALID_ARG;
  }

  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_PRESCL_CTRL0_REG_OFFSET,
            reg_prescl_ctrl0.val);
  CDNSI3C_REG_PRESCL_CTRL1_reg_u reg_prescl_ctrl1 = {.val = 0x00000009};
  write_i3c(drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_PRESCL_CTRL1_REG_OFFSET,
            reg_prescl_ctrl1.val);

  if (drv->ctx.role != SUBORDINATE)
  {
    CDNSI3C_REG_DEVS_CTRL_reg_u reg_devs_ctrl = {.val = 0x0};
    reg_devs_ctrl.f.dev0_active = 1;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_DEVS_CTRL_REG_OFFSET,
              reg_devs_ctrl.val);

    CDNSI3C_REG_MST_IER_reg_u reg_mst_ier = {.val = 0x0007dfff};
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_IER_REG_OFFSET,
              reg_mst_ier.val);

    CDNSI3C_REG_TX_RX_THR_CTRL_reg_u thr_ctrl = {.val = 0x0};
    thr_ctrl.f.tx_thr = 2;
    thr_ctrl.f.rx_thr = 2;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_TX_RX_THR_CTRL_REG_OFFSET,
              thr_ctrl.val);

    CDNSI3C_REG_CMD_IBI_THR_CTRL_reg_u reg_cmd_ibi_thr_ctrl = {.val = 0x0};
    reg_cmd_ibi_thr_ctrl.f.cmdd_thr = 0x4;
    reg_cmd_ibi_thr_ctrl.f.ibid_thr = 0x4;
    reg_cmd_ibi_thr_ctrl.f.cmdr_thr = 0x4;
    reg_cmd_ibi_thr_ctrl.f.ibir_thr = 0x4;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD_IBI_THR_CTRL_REG_OFFSET,
              reg_cmd_ibi_thr_ctrl.val);

    simputs("Device Initialized\n");
    CDNSI3C_REG_CTRL_reg_u reg_ctrl = {.val = 0x0};
    reg_ctrl.f.mst_ack = 1;
    reg_ctrl.f.hj_ack = 1;
    reg_ctrl.f.thd_del = 0x2;
    reg_ctrl.f.bus_mode = I3C_BUS_MODE_PURE;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CTRL_REG_OFFSET,
              reg_ctrl.val);

    simputs("Enabling Core\n");
    reg_ctrl.f.dev_en = 1;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CTRL_REG_OFFSET,
              reg_ctrl.val);
  }
  else
  {
    simputs("slave initialization\n");
    CDNSI3C_REG_SLV_CTRL_reg_u reg_slv_ctrl = {.val = 0x0};
    reg_slv_ctrl.f.pr_pl = 0x20;
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_CTRL_REG_OFFSET,
              reg_slv_ctrl.val);
    CDNSI3C_REG_MST_IER_reg_u mst_ier = {.val = 0x0};
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_IER_REG_OFFSET,
              mst_ier.val);
    CDNSI3C_REG_TX_RX_THR_CTRL_reg_u reg_tx_rx_thr_ctrl = {.f.tx_thr = 0,
                                                           .f.rx_thr = 0};
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_TX_RX_THR_CTRL_REG_OFFSET,
              reg_tx_rx_thr_ctrl.val);

    CDNSI3C_REG_CMD_IBI_THR_CTRL_reg_u reg_cmd_ibi_thr_ctrl = {
        .f.cmdd_thr = 0x0,
        .f.ibid_thr = 0x0,
        .f.cmdr_thr = 0x0,
        .f.ibir_thr = 0x0};
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMD_IBI_THR_CTRL_REG_OFFSET,
              reg_cmd_ibi_thr_ctrl.val);

    CDNSI3C_REG_SLV_IER_reg_u reg_slv_ier = {.val = 0x0};
    write_i3c(drv->ctx.controller_id,
              SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_IER_REG_OFFSET,
              reg_slv_ier.val);
  }
  return I3C_OK;
}

/*--------------------------------------------------------------
  Write data in chunk(s) to a slave device.
---------------------------------------------------------------*/
static I3C_Status I3C_Write(I3C_Driver *drv, uint8_t da, const uint8_t *data,
                            size_t length)
{
  if (!drv->ctx.initialized)
    return I3C_ERR_HW;

  size_t remaining = length;
  const uint8_t *ptr = data;

  // write in chunks of fifo depth bytes
  while (remaining > 0)
  {  size_t chunk_size =
        (remaining > (FIFO_DEPTH * 4)) ? (FIFO_DEPTH * 4) : remaining;
    I3C_Status st = fifo_write(drv, ptr, chunk_size);
    if (st != I3C_OK)
      return st;

    st = i3c_issue_write_cmd(drv, da, chunk_size);
    if (st != I3C_OK)
      return I3C_ERR_CMD_FAILED;

    ptr += chunk_size;
    remaining -= chunk_size;
  }
  return I3C_OK;
}

static I3C_Status fifo_read_full_width(I3C_Driver *drv, uint8_t *buffer, size_t length,
                                       size_t *bytes_read)
{
  if (drv == NULL || !drv->ctx.initialized || buffer == NULL)
  {
    return I3C_ERR_HW;
  }
  uint8_t controller_id = drv->ctx.controller_id;
  size_t total_bytes_read = 0;

  while(total_bytes_read < length)
  {
    uint32_t timeout = FIFO_WAIT_TIMEOUT;
    CDNSI3C_REG_MST_STATUS0_reg_u status;

    // Wait for at least one byte to be available in the RX FIFO.
    while (timeout > 0)
    {
      status.val =
          read_i3c(controller_id,
                   SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET);
      if (!status.f.rx_emp)
      {
        break;
      }
      timeout--;
    }
    if (timeout == 0)
    {
      simputs("Timeout waiting for data in RX FIFO\n");
      return I3C_ERR_TIMEOUT;
    }

    // Read four bytes from the FIFO or less if remaining bytes are less than 4.
    size_t remaining = length - total_bytes_read;
    size_t bytes_to_read = (remaining > 4) ? 4 : remaining;
    uint32_t raw = read_i3c(
        controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_REG_OFFSET);
    for(size_t i = 0; i < bytes_to_read; i++)
    {
      buffer[(total_bytes_read + i)] = (uint8_t)((raw >> (i * 8)) & 0xFF);
    }
    total_bytes_read += bytes_to_read;
  }

  if (bytes_read)
  {
    *bytes_read = total_bytes_read;
  }
  return I3C_OK;
}
/*--------------------------------------------------------------
  Read data in chunk(s) from a slave device.
---------------------------------------------------------------*/
static I3C_Status I3C_Read(I3C_Driver *drv, uint8_t da, uint8_t *buffer,
                           size_t length)
{
  if (!drv->ctx.initialized)
    return I3C_ERR_HW;

  CDNSI3C_REG_RX_FIFO_STATUS_reg_u rx_stat = {
      .val = read_i3c(
          drv->ctx.controller_id,
          SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_STATUS_REG_OFFSET)};

  uint32_t available = rx_stat.f.rx_fifo_fill_lvl * I3C_FIFO_WORD_SIZE;

  I3C_Status st;
  if (available == 0) {
    // set to MRL + 1 to ensure we get all the data (unknown payload size)
    // refer section 6.8.3 of Cadence I3C spec
    st = i3c_issue_read_cmd(drv, da, 2081);
    if (st != I3C_OK)
      return I3C_ERR_CMD_FAILED;
  }

  size_t bytes_read = 0;
  st = I3C_ReceivePayloadStream(drv, buffer, length, &bytes_read);
  if (st != I3C_OK)
    return I3C_ERR_CMD_FAILED;

  CDNSI3C_REG_MST_STATUS0_reg_u mst_status0 = {.val = read_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET)};
  // empty cmdr fifo
  while (!mst_status0.f.cmdr_emp) {
    // pop from CMDR FIFO
    CDNSI3C_REG_CMDR_reg_u cmdr = {.val = read_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_CMDR_REG_OFFSET)};
    if (cmdr.f.error != 0) {
      decode_cmdr_error(cmdr.f.error);
      return I3C_ERR_CMD_FAILED;
    } else if (cmdr.f.cmd_id != CMD_ID_READ) {
      simputs("Error: Unexpected command ID\n");
      simputshex32("Expected: ", CMD_ID_READ);
      simputshex32("Received: ", cmdr.f.cmd_id);
      return I3C_ERR_CMD_FAILED;
    }
    mst_status0.val = read_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_MST_STATUS0_REG_OFFSET);
  }
  return I3C_OK;
}

/*--------------------------------------------------------------
  Send a single payload (no internal chunking).
---------------------------------------------------------------*/
static I3C_Status I3C_SendPayload(I3C_Driver *drv, const uint8_t addr,
                                  const uint8_t *data, size_t length)
{
  if (drv == NULL || !drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }

  I3C_Status status = I3C_OK;
  for (size_t i = 0; i < length; i++)
  {
    status = fifo_write(drv, data+i, 1);
    if (status != I3C_OK)
    {
      return status;
    }
    status = i3c_issue_write_cmd(drv, addr, 1);
    if (status != I3C_OK)
    {
      return status;
    }
  }
  return status;
}

/*--------------------------------------------------------------
  Send a single payload (no internal chunking).
---------------------------------------------------------------*/
static I3C_Status I3C_SendPayloadStream(I3C_Driver *drv, const uint8_t addr,
                                        const uint8_t *data, size_t length)
{
  if (drv == NULL || !drv->ctx.initialized)
  {
    return I3C_ERR_HW;
  }

  // initially seed the fifo with the first chunk of data which will begin transferring immediately
  int initial_write_size = (length > FIFO_DEPTH * I3C_FIFO_WORD_SIZE) ? FIFO_DEPTH * I3C_FIFO_WORD_SIZE : length;

  I3C_Status status = fifo_write(drv, data, initial_write_size);
  if (status != I3C_OK)
  {
    return status;
  }

  // issue the write command to begin transfer
  status = i3c_issue_write_stream_cmd(drv, addr, length);
  if (status != I3C_OK)
  {
    return status;
  }

  // if there is more data to write, write the rest of the data which will be transferred in the background
  if (length > initial_write_size) {
    status = fifo_write(drv, data + initial_write_size, length - initial_write_size);
    if (status != I3C_OK)
    {
      return status;
    }
  }

  return wait_command(drv, CMD_ID_WRITE, I3C_CMD_TIMEOUT_MS);
}


/*--------------------------------------------------------------
  Check how many bytes are in the RX FIFO.
---------------------------------------------------------------*/
static uint32_t I3C_CheckRxFifo(I3C_Driver *drv)
{
  if (drv == NULL || !drv->ctx.initialized)
  {
    return 0;
  }
  CDNSI3C_REG_RX_FIFO_STATUS_reg_u reg_rx_fifo_status = {
      .val = read_i3c(
          drv->ctx.controller_id,
          SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_STATUS_REG_OFFSET)};
  return reg_rx_fifo_status.f.rx_fifo_fill_lvl;
}

/*--------------------------------------------------------------
  Receive up to buffer_length bytes from the RX FIFO.
---------------------------------------------------------------*/
static I3C_Status I3C_ReceivePayload(I3C_Driver *drv, uint8_t *buffer,
                                     size_t buffer_length,
                                     size_t *bytes_received)
{
  if (drv == NULL || !drv->ctx.initialized || buffer == NULL)
  {
    return I3C_ERR_HW;
  }
  size_t total_read = 0;
  I3C_Status status = I3C_OK;
  uint32_t no_data_counter = 0;
  const uint32_t NO_DATA_THRESHOLD = 10000;

  while (total_read < buffer_length)
  {
    CDNSI3C_REG_RX_FIFO_STATUS_reg_u rx_stat = {
        .val = read_i3c(
            drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_STATUS_REG_OFFSET)};
    uint32_t available = rx_stat.f.rx_fifo_fill_lvl;

    if (available == 0)
    {
      no_data_counter++;
      if (no_data_counter >= NO_DATA_THRESHOLD)
      {
        break;
      }
      continue;
    }
    no_data_counter = 0;

    size_t remaining = buffer_length - total_read;
    size_t to_read = (available < remaining) ? available : remaining;

    size_t read_count = 0;
    status = fifo_read(drv, buffer + total_read, to_read, &read_count);
    if (status != I3C_OK)
    {
      return status;
    }
    total_read += read_count;
  }

  if (bytes_received)
  {
    *bytes_received = total_read;
  }
  simputshex16("Received: ", total_read);
  return status;
}

/*--------------------------------------------------------------
  Receive up to buffer_length bytes from the RX FIFO.

  Buffer length must be the full size of the expected payload
  or a multiple of I3C_FIFO_WORD_SIZE or you may discard data.
---------------------------------------------------------------*/
static I3C_Status I3C_ReceivePayloadStream(I3C_Driver *drv, uint8_t *buffer,
                                           size_t buffer_length,
                                           size_t *bytes_received)
{
  if (drv == NULL || !drv->ctx.initialized || buffer == NULL)
  {
    return I3C_ERR_HW;
  }
  size_t total_read = 0;
  I3C_Status status = I3C_OK;
  uint32_t no_data_counter = 0;
  const uint32_t NO_DATA_THRESHOLD = 10000;

  while (total_read < buffer_length)
  {
    CDNSI3C_REG_RX_FIFO_STATUS_reg_u rx_stat = {
        .val = read_i3c(
            drv->ctx.controller_id,
            SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_RX_FIFO_STATUS_REG_OFFSET)};
    uint32_t available = rx_stat.f.rx_fifo_fill_lvl;

    if (available == 0)
    {
      no_data_counter++;
      if (no_data_counter >= NO_DATA_THRESHOLD)
      {
        break;
      }
      continue;
    }
    no_data_counter = 0;

    size_t remaining = buffer_length - total_read;
    size_t to_read = (available*I3C_FIFO_WORD_SIZE < remaining) ? available*I3C_FIFO_WORD_SIZE : remaining;

    size_t read_count = 0;
    status = fifo_read_full_width(drv, buffer + total_read, to_read, &read_count);
    if (status != I3C_OK)
    {
      return status;
    }
    total_read += read_count;
  }

  if (bytes_received)
  {
    *bytes_received = total_read;
  }
  simputshex16("Received: ", total_read);
  return status;
}
/*--------------------------------------------------------------
  Return the driver instance for a controller_id
---------------------------------------------------------------*/
I3C_Driver *I3C_GetDriverInstance(uint8_t controller_id)
{
  static I3C_Driver instances[I3C_MAX_DEVICES];
  static bool initialized[I3C_MAX_DEVICES] = {false};

  if (controller_id >= I3C_MAX_DEVICES)
  {
    return NULL;
  }
  I3C_Driver *drv = &instances[controller_id];

  if (!initialized[controller_id])
  {
    drv->init = I3C_Init;
    drv->start = I3C_Start;
    drv->issue_entdaa = I3C_IssueENTDAA;
    drv->issue_setgrpa = I3C_IssueSETGRPA;
    drv->wait_command = wait_command;
    drv->process_devices = I3C_ProcessDevices;
    drv->write = I3C_Write;
    drv->read = I3C_Read;
    drv->fifo_write = fifo_write;
    drv->fifo_read = fifo_read;

    drv->send_payload = I3C_SendPayload;
    drv->send_payload_stream = I3C_SendPayloadStream;
    drv->check_rx_fifo = I3C_CheckRxFifo;
    drv->receive_payload = I3C_ReceivePayload;
    drv->receive_payload_stream = I3C_ReceivePayloadStream;

    initialized[controller_id] = true;
  }
  return drv;
}
