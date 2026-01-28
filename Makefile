.PHONY: all clean containers

# Default base image for ko (distroless static)
export KO_DEFAULTBASEIMAGE := gcr.io/distroless/static:nonroot
# Target container registry (override with KO_DOCKER_REPO=gcr.io/my-project/my-repo make containers)
KO_DOCKER_REPO ?= ko.local

all: bin/ct_hammer bin/hammer

bin/ct_hammer:
	GOBIN=$(PWD)/bin go install github.com/google/certificate-transparency-go/trillian/integration/ct_hammer@latest

bin/hammer:
	GOBIN=$(PWD)/bin go install github.com/transparency-dev/tesseract/internal/hammer@latest

containers:
	ko build github.com/google/certificate-transparency-go/trillian/integration/ct_hammer
	ko build github.com/transparency-dev/tesseract/internal/hammer

clean:
	rm -rf bin/