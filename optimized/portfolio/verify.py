"""Verify saved outputs, model compatibility, filters and the demo without retraining."""
import argparse
import importlib.metadata
import platform
from pathlib import Path
import sys
import unittest

from optimized.portfolio.service import BENCHMARK, ORIGINAL, FOLLOWUP, ROOT, required_files
from optimized.cold_start_benchmark.experiment import json, save_json


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",type=Path,default=ROOT/"optimized/portfolio/artifacts/verification.json")
    args=parser.parse_args()
    missing=[str(path) for path in required_files() if not path.is_file()]
    if missing:
        print("Missing artifacts:\n"+"\n".join(missing))
        return 1
    names=["optimized.cold_start_benchmark.test_experiment",
           "optimized.cold_start_improvements.test_improvements","optimized.portfolio.test_demo"]
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    versions={name:importlib.metadata.version(name) for name in
              ["streamlit","numpy","pandas","scipy","scikit-learn","joblib","setuptools"]}
    report={"success":result.wasSuccessful(),"tests_run":result.testsRun,
            "failures":len(result.failures),"errors":len(result.errors),
            "skipped":len(result.skipped),"python":platform.python_version(),"versions":versions,
            "checks":"data splitting and labels; ranking metrics; model roundtrip; frozen baseline; saved original/new recommendations; Streamlit form and empty state",
            "not_performed":"No fresh full-data retraining in this verification run. Existing saved training/evaluation outputs are reused.",
            "runs":{"benchmark":BENCHMARK.name,"original":ORIGINAL.name,"followup":FOLLOWUP.name}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    save_json(args.report,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":
    raise SystemExit(main())
