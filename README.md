# Verum

Verum is a set of eight advisory agents that read sensor data from a simulated Saudi gasoline terminal, rank the likely causes of an abnormal situation and suggest which inspection to do first. The eight roles are anomaly detection, predictive health, topology dependency, historical asset intelligence, diagnostic reasoning, inspection planning, inspection quality documentation, and evidence verification and decision. All data is synthetic: it comes from a simulator whose parameters are design selections and not measurements of a real terminal. The system is advisory only and never controls equipment. A runner chains the agents over one analysis window at a time, and a small local HTTP service plays those windows to a frontend.

## Requirements and installation

You need Python 3.11 or newer (the pinned dependencies in `requirements.txt` cover 3.11 and later), a terminal, and git.

1. Clone the repository and enter it.

```bash
git clone https://github.com/Areen-Alsemari/Verum_Backend.git
cd Verum_Backend
```

2. Check out the branch you were given, then create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows use `py -3 -m venv .venv` and `.venv\Scripts\activate`.

3. Install the runtime dependencies.

```bash
pip install -r requirements.txt
```

4. Make the `verum` package importable. The project is not installed as a package, so every command below expects the source folder on the Python path.

```bash
export PYTHONPATH=src
```

On Windows PowerShell the equivalent is `$env:PYTHONPATH = "src"`. Set it again in every new terminal.

To also run the tests and checks, install the development tools with `pip install -r requirements-dev.txt`. The pins in both files come from `uv.lock`, which is the source of truth, so an update of a dependency starts there.

## Data

No data is committed. The generated data takes several gigabytes, so the `data/` folder is ignored by git and you must generate it yourself. The generator is deterministic from a seed, but the result is only reproducible on the same code, the same dependency versions and, as the data guide notes, up to platform-dependent numerical details.

Two commands refuse to start in a state you may not expect. The full generator raises if the git working tree has uncommitted changes, so commit or discard your edits first. The release builder refuses to write into a folder that already exists.

### Quick start: a 60-episode pilot

This is the smallest supported generation: the 60-slot pilot campaign of the campaign generator, turned into a release with the same code as the full dataset. Run the commands in this order from the repository root, with the virtual environment active and `PYTHONPATH=src` set.

```bash
python tools/campaign.py pilot --root data/quickstart/campaign
python tools/campaign.py summary --root data/quickstart/campaign
python tools/dataset_release.py build --source data/quickstart/campaign --output data/quickstart/release
python tools/dataset_release.py materialize-all data/quickstart/release
python tools/dataset_release.py verify data/quickstart/release
python tools/dataset_release.py verify-roles data/quickstart/release
```

On a Mac with 10 cores, the pilot took 515 s (about 9 minutes) with the default worker count, and the other four commands took about 35 s together. The output uses about 110 MB, of which the campaign folder is about 70 MB and the release about 40 MB. The pilot prints the byte counts and `60 records` when it ends. The pilot is resumable, so after an interruption run the same command again.

When it worked, `summary` prints `status {'completed': 58, 'gap': 2}` and a split of 31 train, 17 validation and 10 test episodes. Two slots are recorded gaps: a simulation gate rejected their attempts, and a gap is a normal outcome and not an error. The folder `data/quickstart/campaign` holds `agent_visible/` (observations and labels an agent may see), `evaluator/` (truth and the manifest, never given to an agent), and `work/` and progress files. The folder `data/quickstart/release` holds `observations/`, `examples/`, `knowledge/`, `role_views/`, `evaluator/` (the source manifest and the truth copies, never given to an agent) and `release_manifest.json`. `verify` prints `"integrity_passed": true`, 58 episodes and 696 examples (372 train, 204 validation, 120 test), and `verify-roles` prints 24 role files, 3,785 examples and `"integrity_passed": true`.

You can start the service on this release for live runs with `python -m verum.service --port 0 --release data/quickstart/release`. Started that way it printed its address and answered `/api/health` with live mode on and replay mode off. I did not run the 181-window sample script on this release.

What this data can and cannot show: it is a small campaign of 58 episodes that uses a different configuration from the full one (a block of 60 slots, seed 20261102), so it checks that the generator, the release builder and the integrity checks work on your machine and gives the code something to read. Its counts, splits and any metric computed from it must not be compared with the numbers in `reports/`, which come from the 3,000-episode release. Several mechanisms have only a few episodes each, so no per-mechanism result on it means anything.

### Full generation: the dataset the reports describe

This produces the 3,000-episode reference release, split into 1,660 train, 756 validation and 584 test episodes, together with the roof reference runs and the role views of the eight agents. The recipe is committed in `config/extensions/reference_recipe_v2.json`: campaign seed 20261101, 3,004 slots, 3,600 s per episode.

```bash
python tools/generate_dataset.py --root data/reference_release_v2 --workers 3
```

The release ends up in `data/reference_release_v2/verum_reference_v2`, which is the folder the runner and the service look for by default. Next to it the command leaves the campaign (`campaign/`), the roof reference runs (`roof_reference_v1/`) and a compact `verum_reference_v2_training.zip` with its checksum file.

The campaign stage needs at least 20 GB of free disk space for its own check. In the copy of the author, the campaign folder is about 3.7 GB and the finished release about 2.1 GB. The run time depends on the machine and the worker count, and it is not written down anywhere in the repository, so no figure is given here. It is the slow part of the whole system, so keep the machine plugged in and awake for the whole run. On a Mac, start the command from the system Terminal with `caffeinate -i` in front of it. If it is interrupted, run the same command with the same `--root` again: the campaign stage continues from the slots already stored. If it stops after the campaign stage, do not delete the campaign. Follow `docs/data_generation.md`, which explains how to reuse a finished campaign with `--campaign` and `--roof-reference`.

