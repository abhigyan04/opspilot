import json
import hashlib

from evals import safety_runner


def test_safety_cli_saves_report(tmp_path, capsys):
    exit_code = safety_runner.main([
        "--output-dir", str(tmp_path),
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "passed"
    assert output["total_checks"] == 10
    assert output["passed_checks"] == 10

    reports = list(tmp_path.glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))

    assert report["run_id"] == output["run_id"]
    assert report["evaluation_mode"] == "simulation_controls"
    assert report["fixture_sha256"] == {
        "checkout_recovery": hashlib.sha256(
            safety_runner.recovery.DATA_PATH.read_bytes()
        ).hexdigest()
    }
    assert set(report["sections"]) == {
        "approval", "execution_guards", "recovery", "review_workflow"
    }
    assert set(report["code_sha256"]) == {
        "remediation", "verification", "schemas", "evaluator", "runner", "recovery_loader"
    }
    assert all(
        len(digest) == 64
        for digest in report["code_sha256"].values()
    )


def test_safety_cli_saves_failures_and_returns_nonzero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        safety_runner.safety,
        "verify_recovery",
        lambda window: {"status": "recovered"},
    )

    exit_code = safety_runner.main([
        "--output-dir", str(tmp_path),
    ])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["passed_checks"] == 8

    report_path = next(tmp_path.glob("*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failed_checks = {
        check["check_id"]
        for check in report["sections"]["recovery"]["checks"]
        if not check["passed"]
    }
    assert failed_checks == {
        "unhealthy_sample", "insufficient_samples",
    }
