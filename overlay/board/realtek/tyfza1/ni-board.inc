/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included by the imported DM NI driver, after its PHY/map helpers. */
#include "sgmii.h"

static int tyf_ni_phy_status(struct phy_device *phy)
{
	int value;
	if (!phy) return -ENODEV;
	if (phy->is_c45) return phy_startup(phy);
	phy->link = 0;
	value = phy_read(phy, MDIO_DEVAD_NONE, MII_BMSR);
	if (value < 0) return value;
	value = phy_read(phy, MDIO_DEVAD_NONE, MII_BMSR);
	if (value < 0) return value;
	if (!(value & BMSR_LSTATUS) || !(value & BMSR_ANEGCOMPLETE)) return 0;
	value = genphy_parse_link(phy);
	if (!value) phy->link = 1;
	return value;
}

static void tyf_gpio_output(unsigned int pin, bool value)
{
	unsigned long bank = 0xf43292c0 + (pin / 32) * 0x24;
	unsigned long mux = 0xf4320100 + (pin / 32) * 4;
	u32 bit = BIT(pin % 32);
	setbits_le32(mux, bit);
	clrsetbits_le32(bank + 4, bit, value ? bit : 0);
	clrbits_le32(bank, bit);
}

static int tyf_ni_board_prepare(struct cortina_ni_priv *priv)
{
	const char *variant = env_get("board_variant");
	u32 value;
	priv->maps[4].phy_id = -1;
	priv->maps[5].phy_id = -1;
	if (!variant || strcmp(variant, "2p5g")) return 0;
	priv->maps[4].phy_id = 7;
	priv->maps[4].sds_mode = AAL_SDS_MODE_SGMII;
	tyf_gpio_output(128, false);
	mdelay(30);
	tyf_gpio_output(128, true);
	mdelay(300);
	tyf_gpio_output(14, true);
	mdelay(300);
	/* Original S3 power and mux sequence; preserve adjacent USB/PCIe controls. */
	value = readl(0xf43200c4);
	writel((value | BIT(25)) & ~BIT(26), 0xf43200c4);
	value = readl(0xf432036c);
	writel((value | 0xc0080000) & ~0x6020, 0xf432036c);
	writel(0x5359, 0xf460001c);
	writel(0x30, 0xf43200d0);
	writel(0x34200248, 0xf43200d4);
	return 0;
}

static int tyf_ni_port4_speed(struct phy_device *phy)
{
	if (!phy || !phy->link || (phy->speed != 10 && phy->speed != 100 &&
	    phy->speed != 1000 && phy->speed != 2500)) return -EINVAL;
	rtl_sgmii_link((void *)0xf43200c4, (void *)0xf43200a0,
		       (void *)0xf43200d4, (void *)0xf433b000, phy->speed);
	return 0;
}

static int tyf_ni_refresh_link(struct cortina_ni_priv *priv)
{
	struct phy_device *phy;
	int old_port = priv->active_port, speed = -1, duplex = -1, ret;
	if (!priv->is_phyinited || get_timer(priv->link_polled) < 250) return 0;
	priv->link_polled = get_timer(0);
	phy = __get_curr_phydev(priv);
	if (phy) { speed = phy->speed; duplex = phy->duplex; }
	ret = tyf_ni_phy_status(phy);
	if (ret || !phy || !phy->link) {
		if (phy) phy->link = 0;
		ni_auto_scan_active_port(priv);
		phy = __get_curr_phydev(priv);
	}
	if (phy && phy->link && old_port == priv->active_port &&
	    speed == phy->speed && duplex == phy->duplex) return 0;
	if (old_port >= 0 && is_valid_port(priv, old_port)) ni_enable_tx_rx(old_port, 0);
	if (!phy || !phy->link) { priv->phydev = NULL; return 0; }
	if (priv->active_port == 4 && (ret = tyf_ni_port4_speed(phy))) return ret;
	ret = priv->aal_mode_sync(priv->active_port, priv->maps[priv->active_port].sds_mode, phy);
	if (ret) return ret;
	priv->aal_set_active_port(priv->active_port);
	priv->phydev = phy;
	ni_enable_tx_rx(priv->active_port, 1);
	printf("Recovery link: port %d, %d Mbps\n", priv->active_port, phy->speed);
	return 0;
}
