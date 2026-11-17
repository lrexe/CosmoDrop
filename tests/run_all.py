"""Run every end-to-end suite in a subprocess and print one summary line each."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["vtest", "tontest", "relaytest", "admintest", "maintest"]


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    ok = True
    for name in SUITES:
        proc = subprocess.run([sys.executable, os.path.join(HERE, name + ".py")],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env)
        lines = proc.stdout.splitlines()
        passed = sum(1 for l in lines if l.startswith("PASS"))
        good = proc.returncode == 0 and any(l.strip() == "ALL PASS" for l in lines)
        if good:
            print(f"{name}: ALL PASS ({passed})")
        else:
            ok = False
            print(f"{name}: FAILED ({passed} passed, exit {proc.returncode})")
            for l in lines:
                if l.startswith("FAIL"):
                    print("  " + l)
            if proc.stderr.strip():
                print("  " + proc.stderr.strip().splitlines()[-1])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
