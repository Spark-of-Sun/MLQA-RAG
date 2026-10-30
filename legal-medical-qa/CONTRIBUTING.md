# Contributing

* Python 3.14, `uv sync --frozen --all-packages`. `make lint` and `make test` must pass.
* No mocks, fakes, factories or frozen clocks: tests use the real PostgreSQL, Valkey, Qdrant, object
  store and key provider (`make infra-test`). Fixtures come from `corpus/manifest.toml` only.
* A test that needs an ML model is marked `live_models`; one that needs AWS is `live_aws`. Never run
  those on a small machine.
* Every security-relevant bug gets a regression test first. Bulk edits are asserted to match exactly
  once; never write a regex that can span two statements.
* `make gate STAGE=n` re-runs every gate from stage 0 to n.
