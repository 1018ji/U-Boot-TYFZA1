// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <env.h>
#include <asm/io.h>
#include <linux/delay.h>
#include <string.h>
#include <tyfza1_recovery.h>

#define GPIO_MUX 0xf4320100UL
#define GPIO_DIR 0xf43292c0UL
#define GPIO_OUT 0xf43292c4UL
#define GPIO_IN  0xf43292c8UL

int tyfza1_reset_held(void)
{
	u32 pin = 1U << 8;
	unsigned int i;
	setbits_le32(GPIO_MUX, pin);
	setbits_le32(GPIO_DIR, pin);
	/* Sample before PHY discovery, so releasing Reset during it is harmless. */
	for (i = 0; i < 3; i++) {
		if (readl(GPIO_IN) & pin) return 0;
		udelay(1000);
	}
	return 1;
}

void tyfza1_boot_leds(void)
{
	static const unsigned int four_ge[] = { 4, 3, 1, 0 };
	static const unsigned int two_p5g[] = { 11, 12, 3, 4 };
	const char *variant = env_get("board_variant");
	const unsigned int *pins;
	u32 mask = 0, low, mux, dir, out;
	unsigned int i;
	if (!variant) return;
	if (!strcmp(variant, "4ge")) {
		pins = four_ge;
		low = (1U << 4) | (1U << 3) | (1U << 1) | 1;
	} else if (!strcmp(variant, "2p5g")) {
		pins = two_p5g;
		low = (1U << 3) | (1U << 4);
	} else {
		return;
	}
	for (i = 0; i < 4; i++) mask |= 1U << pins[i];
	mux = readl(GPIO_MUX);
	dir = readl(GPIO_DIR);
	out = readl(GPIO_OUT);
	clrsetbits_le32(GPIO_OUT, mask, low);
	setbits_le32(GPIO_MUX, mask);
	clrbits_le32(GPIO_DIR, mask);
	for (i = 0; i < 4; i++) {
		clrsetbits_le32(GPIO_OUT, mask, low ^ (1U << pins[i]));
		mdelay(150);
		clrsetbits_le32(GPIO_OUT, mask, low);
	}
	/* Return the pins to their previous LED/hardware ownership. */
	clrsetbits_le32(GPIO_OUT, mask, out & mask);
	clrsetbits_le32(GPIO_DIR, mask, dir & mask);
	clrsetbits_le32(GPIO_MUX, mask, mux & mask);
}
