import argparse
import json
from pathlib import Path

from evals.assessment import DiagnosisReview, save_review
from evals.citations import build_citation_view


CRITERIA = {
    "causal_explanation": "Does it identify the supported failure mechanism?",
    "deployment_reasoning": "Does it interpret deployment timing and changes correctly?",
    "evidence_grounding": "Are claims and citations supported by the observations?",
    "uncertainty_handling": "Does it handle unknowns and choose whether to abstain appropriately?",
}

VERDICTS = {
    "1": "met",
    "2": "not_met",
    "3": "not_assessable",
}


def collect_review(report: dict, reviewer: str, input_fn=input, output_fn=print) -> DiagnosisReview:
    if report.get("report_version") != 2:
        raise ValueError("Review requires a version 2 run report.")

    output_fn(json.dumps(report, indent=2))
    citation_view = build_citation_view(report)
    if citation_view:
        output_fn(
        "Claim-by-claim citations: check whether these observations "
        "support every part of each statement. A resolved ID alone "
        "does not establish support."
        )
        output_fn(json.dumps(citation_view, indent=2))
    output_fn(
        "Compare the diagnosis with the actual observations and reference answer. "
        "Do not treat earlier model reasoning as evidence. "
        "If no diagnosis exists, select not_assessable for every criterion."
    )

    payload = {
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "reviewer": reviewer,
    }

    for name, question in CRITERIA.items():
        output_fn(f"\n{name}: {question}")

        while True:
            choice = input_fn(
                "1 = met, 2 = not_met, 3 = not_assessable: "
            ).strip()
            if choice in VERDICTS:
                break
            output_fn("Enter 1, 2, or 3.")

        while True:
            rationale = input_fn("Rationale: ").strip()
            if rationale:
                break
            output_fn("A nonblank rationale is required.")

        payload[name] = {
            "verdict": VERDICTS[choice],
            "rationale": rationale,
        }

    return DiagnosisReview.model_validate(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Record a human review of an evaluation report."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        review = collect_review(report, args.reviewer)
        destination = save_review(review, args.report)
    except (EOFError, KeyboardInterrupt):
        print("\nReview cancelled; no review saved.")
        raise SystemExit(130)
    except (ValueError, OSError) as error:
        print(f"Review failed: {error}")
        raise SystemExit(1)

    print(f"Review saved: {destination}")
