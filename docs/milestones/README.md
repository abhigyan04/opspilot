# Engineering history and detailed recipes

These documents preserve the detailed material moved from the root README on
27 October 2026. They record development checkpoints and command examples, not
a single current setup guide. Run their commands from the repository root;
some examples require saved local reports or optional services.

Start with the [current README](../../README.md) for the web application,
[architecture](../architecture.md) for component boundaries, and
[milestone status](../milestone-status.md) for the current technical checkpoint.

| Archive | Contents | Review evidence |
|---|---|---|
| [Core development](core-development.md) | Investigation, diagnosis, simulation, recovery, tests, evaluation runner, replay, review, and CI recipes | [Grounding baseline](../grounding-baseline-results.md) |
| [Milestone 8](milestone-08.md) | Evaluation audit and historical completion planning | [Baseline](../milestone-8-baseline.md) |
| [Milestone 9](milestone-09.md) | Knowledge collection, embeddings, ranking, indexes, pgvector, optional references, and generation bounds | [RAG review](../milestone-9-review.md) |
| [Milestone 10](milestone-10.md) | Read-only MCP investigation tools and runner integration | [MCP review](../milestone-10-review.md) |
| [Milestone 11](milestone-11.md) | LangGraph, checkpoints, restart, proposals, and human review | [Workflow review](../milestone-11-review.md) |
| [Milestone 12](milestone-12.md) | Local API, Docker application, and offline simulation control report | [UI and deployment review](../milestone-12-review.md) |

The source text is preserved within each archive, with relative Markdown links
adjusted for its new location. Historical next-step statements and measurements
have not been rewritten to look like current results. The index orders milestones
numerically even though the former README appended milestone 9 after milestone 12.
