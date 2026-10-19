# Investigating application exceptions

This is synthetic operational guidance, not evidence about a current incident.

## Symptoms

Unhandled exceptions can cause request failures. Attribute errors involving
None may indicate that code assumed an object existed when it did not.

## Investigation

Capture the exact exception and available stack trace. Identify the failing
expression and determine which object could be absent.

Inspect changes to that code path and compare deployment timing with the
observed errors. A matching code change and exception strengthen a regression
hypothesis, but timing alone does not prove causation.

Check affected request types and application versions. Do not infer a specific
user state, such as unauthenticated access, without supporting observations.

## Response considerations

A rollback candidate requires a relevant change, an available target version,
and an assessment of compatibility and operational risk.

If evidence is incomplete, state the hypothesis and missing observations.
Do not invent a stack trace, request payload, or reproduction result.

## Verification

Check post-action exception frequency and service error metrics. Confirm
whether the affected request path was exercised during the observation window.
