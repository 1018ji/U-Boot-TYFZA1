// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <image.h>
#include <u-boot/rsa.h>
#include <u-boot/hash-checksum.h>
#include <u-boot/sha256.h>
#include "certificates.h"

static void firmware_sha256(const void *data, size_t size, unsigned char hash[32])
{
	sha256_csum_wd(data, size, hash, CHUNKSZ_SHA256);
}

static int strict_pss(struct image_sign_info *info, const uint8_t *message,
		      int length, const uint8_t *hash, int hash_size)
{
	unsigned char input[36], mask[32];
	unsigned int i, counter, position = 190;
	int ret = padding_pss_verify(info, message, length, hash, hash_size);
	if (ret || length != 256 || hash_size != 32) return ret ? ret : -EINVAL;
	/* The certificate profile specifies a 32-byte salt, not an arbitrary salt. */
	memcpy(input, message + 223, 32);
	for (counter = 0; counter <= position / 32; counter++) {
		input[32] = input[33] = input[34] = 0;
		input[35] = counter;
		firmware_sha256(input, sizeof(input), mask);
		for (i = counter * 32; i <= position && i < (counter+1)*32; i++) {
			unsigned char value = message[i] ^ mask[i % 32];
			if (!i) value &= 0x7f;
			if (value != (i == position ? 1 : 0)) return -EINVAL;
		}
	}
	return 0;
}

static int firmware_verify_pss(const void *key, size_t key_size,
			       const unsigned char hash[32], const void *signature, size_t size)
{
	struct checksum_algo checksum = { .name = "sha256", .checksum_len = 32, .calculate = hash_calculate };
	struct crypto_algo crypto = { .name = "rsa2048", .key_len = 256 };
	struct padding_algo padding = { .name = "pss", .verify = strict_pss };
	struct image_sign_info info = {
		.key = key, .keylen = key_size, .checksum = &checksum, .crypto = &crypto, .padding = &padding
	};
	if (size != 256) return -EINVAL;
	return rsa_verify_with_pkey(&info, hash, (void *)signature, size);
}

int tyfza1_loader_certificates(const void *loader, size_t size)
{
	const struct tyf_crypto crypto = { firmware_sha256, firmware_verify_pss };
	return tyf_verify_certificates(loader, size, &crypto);
}
