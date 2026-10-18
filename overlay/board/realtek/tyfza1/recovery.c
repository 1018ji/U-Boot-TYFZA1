// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <command.h>
#include <env.h>
#include <image.h>
#include <malloc.h>
#include <memalign.h>
#include <mapmem.h>
#include <mtd.h>
#include <stdio.h>
#include <ubi_uboot.h>
#include <tyfza1_recovery.h>
#include <lzma/LzmaTools.h>
#include <linux/libfdt.h>
#include "formats.h"

static int volume_verify(char *name, const void *data, size_t length,
			 void (*poll)(void))
{
	unsigned char *check = malloc_cache_aligned(0x10000);
	const unsigned char *input = data;
	size_t off, chunk;
	int ret = -ENOMEM;
	if (!check) return ret;
	for (off = 0; off < length; off += chunk) {
		chunk = min_t(size_t, 0x10000, length - off);
		ret = ubi_volume_read_quiet(name, (char *)check, off, chunk);
		if (ret || memcmp(check, input + off, chunk)) {
			ret = ret ? ret : -EIO;
			break;
		}
		poll();
	}
	free(check);
	return ret;
}

static int verify_fit(const struct tyf_payload *image)
{
	const void *data;
	const char *conf = env_get("b_conf"), *variant = env_get("board_variant");
	void *dtb = NULL;
	size_t size;
	u8 comp;
	int node, fdt, images, child, ret = -EINVAL;
	if (!conf || !variant || (strcmp(variant, "4ge") && strcmp(variant, "2p5g")) ||
	    fit_check_format(image->data, image->size)) return -EINVAL;
	images = fdt_path_offset(image->data, FIT_IMAGES_PATH);
	if (images < 0) return -EINVAL;
	fdt_for_each_subnode(child, image->data, images) {
		uintptr_t start = (uintptr_t)image->data, at;
		if (fit_image_get_data(image->data, child, &data, &size)) return -EINVAL;
		at = (uintptr_t)data;
		if (at < start || size > image->size || at - start > image->size - size)
			return -EINVAL;
	}
	if (!fit_all_image_verify(image->data)) return -EINVAL;
	node = fit_conf_get_node(image->data, conf);
	if (node < 0) return node;
	fdt = fit_conf_get_prop_node(image->data, node, FIT_FDT_PROP, IH_PHASE_NONE);
	if (fdt < 0 || fit_image_get_data(image->data, fdt, &data, &size) ||
	    (const unsigned char *)data < image->data || size > image->size ||
	    (const unsigned char *)data - image->data > image->size - size ||
	    fit_image_get_comp(image->data, fdt, &comp)) return -EINVAL;
	if (comp == IH_COMP_LZMA) {
		SizeT output_size = 0x20000;
		dtb = malloc(output_size);
		if (!dtb) return -ENOMEM;
		if (lzmaBuffToBuffDecompress(dtb, &output_size, (unsigned char *)data, size))
			goto out;
		data = dtb;
		size = output_size;
	} else if (comp != IH_COMP_NONE) {
		goto out;
	}
	if (fdt_check_full(data, size)) goto out;
	ret = fdt_node_check_compatible(data, 0, !strcmp(variant, "2p5g") ?
		"tianyi,tyfza1-2p5g" : "tianyi,tyfza1");
	if (ret) ret = -EINVAL;
out:
	free(dtb);
	return ret;
}

int tyfza1_check_fit(ulong address, size_t size)
{
	struct tyf_payload image = { map_sysmem(address, size), size };
	int ret = verify_fit(&image);
	unmap_sysmem(image.data);
	return ret;
}

int tyfza1_boot_upload(ulong address, size_t size)
{
	int ret = tyfza1_check_fit(address, size);
	if (ret) return ret;
	/* Source the validated board script when present; otherwise select the board FIT explicitly. */
	env_set_hex("unzip_src", address);
	if (fdt_path_offset((void *)address, "/images/script") >= 0)
		return run_commandf("source %lx:script", address);
	return run_commandf("bootm %lx#%s", address, env_get("b_conf"));
}

