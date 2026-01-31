// pkcs8_encrypt converts an unencrypted RSA private key (PKCS#1 PEM) to a
// legacy-PEM-encrypted PKCS#8 key that ct_hammer can parse.
//
// ct_hammer expects: Proc-Type/DEK-Info PEM encryption + PKCS#8 DER content.
// OpenSSL 3.x cannot produce this combination:
//   - "openssl rsa -des3 -traditional" → PKCS#1 DER (Go's ParsePKCS8 rejects)
//   - "openssl pkcs8 -topk8 -v1 ..."  → PKCS#8 encrypted PEM (no DEK-Info, Go's DecryptPEMBlock can't read)
//
// Usage: go run scripts/pkcs8_encrypt.go <input.pem> <output.pem> <password>
package main

import (
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintf(os.Stderr, "usage: %s <input.pem> <output.pem> <password>\n", os.Args[0])
		os.Exit(1)
	}

	inPath, outPath, password := os.Args[1], os.Args[2], os.Args[3]

	// Read unencrypted PKCS#1 PEM
	pemData, err := os.ReadFile(inPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read %s: %v\n", inPath, err)
		os.Exit(1)
	}
	block, _ := pem.Decode(pemData)
	if block == nil {
		fmt.Fprintf(os.Stderr, "no PEM block in %s\n", inPath)
		os.Exit(1)
	}

	// Parse as PKCS#1 RSA key
	rsaKey, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse PKCS#1: %v\n", err)
		os.Exit(1)
	}

	// Re-marshal as PKCS#8
	pkcs8DER, err := x509.MarshalPKCS8PrivateKey(rsaKey)
	if err != nil {
		fmt.Fprintf(os.Stderr, "marshal PKCS#8: %v\n", err)
		os.Exit(1)
	}

	// Encrypt with legacy PEM encryption (Proc-Type/DEK-Info with 3DES)
	//nolint:staticcheck // x509.EncryptPEMBlock is deprecated but is the only
	// way to produce legacy-encrypted PEM that Go's x509.DecryptPEMBlock reads.
	encBlock, err := x509.EncryptPEMBlock(rand.Reader, "PRIVATE KEY", pkcs8DER,
		[]byte(password), x509.PEMCipher3DES)
	if err != nil {
		fmt.Fprintf(os.Stderr, "encrypt: %v\n", err)
		os.Exit(1)
	}

	out, err := os.Create(outPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "create %s: %v\n", outPath, err)
		os.Exit(1)
	}
	defer out.Close()

	if err := pem.Encode(out, encBlock); err != nil {
		fmt.Fprintf(os.Stderr, "encode PEM: %v\n", err)
		os.Exit(1)
	}
}
