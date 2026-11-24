# Negative controls (blueprint 19.1 rule R6)

A control is a planted fault that a gate must catch. Controls are instruments, not data: each one is listed here,
carries `@pytest.mark.control`, and runs in the same lane as the check it proves. An unlisted control fails review.

| ID | Gate | Planted fault | Where | Expected result |
| --- | --- | --- | --- | --- |
| C-IMPORT | G0.5 | A package importing `lmqa_vectorstore` against a forbidden contract | `tests/controls/lmqa_control_violation/` | `lint-imports` exits non-zero and names the contract |
| C-MOCK | G0.11 | A module importing `unittest.mock` | written to ruff's stdin at test time, never committed | `ruff check` reports TID251 |
| C-SECRET | G0.6 | An AWS-style access key and a private-key block | generated in a temporary directory at test time, never committed | `gitleaks dir` exits 1 |
| C-RLS-OFF | G1.3 | FORCE RLS removed on an isolated test database | Stage 1 | the boot self-test refuses to start |
| C-PIN | G0.1 | Compose services with a tag-only image, a digest without a tag, a short digest and no image | built in memory by `tests/contract/test_stage0_toolchain.py::test_control_the_pin_check_rejects_unpinned_images`, never committed | `unpinned_images` names every planted service and accepts `name:tag@sha256:<64 hex>` |