A fresh run reports its own outcomes. Failed slots are recorded as gaps, so the seed does not by itself guarantee 3,000 completed episodes, and the counts below are the ones the reports describe.

### Check that generation worked

```bash
python tools/dataset_release.py verify data/reference_release_v2/verum_reference_v2
python tools/dataset_release.py verify-roles data/reference_release_v2/verum_reference_v2
```

On the release of the author, `verify` ran in about 15 s and printed `"integrity_passed": true`, 3,000 episodes, 36,000 examples, and 19,920 train, 9,072 validation and 7,008 test examples (12 windows per episode, which corresponds to 1,660, 756 and 584 episodes). `verify-roles` printed 24 role files, 180,339 examples and `"integrity_passed": true`. The episode counts per split are also stored in `release_manifest.json` under `splits`. If your numbers differ, the check can still pass, because it verifies that the files match their stored hashes and splits and not that the cohort has a given size. Compare the counts with the numbers above before you compare any result with the reports.

### Point the system at the data

The runner and the service read the release folder you pass with `--release`. The default is `data/reference_release_v2/verum_reference_v2` under the repository, so a full generation with the command above needs no extra setting. For any other folder, pass it explicitly as shown in the next section.

## Run the system

The system is the local run service. It plays windows of the synthetic terminal, either replayed from stored bundles or run live through the real agents on a validation episode. The service is written with the Python standard library only. It never reads the test split.

First store the replay sample once. This runs the full runner over a fixed, seeded sample of 181 windows of the train and validation splits and writes the bundles to `local/replay_sample`.

```bash
python tools/agents/run_runner_sample.py --out local/replay_sample
```

Then start the service.

```bash
python -m verum.service --port 8765 --replay-dir local/replay_sample --release data/reference_release_v2/verum_reference_v2
```

The service binds to 127.0.0.1 and allows the browser origin `http://localhost:5173`. `--port 0` picks a free port. Without `--replay-dir` replay is off, and without `--release` live runs are off. When it works, the first line printed is `verum service listening on http://127.0.0.1:<port>`, and `GET /api/health` returns `{"status": "ok", "service": "verum run service", "modes": {"replay": true, "live": true}}`. The routes, the events and a real example of each are in `docs/service_api.md`.

To see the options without starting anything, run `python -m verum.service --help`.

## Additional instructions

### Tests and checks

```bash
ruff check .
python tools/check_agent_interfaces.py
python tools/agents/check_stubs.py
python tools/agents/build_chained_fixtures.py --check
mypy
pytest -m fast
```

`pytest -m slow` also runs the long engine runs and needs the generated campaign. Two tests, `test_two_simultaneous_runs_share_no_state` and `test_each_failure_kind_has_its_own_issue_code[wrong_revision]`, are timing-sensitive: under heavy machine load they can fail, and they should be re-run alone before you look for a cause. The tests of reduced models check the code against itself and are not independent validation of the physics.

### Tracing

Tracing of the runner to LangSmith is optional and off by default. The system needs no account or key to run. To switch it on, install the extra package with `pip install "langsmith>=0.14.17"`, then set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in your shell. The key stays in your environment and never in the repository. Only summaries and digests are sent, and it must not be switched on for real plant data. `docs/runner_tracing.md` lists what is recorded and what is not.

### Repository layout

| Path | Contents |
| --- | --- |
| `src/verum/` | The package: simulator, sensors, inspection model, campaign generator, training and release code, the eight agents and the runner (`agents/`), and the service (`service/`) |
| `tools/` | Command line scripts: campaign and dataset generation, release checks, agent evaluation and the runner sample |
| `config/`, `schemas/`, `contracts/` | Machine-readable contracts and JSON Schemas that define the interfaces |
| `vendor/` | The audited input package manifest, read-only |
| `tests/` | The test suite |
| `docs/` | Design records, the data contract, the generation guide and the service API |
| `reports/` | Reports of studies and evaluations |
| `data/`, `local/` | Generated data and local outputs, ignored by git |

Start with `docs/project_scope.md` for the scope, `docs/data_generation.md` for the data, `docs/agent_interfaces.md` for the agents and `docs/service_api.md` for the service.

### Limitations

All data is synthetic. The parameters are design selections, and no value is a measurement of a real terminal, so a good result on this data does not show performance on a real plant. The data is not qualified for physical diagnostic training, and the release policy keeps production generation disabled. Several inspection outcomes and roof, damage and emission mechanisms are outside the supported scope, as `docs/project_scope.md` explains. The agents give advice and rank causes. They do not act on the plant, and a person decides what to do. The reports in `reports/` state what was and was not validated for each agent, and they should be read before any number is quoted.

### Windows and line endings

The files whose bytes are checked by a hash, in tests or in the detector artifact, are pinned to LF in `.gitattributes`. On Windows, files checked out before that pin was added can still carry CRLF line endings, which makes the hash checks fail and degrades the first agents of a run. After you pull a version that contains `.gitattributes`, refresh the pinned files once: save or discard your own edits to them, then run `git checkout HEAD -- config schemas vendor/MANIFEST.sha256 uv.lock src/verum/agents/anomaly_detection/artifacts src/verum/agents/predictive_health/ridge_models.json`. Do not change `core.autocrlf` for this.
