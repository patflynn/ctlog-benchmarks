# TesseraCT Ergonomic & Bug Log

This document tracks issues, bugs, and friction points encountered during the deployment and benchmarking of TesseraCT on GCP.

## 1. Secret Manager Alias Restriction (Bug)
*   **Issue:** Using the `versions/latest` alias for signer keys results in a `request corrupted in-transit` error.
*   **Root Cause:** In `cmd/tesseract/gcp/secret_manager.go`, the code strictly compares the requested resource name with the returned resource name:
    ```go
    if resp.Name != secretName {
        return nil, errors.New("request corrupted in-transit")
    }
    ```
    When requesting `latest`, GCP returns the canonical version name (e.g., `projects/.../versions/5`). Since these strings don't match, the client aborts with a misleading "corruption" error.
*   **Workaround:** Deployment scripts must manually resolve `latest` to a numeric ID before passing it to the binary.

## 2. Fixed Signer Types in Variant Binaries (Ergonomics)
*   **Issue:** The `cmd/tesseract/gcp` binary *only* supports Secret Manager flags. It does not include the flags for local file-based keys (available in `posix`).
*   **Impact:** Difficult to debug locally or use in air-gapped/transient environments where creating GCP Secret Manager resources is overkill.
*   **Suggestion:** Base flags (like file paths) should be available in all variants, with specialized backends (GCP, AWS) added as options.

## 3. Misleading Error Messages (Ergonomics)
*   **Issue:** The "request corrupted in-transit" error for name mismatches is highly misleading. It suggests a network or encoding problem rather than a logic/naming issue.

## 4. Spanner DDL Idempotency (Ergonomics)
*   **Issue:** The provided `schema.sql` for Spanner does not use `IF NOT EXISTS` logic (which is limited in Spanner DDL).
*   **Impact:** Automating deployment requires wrapping the DDL update in a "try/catch" or ignoring errors, as re-running the script on an existing database fails.

## 6. Mandatory Roots File (Ergonomics)
*   **Issue:** The server crashes immediately if `--roots_pem_file` is not provided or is empty.
*   **Impact:** Prevents "zero-config" testing. Unlike some other logs that might start with an empty set, TesseraCT requires at least one root to be explicitly configured at startup.
*   **Error Message:** `Can't initialize CT HTTP Server: newCertValidationOpts(): empty rootsPemFile`
