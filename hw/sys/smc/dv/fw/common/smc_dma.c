#include "smc_dma.h"

#include "smc_defines.h"

void smc_dma_init()
{
  write_dma_ctrl_reg(DMA_CTRL_NUM_REPETITIONS_LO_REG_OFFSET, 0x1);
  write_dma_ctrl_reg(DMA_CTRL_CONFIG_REG_OFFSET, 0x400);
}

void smc_dma_config(dma_config_u *config)
{
  write_dma_ctrl_reg(DMA_CTRL_CONFIG_REG_OFFSET, config->val);
}

bool smc_dma_is_idle()
{
  return (read_dma_ctrl_reg(DMA_CTRL_STATUS_0_REG_OFFSET) & 0x3FF) == 0;
}

void smc_dma_wait_idle()
{
  do
  {
  } while (!smc_dma_is_idle());
}

dma_err_e smc_dma_issue_cmd(dma_cmd_t *cmd)
{
  write_dma_ctrl_reg(DMA_CTRL_SRC_ADDRESS_LO_REG_OFFSET, cmd->src_addr);
  write_dma_ctrl_reg(DMA_CTRL_SRC_STRIDE_LO_REG_OFFSET, cmd->src_stride);
  write_dma_ctrl_reg(DMA_CTRL_DST_ADDRESS_LO_REG_OFFSET, cmd->dst_addr);
  write_dma_ctrl_reg(DMA_CTRL_DST_STRIDE_LO_REG_OFFSET, cmd->dst_stride);
  write_dma_ctrl_reg(DMA_CTRL_LENGTH_LO_REG_OFFSET, cmd->length);
  write_dma_ctrl_reg(DMA_CTRL_NUM_REPETITIONS_LO_REG_OFFSET, cmd->num_blocks);
  //   smc_dma_wait_idle();
  cmd->id = read_dma_ctrl_reg(DMA_CTRL_NEXT_ID_0_REG_OFFSET);
  if (cmd->id != 0)
  {
    return SMC_DMA_OK;
  }
  return SMC_DMA_OK;
}

void smc_dma_wait_cmd_done(dma_cmd_t *cmd)
{
  do
  {
  } while ((uint32_t)read_dma_ctrl_reg(DMA_CTRL_DONE_0_REG_OFFSET) !=
           cmd->id);
}
