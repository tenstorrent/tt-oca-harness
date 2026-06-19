#include "metal/interrupt.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "atomic.h"
#include <stdio.h>
#include "virt_console.h"

#define NUM_SMC_MAILBOXES (32)

_Atomic volatile int core_setup_done[4] = {0, 0, 0, 0};
char debug_msg[100][4];

void mailbox_interrupt_handler(int id, void *priv)
{
	// Determine which mailbox triggered the interrupt based on 'id'
	int mailbox_id = id - (MAILBOX_INTERUPT_ID_BASE + 1); // Reverse mapping

	// Read the mailbox
	uint64_t mailbox_data = read_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR));

	simputshex16("Core:", metal_cpu_get_current_hartid());
	simputshex16("Interrupted by Mailbox ID", mailbox_id);
	simputshex32("Mailbox Data:", mailbox_data);

	// Validate that the correct core triggered the interrupt
	if (mailbox_id != ((metal_cpu_get_current_hartid() - 1) % 4))
	{
		simputs("Unexpected mailbox interrupt!");
		test_fail(0);
	}

	// Flush the mailbox data
	simputs("Mailbox data validated, flushing mailbox...");
	write_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR), 0b11);

	// Clear the pending interrupt in the mailbox's IRQS register
	simputs("Clearing pending interrupt in mailbox IRQS register...");
	write_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR), 1);
}

static void reset_plic_enable_registers()
{
	simputs("Clearing PLIC registers\n");
	for (uint64_t addr = SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0);
		 addr <= SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_ENABLE_BASE_ADDR(6); addr += 4)
	{
		write_reg(addr, 0x0);
	}

	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_BASE_ADDR, 0x0);
	write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_BASE_ADDR, 0x0);
}

void write_mailbox_int(int mailbox_id)
{
	// Set Write Interrupt Request Threshold for mailbox 0
	write_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR), 0);

	// Enable write threshold interrupt for mailbox 0
	write_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR), 1);

	// Write data to mailbox 0
	write_mailbox(mailbox_id, 1, (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR - SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR), 0xdeadbeef);
}

int main(void)
{

	// Mask AVSBUS interrupts
	avsbus_controller__AVS_INTERRUPT_MASK_t avsbus_mask_interrupts;
	avsbus_mask_interrupts.w = 0xffffffff;
	write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_MASK_BASE_ADDR, avsbus_mask_interrupts.w);

	int hartid = metal_cpu_get_current_hartid();

	write_scratch(1, hartid);

	struct metal_interrupt *plic_controller;
	struct metal_cpu *cpu;
	struct metal_interrupt *cpu_controller;

	// get PLIC interrupt controller
	plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, hartid);

	cpu = metal_cpu_get(hartid);
	cpu_controller = metal_cpu_interrupt_controller(cpu);

	// enable external interrupts in the cpu
	metal_interrupt_init(cpu_controller);
	metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);
	metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_EXT);

	// If we are Core 0, set up PLIC, then send an interrupt to mailbox 0
	if (hartid == 0)
	{
		// init the plic and register interrupt handler
		metal_interrupt_init(plic_controller);

		// Reset PLIC registers
		reset_plic_enable_registers();

		int interrupt_id = MAILBOX_INTERUPT_ID_BASE + 3 + 1;			// Mailbox 3 interrupts core 0
		metal_interrupt_set_priority(plic_controller, interrupt_id, 1); // Set priority
		if (metal_interrupt_register_handler(plic_controller, interrupt_id, mailbox_interrupt_handler, NULL) != 0)
		{
			simputs("Failed to register interrupt handler");
			test_fail(0);
		}
		metal_interrupt_enable(plic_controller, interrupt_id - 1);

		__metal_interrupt_global_enable();

		// Atomically store, so other cores can see this setup is done
		metal_atomic_swap(&core_setup_done[0], 1);

		simputs("Core 0: Setup done, waiting for interrupts...");

		// Wait for other cores to set up
		while (metal_atomic_add(&core_setup_done[1], 0) == 0 ||
			   metal_atomic_add(&core_setup_done[2], 0) == 0 ||
			   metal_atomic_add(&core_setup_done[3], 0) == 0)
		{
			__asm__ volatile("" ::: "memory");
		}

		// Send mailbox interrupt
		write_mailbox_int(0);

		// Send interrupt to mailbox 0
		simputs("Sent interrupt to mailbox 0\n");

		// wait for an interrupt
		__asm__ volatile("wfi");

		// If core 0 was interrupted, then test was successful
		test_pass(hartid);
	}
	else
	{
		while (metal_atomic_add(&core_setup_done[0], 0) == 0)
		{
			__asm__ volatile("" ::: "memory");
		}

		// Expects an interrupt from mailbox hartid - 1, ie Core 1 expects from mailbox 0 (Core 0)
		int interrupt_id = MAILBOX_INTERUPT_ID_BASE + hartid;

		metal_interrupt_set_priority(plic_controller, interrupt_id, 1); // Set priority
		if (metal_interrupt_register_handler(plic_controller, interrupt_id, mailbox_interrupt_handler, NULL) != 0)
		{
			snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]),
					 "Core %d: Failed to register interrupt handler for mailbox %d\n", hartid, hartid - 1);
			simputs(debug_msg[hartid]);
			test_fail(hartid);
		}
		metal_interrupt_enable(plic_controller, interrupt_id);

		__metal_interrupt_global_enable();

		snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]), "Core %d: Setup done, waiting for interrupt...\n", hartid);
		simputs(debug_msg[hartid]);

		// Say that this core is set up
		metal_atomic_swap(&core_setup_done[hartid], 1);

		__asm__ volatile("wfi");

		// Send mailbox interrupt
		write_mailbox_int(hartid);

		// Send interrupt to mailbox hartid
		snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]), "Sent interrupt to mailbox %d\n", hartid);
		simputs(debug_msg[hartid]);

		// wait for an interrupt
		__asm__ volatile("wfi");
	}

	return 0;
}

int secondary_main(void)
{
	return main();
}