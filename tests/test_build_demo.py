import hashlib
import json
import shutil

import pytest

from scripts import build_demo as builder


def test_bundle_contains_only_demo_assets_and_preserves_data(tmp_path):
    output = tmp_path / "site"
    manifest = builder.build_demo(output)

    expected = {
        "index.html",
        "demo-data/checkout_regression.json",
        "demo-data/payment_provider_outage.json",
    }
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert actual == expected

    html = (output / "index.html").read_text(encoding="utf-8")
    assert 'href="./"' in html
    assert 'href="./demo.html"' not in html

    for scenario in builder.SCENARIOS:
        name = f"demo-data/{scenario}.json"
        assert (output / name).read_bytes() == (
            builder.WEB_ROOT / name
        ).read_bytes()

    assert {item["file"] for item in manifest["files"]} == expected
    for item in manifest["files"]:
        content = (output / item["file"]).read_bytes()
        assert item["bytes"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()


def test_bundle_does_not_overwrite_existing_output(tmp_path):
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep this", encoding="utf-8")

    with pytest.raises(ValueError, match="new or empty directory"):
        builder.build_demo(output)

    assert sentinel.read_text(encoding="utf-8") == "keep this"
    assert list(output.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    "invalid_field",
    ["mode", "synthetic", "pending_work", "proposal_id"],
)
def test_invalid_demo_data_is_rejected_before_writing(
    tmp_path, monkeypatch, invalid_field
):
    source = tmp_path / "source"
    shutil.copytree(builder.WEB_ROOT, source)
    monkeypatch.setattr(builder, "WEB_ROOT", source)

    path = source / "demo-data" / "checkout_regression.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    if invalid_field == "mode":
        data["mode"] = "live"
    elif invalid_field == "synthetic":
        data["synthetic"] = False
    elif invalid_field == "pending_work":
        data["workflow"]["next"] = ["review"]
    else:
        data["workflow"]["state"]["proposal_id"] = "pending-proposal"

    path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "site"

    with pytest.raises(ValueError):
        builder.build_demo(output)

    assert not output.exists()