static int resize_root(struct ubi_volume *root, int lebs)
{
	struct ubi_volume_desc *desc;
	int ret;
	desc = ubi_open_volume(root->ubi->ubi_num, root->vol_id, UBI_EXCLUSIVE);
	if (IS_ERR(desc)) return PTR_ERR(desc);
	ret = ubi_resize_volume(desc, lebs);
	ubi_close_volume(desc);
	return ret;
}

int tyfza1_install_system(ulong address, size_t size, void (*poll)(void))
{
	struct tyf_firmware fw;
	const void *input = map_sysmem(address, size);
	const char *committed = env_get("sw_commit"), *installed = env_get("tyfza1_slot");
	char kernel[16], root[16];
	char old_commit[2] = "0", old_active[2] = "0", old_try[2] = "2", old_slot[2] = "";
	struct ubi_device *ubi;
	struct ubi_volume *rootvol, *data;
	size_t capacity;
	int slot, root_lebs, available, ret = -EINVAL;

	if (committed && strcmp(committed, "0") && strcmp(committed, "1")) goto out;
	if (committed) old_commit[0] = committed[0];
	if (installed) {
		if (strcmp(installed, "0") && strcmp(installed, "1")) goto out;
		old_slot[0] = installed[0];
	}
	/* Keep reinstalling into OpenWrt's slot, preserving the original OEM slot. */
	slot = installed ? old_slot[0] - '0' : old_commit[0] == '0' ? 1 : 0;
	if (env_get("sw_active")) old_active[0] = env_get("sw_active")[0];
	if (env_get("sw_tryactive")) old_try[0] = env_get("sw_tryactive")[0];
	if (tyf_parse_sysupgrade(input, size, &fw) || verify_fit(&fw.kernel)) {
		puts("Expected a TYFZA1 sysupgrade archive with a matching, hash-verified FIT and SquashFS.\n");
		goto out;
	}
	ret = ubi_part("ubi_device", NULL);
	if (ret) goto out;
	snprintf(kernel, sizeof(kernel), "ubi_k%d", slot);
	snprintf(root, sizeof(root), "ubi_r%d", slot);
	ret = ubi_volume_get_size(kernel, NULL, &capacity);
	if (ret || fw.kernel.size > capacity) { ret = -EFBIG; goto out; }
	ubi = ubi_devices[0];
	rootvol = ubi->volumes[slot ? 7 : 4];
	data = ubi->volumes[11];
	if (!rootvol || strcmp(rootvol->name, root) ||
	    (data && strcmp(data->name, "rootfs_data")) ||
	    fw.root.size > 33648640) { ret = -EINVAL; goto out; }
	root_lebs = DIV_ROUND_UP(fw.root.size, rootvol->usable_leb_size);
	available = ubi->avail_pebs + rootvol->reserved_pebs + (data ? data->reserved_pebs : 0);
	if (available - root_lebs < DIV_ROUND_UP(16777216, ubi->leb_size)) {
		ret = -ENOSPC; goto out;
	}
	if (root_lebs > rootvol->reserved_pebs) {
		if (root_lebs - rootvol->reserved_pebs > ubi->avail_pebs && data) {
			ret = ubi_volume_remove("rootfs_data");
			if (ret) goto out;
			data = NULL;
		}
		ret = resize_root(rootvol, root_lebs);
		if (ret) goto out;
	}
	printf("Installing OpenWrt in slot %d; factory volumes are retained.\n", slot);
	ret = ubi_volume_write(root, (void *)fw.root.data, 0, fw.root.size);
	if (!ret) ret = volume_verify(root, fw.root.data, fw.root.size, poll);
	if (ret) goto out;
	ret = ubi_volume_write(kernel, (void *)fw.kernel.data, 0, fw.kernel.size);
	if (!ret) ret = volume_verify(kernel, fw.kernel.data, fw.kernel.size, poll);
	if (ret) goto out;
	ret = resize_root(rootvol, root_lebs);
	if (ret) goto out;
	if (data && (ret = ubi_volume_remove("rootfs_data"))) goto out;
	ret = run_command("ubi create rootfs_data 0 d b", 0);
	if (ret) goto out;
	/* Commit only after both new volumes have passed independent readback. */
	env_set("sw_commit", slot ? "1" : "0");
	env_set("sw_active", slot ? "1" : "0");
	env_set("sw_tryactive", "2");
	env_set("tyfza1_slot", slot ? "1" : "0");
	ret = env_save();
	if (ret) {
		env_set("sw_commit", old_commit);
		env_set("sw_active", old_active);
		env_set("sw_tryactive", old_try);
		env_set("tyfza1_slot", old_slot[0] ? old_slot : NULL);
	} else {
		printf("Slot %d written, read back and committed.\n", slot);
	}
out:
	unmap_sysmem(input);
	return ret;
}

