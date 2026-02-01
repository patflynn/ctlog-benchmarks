#!/usr/bin/env python3
"""Validate costs.json prices against GCP Cloud Billing Catalog API.

Fetches current list prices from the GCP Cloud Billing Catalog API and
compares them against the hardcoded rates in costs.json, flagging any drift
that exceeds a configurable threshold.

Authentication (tried in order):
    1. --api-key flag or GOOGLE_API_KEY env var
    2. gcloud auth print-access-token
    3. gcloud auth application-default print-access-token

Exit codes:
    0 - All prices within threshold
    1 - Price drift detected
    2 - API or runtime error
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "https://cloudbilling.googleapis.com/v1"

# Stable GCP Cloud Billing Catalog service IDs
SERVICES = {
    "compute": "6F81-5844-456A",
    "cloud_sql": "9662-B51E-5089",
    "spanner": "C3BE-E88D-984E",
    "gke": "6F2A-2C47-BC52",
}

# E2 machine type specs (vCPUs, RAM in GB)
MACHINE_SPECS = {
    "e2-standard-2": {"vcpus": 2, "ram_gb": 8},
    "e2-standard-4": {"vcpus": 4, "ram_gb": 16},
    "e2-standard-8": {"vcpus": 8, "ram_gb": 32},
}

# Map GCP regions to the geographic label used in Compute Engine SKU descriptions
REGION_TO_GEO = {
    "us-central1": "Americas",
    "us-east1": "Americas",
    "us-east4": "Americas",
    "us-west1": "Americas",
    "us-west2": "Americas",
    "europe-west1": "EMEA",
    "europe-west2": "EMEA",
    "asia-east1": "Asia Pacific",
    "asia-southeast1": "Asia Pacific",
}

HOURS_PER_MONTH = 730


def get_auth(api_key=None):
    """Resolve API authentication.

    Tries in order:
        1. Explicit api_key argument
        2. GOOGLE_API_KEY environment variable
        3. gcloud auth print-access-token
        4. gcloud auth application-default print-access-token

    Returns dict with either {"key": ...} or {"token": ...} or {}.
    """
    if api_key:
        return {"key": api_key}

    env_key = os.environ.get("GOOGLE_API_KEY")
    if env_key:
        return {"key": env_key}

    for cmd in (
        ["gcloud", "auth", "print-access-token"],
        ["gcloud", "auth", "application-default", "print-access-token"],
    ):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10)
            token = result.stdout.strip()
            if result.returncode == 0 and token:
                return {"token": token}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return {}


def fetch_skus(service_id, auth=None):
    """Fetch all SKUs for a GCP Billing Catalog service, handling pagination."""
    auth = auth or {}
    skus = []
    base_params = "pageSize=5000"
    if "key" in auth:
        base_params += f"&key={auth['key']}"
    url = f"{API_BASE}/services/{service_id}/skus?{base_params}"

    while url:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "ctlog-benchmarks/validate-costs")
            if "token" in auth:
                req.add_header("Authorization", f"Bearer {auth['token']}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"Error fetching SKUs for service {service_id}: {e}",
                  file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f"Error parsing response for service {service_id}: {e}",
                  file=sys.stderr)
            return None

        skus.extend(data.get("skus", []))
        token = data.get("nextPageToken")
        if token:
            url = (f"{API_BASE}/services/{service_id}/skus"
                   f"?{base_params}&pageToken={token}")
        else:
            url = None

    return skus


def extract_rate(sku):
    """Extract USD rate from a SKU's pricing info.

    Returns (rate_per_unit, usage_unit) or (None, None).
    """
    pricing = sku.get("pricingInfo", [])
    if not pricing:
        return None, None

    expr = pricing[0].get("pricingExpression", {})
    unit = expr.get("usageUnit", "")
    rates = expr.get("tieredRates", [])
    if not rates:
        return None, None

    price = rates[0].get("unitPrice", {})
    units = int(price.get("units", "0"))
    nanos = price.get("nanos", 0)
    rate = units + nanos / 1_000_000_000

    return rate, unit


def to_hourly(rate, unit):
    """Convert a rate to hourly."""
    if unit == "h":
        return rate
    if unit == "mo":
        return rate / HOURS_PER_MONTH
    return rate


def find_sku(skus, match_fn, verbose=False):
    """Find the first matching SKU."""
    matches = [s for s in skus if match_fn(s)]
    if verbose and matches:
        print(f"  Found {len(matches)} matching SKU(s):", file=sys.stderr)
        for m in matches[:5]:
            rate, unit = extract_rate(m)
            print(f"    - {m.get('description', 'N/A')} "
                  f"(rate={rate}, unit={unit})", file=sys.stderr)
    return matches[0] if matches else None


def build_checks(tier_data, region):
    """Build a list of price checks for a single tier.

    Each check is a dict with: component, expected, service, match, scale.
    The API rate is multiplied by 'scale' before comparison to 'expected'.
    """
    checks = []
    geo = REGION_TO_GEO.get(region, "Americas")
    machine_type = tier_data.get("gke_machine_type", "e2-standard-2")
    specs = MACHINE_SPECS.get(machine_type)
    if not specs:
        print(f"Warning: unknown machine type {machine_type}", file=sys.stderr)
        specs = {"vcpus": 2, "ram_gb": 8}

    vcpus = specs["vcpus"]
    ram_gb = specs["ram_gb"]
    shared = tier_data.get("shared", {})

    # GKE Cluster Management Fee
    mgmt = shared.get("gke_cluster_mgmt", {})
    if "hourly_rate" in mgmt:
        checks.append({
            "component": "GKE Cluster Management",
            "expected": mgmt["hourly_rate"],
            "service": "gke",
            "match": lambda s: (
                "cluster management fee" in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
            ),
            "scale": 1,
        })

    # E2 CPU per node
    nodes = shared.get("gke_nodes", {})
    pnh = nodes.get("per_node_hourly", {})
    if "cpu" in pnh:
        checks.append({
            "component": f"{machine_type} CPU/node",
            "expected": pnh["cpu"],
            "service": "compute",
            "match": lambda s, g=geo: (
                "e2 instance core" in s.get("description", "").lower()
                and g.lower() in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
                and s.get("category", {}).get("resourceFamily") == "Compute"
            ),
            "scale": vcpus,
        })

    # E2 RAM per node
    if "ram" in pnh:
        checks.append({
            "component": f"{machine_type} RAM/node",
            "expected": pnh["ram"],
            "service": "compute",
            "match": lambda s, g=geo: (
                "e2 instance ram" in s.get("description", "").lower()
                and g.lower() in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
                and s.get("category", {}).get("resourceFamily") == "Compute"
            ),
            "scale": ram_gb,
        })

    # Forwarding Rule
    lb = shared.get("load_balancers", {})
    if "per_rule_hourly" in lb:
        checks.append({
            "component": "Forwarding Rule",
            "expected": lb["per_rule_hourly"],
            "service": "compute",
            "match": lambda s, r=region, g=geo: (
                "forwarding rule" in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
                and s.get("category", {}).get("resourceFamily") == "Network"
                and "additional" not in s.get("description", "").lower()
                and (any(r in sr for sr in s.get("serviceRegions", []))
                     or g.lower() in s.get("description", "").lower())
            ),
            "scale": 1,
        })

    # Cloud SQL
    sql = tier_data.get("trillian", {}).get("cloud_sql", {})
    if "hourly_rate" in sql:
        sql_tier = sql.get("tier", "")
        if "micro" in sql_tier:
            kw = ["micro"]
        elif sql_tier == "db-n1-standard-1":
            kw = ["1 vCPU"]
        elif sql_tier == "db-n1-standard-2":
            kw = ["2 vCPU"]
        else:
            kw = [sql_tier]

        checks.append({
            "component": f"Cloud SQL {sql_tier}",
            "expected": sql["hourly_rate"],
            "service": "cloud_sql",
            "match": lambda s, keywords=kw, r=region: (
                all(k.lower() in s.get("description", "").lower()
                    for k in keywords)
                and "mysql" in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
                and any(r in sr for sr in s.get("serviceRegions", []))
            ),
            "scale": 1,
        })

    # Cloud Spanner Processing Units
    spanner = tier_data.get("tesseract", {}).get("spanner", {})
    if "hourly_rate" in spanner:
        pus = spanner.get("processing_units", 100)
        checks.append({
            "component": f"Spanner {pus} PU",
            "expected": spanner["hourly_rate"],
            "service": "spanner",
            "match": lambda s: (
                "processing" in s.get("description", "").lower()
                and "unit" in s.get("description", "").lower()
                and "regional" in s.get("description", "").lower()
                and s.get("category", {}).get("usageType") == "OnDemand"
            ),
            "scale": pus,
        })

    return checks


def validate_tier(tier_name, tier_data, skus_cache, threshold, region,
                  auth=None, verbose=False):
    """Run all price checks for a tier and return results."""
    checks = build_checks(tier_data, region)
    results = []

    for check in checks:
        service = check["service"]

        # Fetch and cache SKUs per service
        if service not in skus_cache:
            service_id = SERVICES.get(service)
            if not service_id:
                results.append({
                    "component": check["component"],
                    "expected": check["expected"],
                    "actual": None,
                    "drift_pct": None,
                    "status": "ERROR",
                    "detail": f"Unknown service: {service}",
                })
                continue

            if verbose:
                print(f"  Fetching SKUs for {service} ({service_id})...",
                      file=sys.stderr)
            skus = fetch_skus(service_id, auth=auth)
            if skus is None:
                skus_cache[service] = []
            else:
                skus_cache[service] = skus
                if verbose:
                    print(f"  Fetched {len(skus)} SKUs for {service}",
                          file=sys.stderr)

        skus = skus_cache[service]
        if not skus:
            results.append({
                "component": check["component"],
                "expected": check["expected"],
                "actual": None,
                "drift_pct": None,
                "status": "API_ERROR",
                "detail": "Failed to fetch SKUs",
            })
            continue

        if verbose:
            print(f"  Matching: {check['component']}", file=sys.stderr)
        sku = find_sku(skus, check["match"], verbose=verbose)

        if not sku:
            results.append({
                "component": check["component"],
                "expected": check["expected"],
                "actual": None,
                "drift_pct": None,
                "status": "NOT_FOUND",
                "detail": "No matching SKU found",
            })
            continue

        rate, unit = extract_rate(sku)
        if rate is None:
            results.append({
                "component": check["component"],
                "expected": check["expected"],
                "actual": None,
                "drift_pct": None,
                "status": "NO_PRICE",
                "detail": f"SKU has no pricing: {sku.get('description', '')}",
            })
            continue

        hourly = to_hourly(rate, unit)
        actual = round(hourly * check["scale"], 4)
        expected = check["expected"]

        if expected == 0:
            drift_pct = 0.0 if actual == 0 else 100.0
        else:
            drift_pct = abs(actual - expected) / expected * 100

        status = "OK" if drift_pct <= threshold else "DRIFT"
        results.append({
            "component": check["component"],
            "expected": expected,
            "actual": actual,
            "drift_pct": round(drift_pct, 2),
            "status": status,
            "detail": sku.get("description", ""),
        })

    return results


def print_table(tier_name, results, threshold):
    """Print results as a formatted table."""
    print(f"\nValidating tier: {tier_name} (threshold: {threshold}%)\n")

    hdr = (f"{'Component':<28} {'Expected':>10} {'Actual':>10} "
           f"{'Drift':>8} {'Status':>10}")
    print(hdr)
    print("-" * len(hdr))

    for r in results:
        expected = f"${r['expected']:.4f}" if r["expected"] is not None else "N/A"
        actual = f"${r['actual']:.4f}" if r["actual"] is not None else "N/A"
        drift = (f"{r['drift_pct']:.1f}%"
                 if r["drift_pct"] is not None else "N/A")
        print(f"{r['component']:<28} {expected:>10} {actual:>10} "
              f"{drift:>8} {r['status']:>10}")

    ok = sum(1 for r in results if r["status"] == "OK")
    drift = sum(1 for r in results if r["status"] == "DRIFT")
    errors = sum(1 for r in results
                 if r["status"] in ("NOT_FOUND", "API_ERROR", "NO_PRICE", "ERROR"))
    total = len(results)

    print()
    if drift > 0:
        print(f"Result: {drift}/{total} price(s) drifted beyond "
              f"{threshold}% threshold")
    elif errors > 0:
        print(f"Result: {ok}/{total} OK, {errors} could not be verified")
    else:
        print(f"Result: All prices match ({ok}/{total} OK)")


def main():
    parser = argparse.ArgumentParser(
        description="Validate costs.json against GCP Cloud Billing Catalog API")
    parser.add_argument(
        "--tier", help="Validate a specific tier (default: all)")
    parser.add_argument(
        "--threshold", type=float, default=5.0,
        help="Drift tolerance percentage (default: 5.0)")
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output results as JSON")
    parser.add_argument(
        "--region", default="us-central1",
        help="GCP region for price filtering (default: us-central1)")
    parser.add_argument(
        "--api-key",
        help="GCP API key (or set GOOGLE_API_KEY env var)")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print debug info about SKU matching")
    args = parser.parse_args()

    # Resolve authentication
    auth = get_auth(api_key=args.api_key)
    if not auth:
        print("Error: No authentication found. Provide --api-key, set "
              "GOOGLE_API_KEY, or authenticate with gcloud.", file=sys.stderr)
        sys.exit(2)
    if args.verbose:
        method = "API key" if "key" in auth else "OAuth token"
        print(f"  Auth: using {method}", file=sys.stderr)

    # Load costs.json
    costs_path = Path(__file__).resolve().parent.parent / "costs.json"
    try:
        with open(costs_path) as f:
            costs = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading {costs_path}: {e}", file=sys.stderr)
        sys.exit(2)

    tiers = costs.get("tiers", {})
    if args.tier:
        if args.tier not in tiers:
            print(f"Error: tier '{args.tier}' not found in costs.json. "
                  f"Available: {', '.join(tiers.keys())}", file=sys.stderr)
            sys.exit(2)
        tiers = {args.tier: tiers[args.tier]}

    skus_cache = {}
    all_results = {}
    has_drift = False
    has_error = False

    for tier_name, tier_data in tiers.items():
        results = validate_tier(
            tier_name, tier_data, skus_cache, args.threshold,
            args.region, auth=auth, verbose=args.verbose)
        all_results[tier_name] = results

        for r in results:
            if r["status"] == "DRIFT":
                has_drift = True
            elif r["status"] in ("API_ERROR", "ERROR"):
                has_error = True

    if args.json_output:
        output = {"tiers": {}}
        for tier_name, results in all_results.items():
            tier_status = "ok"
            if any(r["status"] == "DRIFT" for r in results):
                tier_status = "drift"
            elif any(r["status"] in ("API_ERROR", "ERROR") for r in results):
                tier_status = "error"
            output["tiers"][tier_name] = {
                "checks": results,
                "status": tier_status,
            }
        output["overall_status"] = (
            "drift" if has_drift else "error" if has_error else "ok")
        print(json.dumps(output, indent=2))
    else:
        for tier_name, results in all_results.items():
            print_table(tier_name, results, args.threshold)

    if has_drift:
        sys.exit(1)
    elif has_error:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
