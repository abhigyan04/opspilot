import pytest
from pydantic import ValidationError

from app.api.schemas import StartWorkflowRequest, ReviewWorkflowRequest


def test_start_request_defaults_and_preserves_incident():
    incident = "  Checkout errors increased.\nInvestigate dependencies.  "

    request = StartWorkflowRequest(incident=incident)

    assert request.model_dump() == {
        "incident": incident,
        "scenario": "checkout_regression",
        "tool_backend": "direct",
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "checkout_regression",
        "payment_provider_outage",
        "sparse_evidence",
    ],
)
@pytest.mark.parametrize("backend", ["direct", "mcp"])
def test_start_request_accepts_supported_choices(scenario, backend):
    request = StartWorkflowRequest(
        incident="Investigate checkout-service.",
        scenario=scenario,
        tool_backend=backend,
    )

    assert request.scenario == scenario
    assert request.tool_backend == backend


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"incident": ""},
        {"incident": " \n\t "},
        {"incident": 123},
        {"incident": None},
        {"incident": "x" * 4001},
        {"incident": "Investigate.", "scenario": "../other"},
        {"incident": "Investigate.", "tool_backend": "remote"},
    ],
)
def test_start_request_rejects_invalid_input(payload):
    with pytest.raises(ValidationError):
        StartWorkflowRequest.model_validate(payload)


@pytest.mark.parametrize(
    "field, value",
    [
        ("database", "other.sqlite"),
        ("thread_id", "existing-thread"),
        ("model", "another-model"),
        ("response", "approve some-proposal"),
    ],
)
def test_start_request_rejects_server_controlled_or_unrelated_fields(field, value):
    with pytest.raises(ValidationError) as error:
        StartWorkflowRequest.model_validate({
            "incident": "Investigate checkout-service.",
            field: value,
        })

    assert any(
        item["type"] == "extra_forbidden"
        and item["loc"] == (field,)
        for item in error.value.errors()
    )


PROPOSAL_ID = "e44d2bcb-d640-4c54-ba6b-2291bb6560b9"


@pytest.mark.parametrize("decision", ["approve", "decline"])
def test_review_request_requires_explicit_decision(decision):
    request = ReviewWorkflowRequest(
        proposal_id=PROPOSAL_ID,
        decision=decision,
    )

    assert request.model_dump() == {
        "proposal_id": PROPOSAL_ID,
        "decision": decision,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"proposal_id": PROPOSAL_ID},
        {"decision": "approve"},
        {"proposal_id": "", "decision": "approve"},
        {"proposal_id": " ", "decision": "approve"},
        {"proposal_id": f" {PROPOSAL_ID}", "decision": "approve"},
        {"proposal_id": "two ids", "decision": "approve"},
        {"proposal_id": 123, "decision": "approve"},
        {"proposal_id": "x" * 129, "decision": "approve"},
        {"proposal_id": PROPOSAL_ID, "decision": True},
        {"proposal_id": PROPOSAL_ID, "decision": "yes"},
        {"proposal_id": PROPOSAL_ID, "decision": "APPROVE"},
        {
            "proposal_id": PROPOSAL_ID,
            "decision": "approve",
            "target_version": "different-version",
        },
    ],
)
def test_review_request_rejects_invalid_or_extra_fields(payload):
    with pytest.raises(ValidationError):
        ReviewWorkflowRequest.model_validate(payload)
