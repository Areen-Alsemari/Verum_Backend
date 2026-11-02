# Generate and share the Verum reference dataset

Commit source code, configuration, dependency locks, tests and documentation. Keep raw data, generated role files and archives under `data/`, which is already ignored by Git. No command below builds agents, trains models, publishes files or pushes the repository.

## Use the shared training bundle

The `verum_reference_v2_training.zip` bundle contains 24 compressed JSONL role/split files, public reference knowledge, the scope contract, generation recipe, counts and file hashes. It excludes raw telemetry, evaluator truth and legacy mechanical archives. Each example contains `input`, `target`, `example_id` and `use`. Feed only `input` to a model; reserve targets for supervision/scoring. Respect each `supervised_loss_mask`: null means unknown, never healthy or zero.

Use train for learning and preprocessing, validation for selection, and test for final evaluation. Keep all windows and mechanical variants of one parent in their assigned split. Roles 3, 4 and 6 include deduplicated reference fixtures rather than independent diagnosis benchmarks. Inspect the release's coverage counts before reporting results for sparse mechanisms.

After downloading the bundle through the team's chosen file-sharing service, verify it before extraction:

```bash
uv run python tools/dataset_release.py verify-archive /path/to/verum_reference_v2_training.zip
```

Compare the archive SHA-256 with the separately shared `.sha256.json` file. The archive also contains `BUNDLE_FILES.json`, which binds every payload file. Share the same bundle and checksum with all five members; do not give each member a differently sampled dataset or randomise new splits.

## Environment and source revision

Use the repository commit recorded in `generation_recipe.json` and `uv.lock`. From a clean checkout:

```bash
uv sync --locked --group dev
```

The audited research folder is not tracked. If running vendor-integrity checks, place the team's unchanged research files at `vendor/verum_audited/` and check them against the committed `vendor/MANIFEST.sha256`. The generator uses the tracked working contracts and source-matched reference copies; do not edit vendor documents, frozen schemas or unresolved parameters to make generation succeed.

## Generate from scratch

```bash
uv run python tools/generate_dataset.py --root data/team_reference_v2 --workers 3
```

The committed `reference_recipe_v2.json` reuses campaign seed 20261101, 3004 slots, the existing block composition and 3600 s episodes. Failed slots remain recorded gaps; the seed does not guarantee 3004 successful episodes. The pipeline then generates prospective coupled roof-boundary references, builds the scoped release, materializes all eight roles and creates the compact training archive. Legacy uncoupled mechanical generation is not part of this pipeline.

Raw simulation is much slower than exporting existing data. The existing campaign alone occupies about 3.7 GB in the current snapshot; generation also needs scratch, reference and export space. The campaign's existing free-space check requires at least 20 GB. Runtime depends on hardware, worker count and rejected attempts; there is no fixed completion-time promise. Reduce workers on smaller machines.

If interrupted during campaign generation, rerun the same command and root. Stored valid campaign slots are reused. A partially generated roof reference or export is not treated as complete: preserve that partial directory for investigation and use a new output root with completed sources explicitly supplied. Do not delete the original campaign or silently overwrite a completed release.

## Reuse completed simulation data

To avoid regenerating the expensive simulations, copy the existing complete campaign and roof reference folders outside Git, then run:

```bash
uv run python tools/generate_dataset.py --root data/team_export_v2 --campaign data/campaign --roof-reference data/roof_reference_v1 --workers 3
```

The pipeline checks the supplied campaign configuration against the committed recipe and checks that the roof references belong to that campaign. Source observation content is verified against stored hashes and copied unchanged. Original splits, unsuccessful slots and all prescribed reference attempts remain recorded. Supplemental sources are explicit; merely having an old mechanical folder nearby cannot change the output.

For the current cohort, the shared export contains 3000 completed hydraulic episodes. The roof reference protocol records 14 attempts, of which 12 complete and two reach the existing pumping minimum. Those outcomes are retained without a success-conditioned redraw. The completed runs supply 12 covered manual-level records; their condition acceptance remains inconclusive. Fresh generation must report its actual outcomes rather than forcing these counts.

## Inspect or export individual stages

```bash
uv run python tools/dataset_release.py build --source data/campaign --inspection-source data/roof_reference_v1 --output data/manual_reference_v2 --workers 3
uv run python tools/dataset_release.py materialize-all data/manual_reference_v2
uv run python tools/dataset_release.py verify data/manual_reference_v2
uv run python tools/dataset_release.py verify-roles data/manual_reference_v2
```

The end-to-end generator additionally records the recipe, copies this guide and produces a complete package. Use it for the final team handoff. Low-level export is useful for investigation and deliberately refuses to overwrite existing releases or role files.

## Reproducibility and sharing

All team members should use the same source commit, recipe, lockfile and source data. Gzip headers, elapsed times, provenance commits and platform-dependent numerical details can affect stored-byte hashes across fresh runs; seed reproducibility does not promise an identical ZIP checksum. Use the supplied hashes to identify the exact shared artifact. The campaign stores decompressed-content hashes so regenerated observations can be compared independently of gzip timestamps.

For the release commit, run both test groups, lint, strict types and the vendor checks after the last source edit:

```bash
uv run pytest -m fast
uv run pytest -m slow
uv run ruff check src tests
uv run mypy
uv run pytest local/checks
```

GitHub blocks ordinary Git files above 100 MiB and recommends distributing large artifacts separately. Keep this repository's existing `data/` ignore rule. The team can distribute the archive through university storage, a shared drive or a manually created release asset, and distribute its checksum alongside it. There is no upload or push in the pipeline. See [GitHub's large-file guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

The supported project boundary is documented in [project scope](project_scope.md). Software verification does not turn excluded roof rupture, damaged-emission or mechanical cascade mechanisms into supported training targets.
