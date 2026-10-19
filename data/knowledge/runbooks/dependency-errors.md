# Investigating dependency errors

This is synthetic operational guidance, not evidence about a current incident.

## Symptoms

Requests to an upstream dependency may return HTTP 502, 503, or 504,
or fail with connection and read timeouts. The calling service may
also report increased errors or latency.

## Investigation

Identify the dependency and operation named in the failing requests.
Compare dependency failures with the calling service's error metrics.

Establish the earliest observed failure and compare it with deployment
timestamps. Failures observed before a deployment weaken the hypothesis
that this deployment initiated the incident. They do not rule out a
later deployment worsening it.

Check whether failures affect multiple application versions or callers.
Seek dependency health information when available. A 503 response alone
does not establish the underlying cause inside the dependency.

## Response considerations

Consider the documented fallback or escalation procedure for the affected
dependency. Retrying requests may increase load or duplicate side effects;
verify retry and idempotency requirements before recommending changes.

Do not recommend application rollback solely because a deployment is recent.
Require evidence connecting an application change to the observed failure.
Any operational action remains subject to the application's approval controls.

## Verification

After an action, inspect new error and latency measurements for the affected
operation. Separate observed recovery from a claim that the action caused it.
