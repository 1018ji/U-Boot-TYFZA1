/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_CERTIFICATES_H
#define TYFZA1_CERTIFICATES_H
#include "formats.h"
struct tyf_crypto {
	void (*sha256)(const void *data, size_t size, unsigned char hash[32]);
	int (*verify_pss)(const void *key, size_t key_size, const unsigned char hash[32],
			  const void *signature, size_t signature_size);
};
int tyf_verify_certificates(const void *loader, size_t size, const struct tyf_crypto *crypto);
#endif
