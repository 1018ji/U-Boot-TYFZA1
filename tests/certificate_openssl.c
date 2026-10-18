/* SPDX-License-Identifier: GPL-2.0-only */
/* The production DER/chain parser uses OpenSSL only as the host RSA/SHA engine. */
#include <openssl/evp.h>
#include <openssl/rsa.h>
#include <openssl/sha.h>
#include <openssl/x509.h>
#include <openssl/decoder.h>
#include <openssl/core_dispatch.h>
#include "certificates.h"

static void host_sha256(const void *data, size_t size, unsigned char hash[32])
{
	SHA256(data, size, hash);
}

static int host_verify_pss(const void *key, size_t key_size,
			   const unsigned char hash[32], const void *signature, size_t signature_size)
{
	const unsigned char *p = key;
	EVP_PKEY *public = NULL;
	OSSL_DECODER_CTX *decoder;
	EVP_PKEY_CTX *context = NULL;
	size_t remaining = key_size;
	int ret = -1;
	decoder = OSSL_DECODER_CTX_new_for_pkey(&public, "DER", "type-specific", "RSA",
					      OSSL_KEYMGMT_SELECT_PUBLIC_KEY, NULL, NULL);
	if (!decoder || OSSL_DECODER_from_data(decoder, &p, &remaining) <= 0) {
		OSSL_DECODER_CTX_free(decoder); goto out;
	}
	OSSL_DECODER_CTX_free(decoder);
	if (!public || remaining ||
	    EVP_PKEY_get_bits(public) != 2048 || signature_size != 256) goto out;
	context = EVP_PKEY_CTX_new(public, NULL);
	if (!context || EVP_PKEY_verify_init(context) <= 0 ||
	    EVP_PKEY_CTX_set_rsa_padding(context, RSA_PKCS1_PSS_PADDING) <= 0 ||
	    EVP_PKEY_CTX_set_signature_md(context, EVP_sha256()) <= 0 ||
	    EVP_PKEY_CTX_set_rsa_mgf1_md(context, EVP_sha256()) <= 0 ||
	    EVP_PKEY_CTX_set_rsa_pss_saltlen(context, 32) <= 0) goto out;
	ret = EVP_PKEY_verify(context, signature, signature_size, hash, 32) == 1 ? 0 : -1;
out:
	EVP_PKEY_CTX_free(context);
	EVP_PKEY_free(public);
	return ret;
}

int tyfza1_loader_certificates(const void *data, size_t size)
{
	const struct tyf_crypto crypto = { host_sha256, host_verify_pss };
	return tyf_verify_certificates(data, size, &crypto);
}
