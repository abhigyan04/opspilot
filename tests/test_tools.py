from app.tools.deployments import get_deployments
from app.tools.git import get_commit
from app.tools.logs import search_logs
from app.tools.metrics import query_metrics

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
