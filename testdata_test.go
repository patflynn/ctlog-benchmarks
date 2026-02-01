package ctlogbenchmarks_test

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// decryptECKey mimics the MakeSigner() flow from ct-go's integration tests:
// PEM decode, decrypt the PEM block with the given password, parse as EC key.
func decryptECKey(t *testing.T, path, password string) *ecdsa.PrivateKey {
	t.Helper()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile(%q): %v", path, err)
	}

	block, _ := pem.Decode(data)
	if block == nil {
		t.Fatalf("no PEM block found in %s", path)
	}

	//nolint:staticcheck // x509.DecryptPEMBlock is deprecated but matches upstream usage
	der, err := x509.DecryptPEMBlock(block, []byte(password))
	if err != nil {
		t.Fatalf("DecryptPEMBlock(%s): %v", path, err)
	}

	key, err := x509.ParseECPrivateKey(der)
	if err != nil {
		t.Fatalf("ParseECPrivateKey(%s): %v", path, err)
	}

	return key
}

// parseCert parses a PEM-encoded X.509 certificate from a file.
func parseCert(t *testing.T, path string) *x509.Certificate {
	t.Helper()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile(%q): %v", path, err)
	}

	block, _ := pem.Decode(data)
	if block == nil {
		t.Fatalf("no PEM block found in %s", path)
	}

	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatalf("ParseCertificate(%s): %v", path, err)
	}

	return cert
}

// testingKey mimics tesseract's testingKey() helper that remaps
// "TEST PRIVATE KEY" PEM headers to the real type for testing keys.
func testingKey(pemData string) string {
	return strings.ReplaceAll(pemData, "TEST PRIVATE KEY", "PRIVATE KEY")
}

func TestTrillianIntCAKey(t *testing.T) {
	key := decryptECKey(t, "testdata/trillian/int-ca.privkey.pem", "babelfish")
	if key.Curve != elliptic.P256() {
		t.Fatalf("expected P-256 curve, got %v", key.Curve.Params().Name)
	}
}

func TestTrillianCTFEKey(t *testing.T) {
	key := decryptECKey(t, "testdata/trillian/ct-http-server.privkey.pem", "dirk")
	if key.Curve != elliptic.P256() {
		t.Fatalf("expected P-256 curve, got %v", key.Curve.Params().Name)
	}
}

func TestTrillianRootCA(t *testing.T) {
	cert := parseCert(t, "testdata/trillian/fake-ca.cert")
	if !cert.IsCA {
		t.Fatal("expected CA certificate")
	}
}

func TestTrillianIntCACert(t *testing.T) {
	cert := parseCert(t, "testdata/trillian/int-ca.cert")
	if !cert.IsCA {
		t.Fatal("expected CA certificate")
	}
}

func TestTrillianLeafChains(t *testing.T) {
	chains, err := filepath.Glob("testdata/trillian/leaf*.chain")
	if err != nil {
		t.Fatalf("Glob: %v", err)
	}
	if len(chains) == 0 {
		t.Fatal("no leaf chain files found")
	}

	for _, chainFile := range chains {
		t.Run(filepath.Base(chainFile), func(t *testing.T) {
			data, err := os.ReadFile(chainFile)
			if err != nil {
				t.Fatalf("ReadFile(%q): %v", chainFile, err)
			}

			var count int
			rest := data
			for {
				var block *pem.Block
				block, rest = pem.Decode(rest)
				if block == nil {
					break
				}
				if _, err := x509.ParseCertificate(block.Bytes); err != nil {
					t.Fatalf("ParseCertificate (cert %d in %s): %v", count, chainFile, err)
				}
				count++
			}

			if count < 2 {
				t.Fatalf("expected at least 2 certificates in chain, got %d", count)
			}
		})
	}
}

func TestTesseractIntCAKey(t *testing.T) {
	data, err := os.ReadFile("testdata/tesseract/test_intermediate_ca_private_key.pem")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}

	block, _ := pem.Decode([]byte(testingKey(string(data))))
	if block == nil {
		t.Fatal("no PEM block found")
	}

	key, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		t.Fatalf("ParsePKCS1PrivateKey: %v", err)
	}

	if key.N.BitLen() == 0 {
		t.Fatal("expected non-zero RSA modulus")
	}
}

func TestTesseractLeafSigningKey(t *testing.T) {
	data, err := os.ReadFile("testdata/tesseract/test_leaf_cert_signing_private_key.pem")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}

	block, _ := pem.Decode([]byte(testingKey(string(data))))
	if block == nil {
		t.Fatal("no PEM block found")
	}

	key, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		t.Fatalf("ParsePKCS1PrivateKey: %v", err)
	}

	if key.N.BitLen() == 0 {
		t.Fatal("expected non-zero RSA modulus")
	}
}

func TestTesseractCerts(t *testing.T) {
	for _, file := range []string{
		"testdata/tesseract/test_root_ca_cert.pem",
		"testdata/tesseract/test_intermediate_ca_cert.pem",
	} {
		t.Run(filepath.Base(file), func(t *testing.T) {
			cert := parseCert(t, file)
			if !cert.IsCA {
				t.Fatal("expected CA certificate")
			}
		})
	}
}
