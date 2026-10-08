from datetime import datetime

from app.tools.deployments import get_deployments
from app.tools.git import get_commit
from app.tools.logs import search_logs
from app.tools.metrics import query_metrics
from app.tools.data import SCENARIOS_ROOT

def test_checkout_incident_is_diagnosable():
    deployments = get_deployments("checkout-service")
    
    assert deployments[0]["version"] == "1.7.4", "Expected version 1.7.4 for checkout-service"
    
    commit = get_commit(deployments[0]["commit_hash"])
    
    assert commit is not None, f"No commit found for hash {deployments[0]['commit_hash']}"
    assert "request.user.customer_id" in commit["diff"], "Expected customer_id refactor not found in commit diff"

    logs = search_logs("checkout-service", "ERROR")
    
    assert any(
        "customer_id" in log["message"]
        for log in logs
    )
    
    metrics =  query_metrics("checkout-service", "error_rate")
    
    assert metrics[-1]["value"] > 0.3, "Expected error rate to be greater than 0 for checkout-service"


def test_provider_failure_predates_checkout_deployment():
    directory = SCENARIOS_ROOT / "payment_provider_outage"
    deployment = get_deployments(
        "checkout-service", data_dir=directory
    )[0]
    logs = search_logs(
        "checkout-service", "ERROR", data_dir=directory
    )
    metrics = query_metrics(
        "checkout-service", "error_rate", data_dir=directory
    )
    commit = get_commit(
        deployment["commit_hash"], data_dir=directory
    )

    def timestamp(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    deployed_at = timestamp(deployment["timestamp"])

    assert any(
        timestamp(log["timestamp"]) < deployed_at
        and log["version"] == deployment["rollback_target_version"]
        and "HTTP 503" in log["message"]
        for log in logs
    )
    assert any(
        timestamp(log["timestamp"]) > deployed_at
        and log["version"] == deployment["version"]
        and "HTTP 503" in log["message"]
        for log in logs
    )
    assert any(
        timestamp(metric["timestamp"]) < deployed_at
        and metric["value"] >= 0.3
        for metric in metrics
    )
    assert commit is not None
    assert 'logger.info' in commit["diff"]
    assert "customer_id" not in commit["diff"]
