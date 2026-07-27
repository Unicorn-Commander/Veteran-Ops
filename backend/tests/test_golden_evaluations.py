from evals.golden import REQUIRED_DOMAINS, run_golden


def test_deidentified_golden_release_gate():
    report = run_golden()

    assert report["ok"], report["results"]
    assert report["passed"] == report["total"]
    assert {result["domain"] for result in report["results"]} == REQUIRED_DOMAINS
