
#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

METAL_LOCK_DECLARE(mmio_lock);
METAL_ATOMIC_DECLARE(shared_counter);

volatile bool _start_other = 0;
static uint32_t checkin_count = 0;

int main(void)
{
    int hartid = metal_cpu_get_current_hartid();

    uint32_t read_data;

    // Access EFUSE interface control registers.
    write_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR, 2000);
    read_data = read_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR);
    write_scratch(1, read_data);
    if (read_data != 2000)
    {
        test_fail(hartid);
    }

    // do a negative test to make sure addresses that should be able to be written to are valid
    efuse_interface_ctrl__EFUSE_INTERFACE_CTRL_STATUS_t efuse_ctrl_status = {.w = 0x0};
    efuse_ctrl_status.f.efuse_sense_done = 0x0;
    efuse_ctrl_status.f.efuse_req_error = 0x1;

    write_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR, efuse_ctrl_status.w); // magic number targetting read only fields //replace
    read_data = read_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR); //replace
    write_scratch(1, read_data);
    if (read_data == efuse_ctrl_status.w)
    {
        test_fail(hartid);
    }

    write_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR, 0x12345); // this entire field is SW read only
    read_data = read_reg(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR);
    write_scratch(1, read_data);
    if (read_data == 0x12345)
    {
        test_fail(hartid);
    }

    test_pass(hartid);

    while (true)
    {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid)
{
    while (true)
    {
        __asm__("wfi");
    }
}

int secondary_main(void)
{
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0)
    {
        return main();
    }
    else
    {
        return other_main(hartid);
    }
}
