# Agent 2: the random forest was evaluated and removed

The random forest that Agent 2 used to score signal departures was evaluated against the plain baselines in the detector experiment (`reports/detector_experiment_results.md`, row C0). It was at chance level on the validation windows and was removed from Agent 2.

## What was measured

On the 3,980 eligible validation windows (prevalence 0.125), with 95% intervals over episodes:

- Average precision 0.149 (0.117 to 0.181). The interval contains the prevalence, so the score does not rank faulty windows above fault-free ones better than a constant would.
- Matched-stage AUROC 0.485 (0.435 to 0.536). The interval contains 0.5.
- At its shipped threshold it alarmed on 0.886 of fault-free windows and on 0.990 of faulty ones, which is close to flagging every window.

Its controls and the explanation of why the earlier, better-looking numbers did not hold are in the same report.

## What changed

- The model file, its pinned hash, its training script and its two evaluation reports were deleted from the Agent 2 package and from the tools folder.
- Agent 2 now runs the topology residual detector, method `topology_residual_v1`, described in `reports/detector_v3_c3_characterisation.md` and `reports/detector_v4_pooled_stress.md`.
- The files are recoverable from the history of the branch before this change.
