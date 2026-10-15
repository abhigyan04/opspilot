from copy import deepcopy


def _token_count(response, field: str) -> int | None:
    value = getattr(response, field, None)
    if type(value) is int and value >= 0:
        return value
    return None


class UsageCollector:
    def __init__(self):
        self._calls: list[dict] = []

    def record(self, *, stage: str, model: str, response=None) -> None:
        self._calls.append({
            "stage": stage,
            "model": model,
            "input_tokens": _token_count(response, "prompt_eval_count"),
            "output_tokens": _token_count(response, "eval_count"),
        })

    def snapshot(self) -> dict:
        calls = deepcopy(self._calls)
        totals = {"attempts": len(calls)}

        for direction in ("input", "output"):
            field = f"{direction}_tokens"
            known = [
                call[field]
                for call in calls
                if call[field] is not None
            ]

            totals[f"{direction}_counted_calls"] = len(known)
            totals[f"known_{direction}_tokens"] = sum(known)
            totals[field] = (
                sum(known) if len(known) == len(calls) else None
            )

        return {
            "calls": calls,
            "totals": totals,
        }
