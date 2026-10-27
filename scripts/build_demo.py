import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "app" / "web"
SCENARIOS = ("checkout_regression", "payment_provider_outage")


def build_demo(output: Path) -> dict:
    html = (WEB_ROOT / "demo.html").read_text(encoding="utf-8")

    old_link = 'href="./demo.html"'
    if html.count(old_link) != 1:
        raise ValueError("Expected exactly one demo home link.")

    html = html.replace(old_link, 'href="./"')
    files = {"index.html": html.encode("utf-8")}

    for scenario in SCENARIOS:
        name = f"demo-data/{scenario}.json"
        content = (WEB_ROOT / name).read_bytes()
        data = json.loads(content)

        if (
            data["scenario"] != scenario
            or data["mode"] != "recorded_demo"
            or data["synthetic"] is not True
        ):
            raise ValueError(f"Unexpected demo metadata: {scenario}")

        workflow = data["workflow"]
        if workflow["next"] or workflow["interrupts"]:
            raise ValueError(f"Demo contains pending workflow work: {scenario}")
        if workflow["state"].get("proposal_id"):
            raise ValueError(f"Demo contains an actionable proposal ID: {scenario}")

        files[name] = content

    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Output must be a new or empty directory: {output}")

    output.mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, content in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest.append({
            "file": name,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })

    return {"output_directory": str(output), "files": manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static recorded demo.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_demo(args.output), indent=2))


if __name__ == "__main__":
    main()
