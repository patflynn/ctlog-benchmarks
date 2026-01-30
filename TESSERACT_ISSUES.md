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

## 7. Hammer Tool Certificate Constraints (Compatibility)
*   **Issue:** The `hammer` tool requires intermediate certificates to have `CA:TRUE` and `keyCertSign` usage, even if they are only used for leaf generation during testing.
*   **Impact:** Certificates generated without these explicit extensions (which many simple `openssl` commands omit by default) will cause the hammer to fail with cryptic "invalid signature" or "parent cannot sign" errors.

## 8. Log Origin URL Prefixing (Friction)
*   **Issue:** While the server allows configuring an `--origin`, the routing behavior is inconsistent. If `--origin` is set, the server expects it to be the first part of the path, but standard LBs or internal routing might strip this, leading to 404s.
*   **Observation:** Setting `write_log_url` to include the origin in the hammer tool is sometimes necessary to satisfy server-side origin checks, but this depends heavily on the ingress/GCLB configuration.

## 9. Signer Key Stickiness (State Consistency)
*   **Issue:** TesseraCT stores its log state (checkpoints/tiles) in a durable backend like GCS. If the signer keys are re-generated during deployment (e.g., in CI/CD) while the GCS state is preserved, the server will fail to verify signatures on old checkpoints.
*   **Impact:** New server instances cannot resume operations from existing state if keys change.
*   **Workaround:** Deployment scripts must check for existing keys in Secret Manager before generating fresh ones to ensure log identity stability.
