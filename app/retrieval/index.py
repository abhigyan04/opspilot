import json
import math
from pathlib import Path

from app.retrieval.provenance import manifest_fingerprint


def _validate_vectors(vectors: list, manifest: dict) -> None:
    dimensions = manifest["embedding"]["dimensions"]
    if type(dimensions) is not int or dimensions < 1:
        raise ValueError("Invalid embedding dimensions.")

    if not isinstance(vectors, list):
        raise ValueError("Vectors must be a list.")

    if len(vectors) != len(manifest["chunks"]):
        raise ValueError("Vector count does not match passages.")

    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ValueError("Invalid vector dimensions.")

        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError("Vector values must be finite numbers.")

        if not any(value != 0 for value in vector):
            raise ValueError("Zero vectors are invalid.")


def save_index(destination: Path, manifest: dict, vectors: list[list[float]]) -> Path:
    _validate_vectors(vectors, manifest)

    payload = {
        "index_version": 1,
        "manifest": manifest,
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "vectors": vectors,
    }
    # Detect accidental changes to vectors as well as metadata.
    payload["payload_fingerprint"] = manifest_fingerprint(payload)

    serialized = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Existing indexes are never silently overwritten.
    with destination.open("x", encoding="utf-8") as output:
        output.write(serialized)
        output.write("\n")

    return destination


def load_index(source: Path, *, expected_manifest: dict) -> list[list[float]]:
    payload = json.loads(source.read_text(encoding="utf-8"))

    expected_keys = {
        "index_version",
        "manifest",
        "manifest_fingerprint",
        "vectors",
        "payload_fingerprint",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("Invalid index structure.")

    if type(payload["index_version"]) is not int or payload["index_version"] != 1:
        raise ValueError("Unsupported index version.")

    recorded_payload_hash = payload.pop("payload_fingerprint")
    if manifest_fingerprint(payload) != recorded_payload_hash:
        raise ValueError("Index payload fingerprint mismatch.")

    stored_manifest_hash = manifest_fingerprint(payload["manifest"])
    if stored_manifest_hash != payload["manifest_fingerprint"]:
        raise ValueError("Index manifest fingerprint mismatch.")

    if stored_manifest_hash != manifest_fingerprint(expected_manifest):
        raise ValueError("Index is stale: current inputs differ.")

    _validate_vectors(payload["vectors"], expected_manifest)
    return payload["vectors"]