static int read_mtd(struct mtd_info *mtd, size_t offset, size_t length, void *out)
{
	size_t done;
	int ret = mtd_read(mtd, offset, length, &done, out);
	if (ret == -EUCLEAN && done == length) ret = 0;
	return ret ? ret : done == length ? 0 : -EIO;
}

int tyfza1_validate_loader(ulong address, size_t size)
{
	struct tyf_fip next;
	const unsigned char *input = map_sysmem(address, size);
	unsigned char *current = NULL;
	struct mtd_info *mtd = NULL;
	int ret = -EINVAL;

	if (tyf_parse_loader(input, size, &next) || tyfza1_loader_certificates(input, size)) goto out;
	mtd_probe_devices();
	mtd = get_mtd_device_nm("boot");
	if (IS_ERR(mtd)) { ret = PTR_ERR(mtd); mtd = NULL; goto out; }
	if (mtd->size != TYF_BOOT_SIZE || mtd->erasesize != 0x20000 ||
	    mtd->writesize != 0x800) goto out;
	current = malloc_cache_aligned(TYF_BOOT_SIZE);
	if (!current) { ret = -ENOMEM; goto out; }
	ret = read_mtd(mtd, 0, TYF_BOOT_SIZE, current);
	if (ret) goto out;
	ret = tyf_loader_preserves_device(input, size, current, TYF_BOOT_SIZE) ? -EINVAL : 0;
	if (ret)
		puts("Loader must preserve this device's GPT, BL2, BL31 and reserved bytes.\n");
out:
	free(current);
	if (mtd) put_mtd_device(mtd);
	unmap_sysmem(input);
	return ret;
}

int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void))
{
	const unsigned char *input;
	const void *bundle;
	struct tyf_payload selected;
	unsigned char *check = NULL;
	struct mtd_info *mtd;
	size_t base, offset, done;
	int copy, ret;
	/* Taurus has no separate AN758x preloader partition. */
	if (bl2) return -EINVAL;
	bundle = map_sysmem(address, size);
	ret = tyf_select_loader(bundle, size, env_get("board_variant"), &selected);
	if (!ret) {
		address = map_to_sysmem(selected.data);
		size = selected.size;
	}
	unmap_sysmem(bundle);
	if (ret) return -EINVAL;
	ret = tyfza1_validate_loader(address, size);
	if (ret) return ret;
	input = map_sysmem(address, size);
	mtd = get_mtd_device_nm("boot");
	if (IS_ERR(mtd)) { unmap_sysmem(input); return PTR_ERR(mtd); }
	check = malloc_cache_aligned(mtd->erasesize);
	if (!check) { ret = -ENOMEM; goto out; }
	for (offset = TYF_FIP0_OFFSET; offset < 0x1c0000; offset += mtd->erasesize) {
		ret = mtd_block_isbad(mtd, offset);
		if (ret) { ret = ret < 0 ? ret : -EIO; goto out; }
	}
	/* Finish and verify FIP1 before touching FIP0. No offset shifting in boot. */
	for (copy = 1; copy >= 0; copy--) {
		base = copy ? TYF_FIP1_OFFSET : TYF_FIP0_OFFSET;
		for (offset = base; offset < base + TYF_FIP_SIZE; offset += mtd->erasesize) {
			struct erase_info erase = { .mtd = mtd, .addr = offset, .len = mtd->erasesize };
			ret = mtd_erase(mtd, &erase);
			if (ret) goto out;
			ret = mtd_write(mtd, offset, mtd->erasesize, &done, input + offset);
			if (ret || done != mtd->erasesize) { ret = ret ? ret : -EIO; goto out; }
			ret = read_mtd(mtd, offset, mtd->erasesize, check);
			if (ret || memcmp(check, input + offset, mtd->erasesize)) {
				ret = ret ? ret : -EIO;
				goto out;
			}
			poll();
		}
		printf("FIP%d written and read back.\n", copy);
	}
out:
	free(check);
	put_mtd_device(mtd);
	unmap_sysmem(input);
	return ret;
}

