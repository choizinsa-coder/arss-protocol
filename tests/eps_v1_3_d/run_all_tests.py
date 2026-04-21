"""Run all T1-T10 adversarial tests and report results."""
import sys, os, importlib, traceback
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
sys.path.insert(0, os.path.dirname(__file__))

TESTS = ["T1_replay_attack", "T2_baseline_missing", "T3_baseline_ambiguous",
         "T4_delta_zero", "T5_delta_insufficient", "T6_verifier_crash",
         "T7_binding_mismatch", "T8_quarantine_bypass", "T9_approval_without_pass",
         "T10_incomplete_close"]

results = {}
for t in TESTS:
    try:
        mod = importlib.import_module(t)
        mod.run()
        results[t] = "PASS"
    except SystemExit:
        results[t] = "FAIL"
    except Exception as e:
        print("  ERROR:", traceback.format_exc())
        results[t] = "FAIL: " + str(e)

print("\n=== TEST SUITE SUMMARY ===")
passed = 0
for t, r in results.items():
    status = "PASS" if r == "PASS" else "FAIL"
    if status == "PASS":
        passed += 1
    print(f"  {t}: {r}")
print(f"\n{passed}/{len(TESTS)} PASSED")
if passed == len(TESTS):
    print("SUITE RESULT: PASS")
else:
    print("SUITE RESULT: FAIL")
    sys.exit(1)
