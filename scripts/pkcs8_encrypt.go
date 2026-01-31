// pkcs8_encrypt.go produces legacy-encrypted PEM (Proc-Type/DEK-Info headers)
// wrapping PKCS#8 DER content. This specific combination is required by ct_hammer
// but cannot be produced by a single OpenSSL 3.x command:
//   - "openssl rsa -des3" produces PKCS#8 encrypted PEM (no DEK-Info header)
//   - "openssl rsa -des3 -traditional" produces legacy PEM but with PKCS#1 DER
//   - ct_hammer calls x509.DecryptPEMBlock (needs DEK-Info) then
//     x509.ParsePKCS8PrivateKey (needs PKCS#8 DER)
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

	// OpenSSL 3.x genrsa outputs PKCS#8 ("PRIVATE KEY"); older versions output PKCS#1
	// ("RSA PRIVATE KEY"). Handle both.
	var pkcs8DER []byte
	if key, err := x509.ParsePKCS8PrivateKey(block.Bytes); err == nil {
		// Already PKCS#8 — re-marshal to get clean DER
		pkcs8DER, err = x509.MarshalPKCS8PrivateKey(key)
		if err != nil {
			fmt.Fprintf(os.Stderr, "marshal PKCS#8: %v\n", err)
			os.Exit(1)
		}
	} else if rsaKey, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		// PKCS#1 — convert to PKCS#8
		pkcs8DER, err = x509.MarshalPKCS8PrivateKey(rsaKey)
		if err != nil {
			fmt.Fprintf(os.Stderr, "marshal PKCS#8: %v\n", err)
			os.Exit(1)
		}
	} else {
		fmt.Fprintf(os.Stderr, "failed to parse key as PKCS#8 or PKCS#1\n")
		os.Exit(1)
	}

	//nolint:staticcheck // x509.EncryptPEMBlock is deprecated but required for legacy PEM format
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