struct preserved_volume {
	const char *name;
	size_t size;
	void *data;
};

int tyfza1_rebuild_ubi(void (*poll)(void))
{
	static const struct { const char *name; unsigned int size; } layout[] = {
		{ "ubi_Config", 0x60e000 }, { "ubi_fpga", 0x41e000 },
		{ "ubi_DTB0", 0x5d000 }, { "ubi_k0", 0x60e000 }, { "ubi_r0", 0x2017000 },
		{ "ubi_DTB1", 0x5d000 }, { "ubi_k1", 0x60e000 }, { "ubi_r1", 0x2017000 },
		{ "ubi_framework1", 0x101b000 }, { "ubi_framework2", 0x101b000 },
		{ "ubi_apps", 0x6007000 }, { "rootfs_data", 0x1000000 },
	};
	struct preserved_volume keep[] = {
		{ "ubi_Config", 0, NULL }, { "ubi_fpga", 0, NULL },
		{ "ubi_DTB0", 0, NULL }, { "ubi_DTB1", 0, NULL },
	};
	struct mtd_info *mtd = NULL;
	size_t offset;
	unsigned int i;
	int ret = ubi_part("ubi_device", NULL);
	if (ret) return ret;
	/* Copy all optical/radio identity and FPGA/DT volumes before erasing anything. */
	for (i = 0; i < ARRAY_SIZE(keep); i++) {
		ret = ubi_volume_get_size(keep[i].name, &keep[i].size, NULL);
		if (ret || !keep[i].size || keep[i].size > 0x800000) {
			ret = ret ? ret : -EINVAL; goto out;
		}
		keep[i].data = malloc_cache_aligned(keep[i].size);
		if (!keep[i].data) { ret = -ENOMEM; goto out; }
		ret = ubi_volume_read((char *)keep[i].name, keep[i].data, 0, keep[i].size);
		if (ret) goto out;
		poll();
	}
	ret = ubi_detach();
	if (ret) goto out;
	mtd_probe_devices();
	mtd = get_mtd_device_nm("ubi_device");
	if (IS_ERR(mtd)) { ret = PTR_ERR(mtd); mtd = NULL; goto out; }
	if (mtd->size != 0x0f5c0000 || mtd->erasesize != 0x20000) { ret = -EINVAL; goto out; }
	for (offset = 0; offset < mtd->size; offset += mtd->erasesize) {
		struct erase_info erase = { .mtd = mtd, .addr = offset, .len = mtd->erasesize };
		ret = mtd_block_isbad(mtd, offset);
		if (ret < 0) goto out;
		if (!ret && (ret = mtd_erase(mtd, &erase))) goto out;
		poll();
	}
	put_mtd_device(mtd);
	mtd = NULL;
	ret = ubi_part("ubi_device", NULL);
	if (ret) goto out;
	for (i = 0; i < ARRAY_SIZE(layout); i++) {
		ret = run_commandf("ubi create %s %x d %x", layout[i].name, layout[i].size, i);
		if (ret) goto out;
		poll();
	}
	for (i = 0; i < ARRAY_SIZE(keep); i++) {
		ret = ubi_volume_write((char *)keep[i].name, keep[i].data, 0, keep[i].size);
		if (!ret) ret = volume_verify((char *)keep[i].name, keep[i].data, keep[i].size, poll);
		if (ret) goto out;
	}
	puts("UBI rebuilt; factory, FPGA and board trees restored and read back. Install a system before booting.\n");
out:
	if (mtd) put_mtd_device(mtd);
	for (i = 0; i < ARRAY_SIZE(keep); i++) free(keep[i].data);
	return ret;
}
