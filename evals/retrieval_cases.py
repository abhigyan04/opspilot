from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_sections: frozenset[tuple[str, str]]


RETRIEVAL_CASES = (
    RetrievalCase(
        case_id="dependency_investigation",
        query=(
            "An upstream payment service returns 503 responses. "
            "What observations should I compare before blaming our deployment?"
        ),
        relevant_sections=frozenset({
            ("runbook-dependency-errors", "Investigation"),
        }),
    ),
    RetrievalCase(
        case_id="dependency_investigation_paraphrase",
        query=(
            "Failures calling another service span a release. "
            "How can I distinguish a caller regression from a dependency problem?"
        ),
        relevant_sections=frozenset({
            ("runbook-dependency-errors", "Investigation"),
        }),
    ),
    RetrievalCase(
        case_id="exception_investigation",
        query=(
            "A request fails with an AttributeError involving None. "
            "What evidence would support a code regression?"
        ),
        relevant_sections=frozenset({
            ("runbook-application-exceptions", "Investigation"),
        }),
    ),
    RetrievalCase(
        case_id="exception_investigation_paraphrase",
        query=(
            "Code dereferences an absent object. "
            "How do I investigate without guessing which users are affected?"
        ),
        relevant_sections=frozenset({
            ("runbook-application-exceptions", "Investigation"),
        }),
    ),
    RetrievalCase(
        case_id="inventory_history",
        query=(
            "What observations and response were recorded in the earlier "
            "inventory reservation timeout incident?"
        ),
        relevant_sections=frozenset({
            ("incident-inventory-timeout", "Historical observations"),
            ("incident-inventory-timeout", "Historical response and outcome"),
        }),
    ),
    RetrievalCase(
        case_id="dependency_retry_risk",
        query=(
            "Should I increase retries when a dependency is failing? "
            "What operational risks should I check?"
        ),
        relevant_sections=frozenset({
            ("runbook-dependency-errors", "Response considerations"),
        }),
    ),
    RetrievalCase(
        case_id="unrelated_cooking",
        query="What ingredients and oven temperature do I need for chocolate cake?",
        relevant_sections=frozenset(),
    ),
    RetrievalCase(
        case_id="unsupported_operational_detail",
        query=(
            "What is the exact production database password "
            "and hostname for the inventory service?"
        ),
        relevant_sections=frozenset(),
    ),
)
