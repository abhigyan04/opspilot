from pathlib import Path

from app.tools.data import DEFAULT_SCENARIO_DIR, read_fixture


def get_commit(commit_hash: str, *, data_dir: Path = DEFAULT_SCENARIO_DIR) -> dict | None:
    commits = read_fixture("commits.json", data_dir)

    return next(
        (commit for commit in commits if commit["hash"] == commit_hash),
        None,
    )
