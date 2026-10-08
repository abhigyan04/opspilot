from dataclasses import dataclass
from pathlib import Path

from app.tools.data import SCENARIOS_ROOT


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    incident: str
    required_tools: frozenset[str]
    reference_root_cause: str
    scenario_dir: Path


CHECKOUT_REGRESSION = EvaluationCase(
    case_id="checkout_regression",
    incident="Errors in checkout-service have increased significantly. Investigate.",
    required_tools=frozenset({
        "query_metrics",
        "search_logs",
        "get_deployments",
        "get_commit",
    }),
    reference_root_cause=(
        "The deployed change accesses request.user.customer_id. "
        "When request.user is None, this access raises AttributeError. "
        "The change does not itself make request.user become None."
    ),
    scenario_dir=SCENARIOS_ROOT / "checkout_regression"
)


PAYMENT_PROVIDER_OUTAGE = EvaluationCase(
    case_id="payment_provider_outage",
    incident="Errors in checkout-service have increased significantly. Investigate.",
    required_tools=frozenset({
        "query_metrics",
        "search_logs",
        "get_deployments",
        "get_commit",
    }),
    reference_root_cause=(
        "Checkout payment authorization fails because PayBridge returns HTTP 503. "
        "Failures and elevated error rates began before the checkout deployment "
        "and affect both versions 1.7.3 and 1.7.4. "
        "The deployment changes logging only and does not explain the onset. "
        "Rolling back checkout is not supported as a remedy by this evidence. "
        "The provider's internal reason for returning 503 remains unknown."
    ),
    scenario_dir=SCENARIOS_ROOT / "payment_provider_outage",
)


CASES = {
    CHECKOUT_REGRESSION.case_id: CHECKOUT_REGRESSION,
    PAYMENT_PROVIDER_OUTAGE.case_id: PAYMENT_PROVIDER_OUTAGE,
}
