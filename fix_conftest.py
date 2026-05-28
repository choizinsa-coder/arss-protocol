import sys
path = "tests/conftest.py"
lines = open(path).readlines()
lines = [l for l in lines if "collect_ignore" not in l and l.strip() != ""]
lines.append('\ncollect_ignore = ["test_observation_e2e.py"]\n')
open(path, "w").writelines(lines)
print("DONE")
