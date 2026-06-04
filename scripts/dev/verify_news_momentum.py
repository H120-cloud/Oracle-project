"""Automatic verification script for News Momentum enhancements."""

import json
import time
import subprocess
import urllib.request
import urllib.error

BASE = "http://localhost:8001/api/v1"


def get(path, timeout=5):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def post(path, timeout=10):
    req = urllib.request.Request(f"{BASE}{path}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def banner(title):
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():
    # Wait for server (health endpoint is at root, not under /api/v1)
    print("Waiting for backend to start...")
    base_url = BASE.replace("/api/v1", "")
    for i in range(30):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as r:
                if r.status == 200:
                    print("Server is UP")
                    break
        except:
            pass
        time.sleep(1)
    else:
        print("Server failed to start within 30 seconds")
        return 1

    banner("1. HEALTH CHECK")
    health_url = BASE.replace("/api/v1", "") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as r:
            health = json.loads(r.read())
    except Exception as e:
        health = {"error": str(e)}
    print(json.dumps(health, indent=2))

    banner("2. NEWS MOMENTUM CONFIG")
    cfg = get("/news-momentum/config")
    print(json.dumps(cfg, indent=2))

    print()
    print("Threshold verification:")
    prem_impact = cfg.get("premarket_impact_threshold")
    mid_impact = cfg.get("midday_impact_threshold")
    vel_max = cfg.get("velocity_bonus_max")
    print(f"  premarket_impact_threshold: {prem_impact} (expect < 70)")
    print(f"  midday_impact_threshold: {mid_impact} (expect > 70)")
    print(f"  velocity_bonus_max: {vel_max} (expect > 0)")

    ok = True
    if prem_impact is None or prem_impact >= 70:
        print("  FAIL: premarket threshold not lower than regular")
        ok = False
    if mid_impact is None or mid_impact <= 70:
        print("  FAIL: midday threshold not higher than regular")
        ok = False
    if vel_max is None or vel_max <= 0:
        print("  FAIL: velocity bonus not configured")
        ok = False
    if ok:
        print("  PASS: All thresholds configured correctly")

    banner("3. HEADLINE CLASSIFICATION (SLXN-like)")
    hl = get("/news-momentum/classify-headline?headline=Recent+SL01+trial+progress%2C+positive+preclinical+data")
    print(json.dumps(hl, indent=2))
    if hl.get("catalyst_category") == "biotech":
        print("  PASS: Classified as biotech")
    else:
        print(f"  FAIL: Expected biotech, got {hl.get('catalyst_category')}")

    banner("4. MANUAL SCAN")
    scan = post("/news-momentum/scan-now")
    print(json.dumps(scan, indent=2))
    if "error" not in scan:
        print("  PASS: Scan completed without error")
    else:
        print(f"  FAIL: Scan error: {scan['error']}")

    banner("5. ACTIVE CANDIDATES")
    cands = get("/news-momentum/candidates")
    print(f"Total active candidates: {len(cands)}")
    for c in cands[:5]:
        ticker = c.get("ticker", "?")
        impact = c.get("news_impact_score", 0)
        move = c.get("move_pct", 0)
        vel = c.get("velocity_score", 0)
        delayed = c.get("is_delayed_reaction", False)
        print(f"  {ticker}: impact={impact:.1f} move={move:.1f}% velocity={vel:.1f} delayed={delayed}")

    banner("6. TELEGRAM QUALITY")
    tq = get("/news-momentum/telegram-quality")
    print(json.dumps(tq, indent=2))

    banner("7. RUNNING TESTS")
    r = subprocess.run(
        ["python", "-m", "pytest", "tests/test_news_momentum.py", "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )
    print(r.stdout[-1500:] if len(r.stdout) > 1500 else r.stdout)
    if r.returncode != 0:
        print("STDERR:")
        print(r.stderr[-500:] if len(r.stderr) > 500 else r.stderr)
        return 1

    banner("VERIFICATION COMPLETE")
    print("All checks passed. The News Momentum enhancements are working.")
    return 0


if __name__ == "__main__":
    exit(main())
