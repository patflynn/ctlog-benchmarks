.PHONY: all clean

all: bin/ct_hammer bin/hammer

bin/ct_hammer:
	GOBIN=$(PWD)/bin go install github.com/google/certificate-transparency-go/trillian/integration/ct_hammer@latest

bin/hammer:
	GOBIN=$(PWD)/bin go install github.com/transparency-dev/tesseract/internal/hammer@latest

clean:
	rm -rf bin/