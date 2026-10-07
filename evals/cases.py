from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    incident: str
    required_tools: frozenset[str]
    reference_root_cause: str


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
)
