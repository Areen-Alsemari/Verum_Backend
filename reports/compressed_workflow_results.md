# Compressed workflow on the meaningful validation windows

This report describes a plumbing test, not a detection result. A simulated inspection is fed to Agents 7 and 8, with the next real window of the same episode as the second pass, to see whether they can leave their degraded states on real validation observations. Everything simulated is marked "SIMULATED INSPECTION" and "time_compressed: true" in a free-text field of the object itself.

## Windows

- The run covers the fixed 169-window validation sample, read through the audit hook and the guard of the detector experiments. No test-split file was opened.
- A window is meaningful when it has one injected component, that component sits on a catalogue asset, and Agent 5 names that asset first. This is the definition of the runner follow-up report, applied unchanged. Labels select the windows and are not an input to the simulation.
- **Meaningful windows over validation only: 25.** The earlier follow-up report counted 30, which differs: that count ran over the 169 validation windows and 12 train windows, and 5 of its 30 were train windows. The validation set here is the same 25 windows as the validation part of the earlier count; none was added or removed.
- Of the 25, 23 have a later real window in the same episode and were run as a second pass. 2 are at the last position (12) and report "no second pass available"; the earlier count had a third, which was a train window.
- The second pass is the window of the same episode 300 s later, so the inspection is treated as performed at the first cutoff and visible at the next one. The catalogue delays of approval, scheduling and execution do not apply.

## The simulated inspection

- The request wall-clock time `as_of_utc` is the fixed synthetic episode start of the sensor configuration (2026-01-01T00:00:00.000Z, the same for every episode) plus the window cutoff in seconds. A window at 300 s has 2026-01-01T00:05:00.000Z. With it set, Agent 7 can compare the calibration date; without it that check can never pass. The default stays unset and the 181-window sample is byte-identical with the default.
- The target and action are the first option of the Agent 6 report that addresses a hypothesis. The request is approved and made at the first cutoff.
- The result is a performed result in research mode: valid evidence, passed quality assurance, calibration valid until 2026-12-31, the first catalogue output of the action with the value 0.0, the catalogue uncertainty (0.0 where the catalogue states none), and the category TEST_INCONCLUSIVE, so it states no equipment condition.
- A coverage row for the target spans the start of the process to the second cutoff and cites the registered observation evidence. One evidence proposal names the result.
- Request, result, coverage identifier and proposal identifier carry the two markers; the result carries them in its free-text observations, and the others in the identifier or permit fields, because the schemas forbid extra fields.
- Identifiers come from a counter over the meaningful windows in processing order. The rule reads the Agent 6 and Agent 5 reports of the first pass and the catalogue, and no label.

## Results per window

Agents 6, 7 and 8 and the Agent 8 decision, first pass and second pass. "Left degraded" means that after the second pass Agent 7 is complete and Agent 8 is not degraded.

| Window | Position | Cutoff (s) | Action | Target | A6 first | A7 first | A8 first | Decision first | Second pass | A6 second | A7 second | A8 second | Decision second | Left degraded |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ad926ec19daa9626d9c996a6 | 10 | 3000 | ACT-INSP-02 | XV-PBO | degraded | degraded | degraded | more evidence | run | degraded | complete | degraded | review required | no |
| 04c2b362473b503b03349704 | 8 | 2400 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 5fcd8fe20b7109cf25c624fc | 8 | 2400 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 030cc598b1d39ee3476e7870 | 10 | 3000 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 3087a1b07fa6a59220074dfa | 11 | 3300 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| c42fc2b9dd591bda6fcdf98e | 12 | 3600 | none | none | degraded | degraded | degraded | more evidence | no second pass available | | | | | |
| 69fde3943af70fb62328d57d | 7 | 2100 | ACT-INSP-02 | XV-PAO | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| f8477d1b84728439ed0c01cc | 7 | 2100 | ACT-INSP-03 | P-101A | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| a3803bbd59204abdde1d4e7e | 9 | 2700 | ACT-INSP-03 | P-101A | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 1df71589104db67cbfe838c8 | 10 | 3000 | ACT-INSP-03 | P-101A | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 7f7df8553297a8046d970193 | 10 | 3000 | ACT-INSP-03 | P-101A | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| ac9628bb618503f6ffe01da0 | 10 | 3000 | ACT-INSP-03 | P-101B | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| f299895ed8c0cdbc3ece1f3f | 10 | 3000 | ACT-INSP-02 | XV-R101 | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| fa373f2c275c862bd4ed4123 | 11 | 3300 | ACT-INSP-02 | XV-R101 | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 4ddcb4b8ddf878c9b869157d | 12 | 3600 | none | none | degraded | degraded | degraded | more evidence | no second pass available | | | | | |
| c1f89eff843fafb6bb7071cc | 11 | 3300 | ACT-INSP-03 | P-101B | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 1e03d2318d3c4e191b3f6160 | 9 | 2700 | ACT-INSP-02 | XV-S103 | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 9d696df476514e470e8cbd61 | 11 | 3300 | ACT-INSP-02 | XV-S102 | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| faf4f6ce8690950cd6a57da8 | 11 | 3300 | ACT-INSP-02 | XV-S103 | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 599048f010064f5bd80d3cea | 10 | 3000 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 0d44b59aa46c68d75cd836f2 | 8 | 2400 | ACT-INSP-03 | P-101B | degraded | degraded | degraded | more evidence | run | insufficient | complete | degraded | more evidence | no |
| 958b066906ceb1744ed87f0c | 11 | 3300 | ACT-INSP-02 | XV-PAI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| 2169eb6bf7ba0845c82dd763 | 7 | 2100 | ACT-INSP-02 | XV-PBI | degraded | degraded | degraded | more evidence | run | insufficient | complete | degraded | more evidence | no |
| ba16e5d4c0e7d6e05940adbf | 10 | 3000 | ACT-INSP-02 | XV-PAI | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |
| b5b528204ba116e4bacc3b44 | 11 | 3300 | ACT-INSP-03 | P-101B | degraded | degraded | degraded | more evidence | run | degraded | complete | complete | assessment available | yes |

## Summary

- First pass, all 25 windows: Agent 6 degraded (preconditions unknown), Agent 7 degraded (no inspection results), Agent 8 degraded with more evidence required.
- Second pass, 23 windows: Agent 7 is complete in all 23, with every check passed and no issue, and Agent 8 judges the proposal usable in all 23.
- **20 of 23 leave degraded** and reach assessment available: 13 of the 15 valve-check windows and 7 of the 8 pump-vibration windows.
- Agent 6 stays degraded in the windows that leave, with the issue code INSPECTION_PRECONDITIONS_UNKNOWN; the report does not say which precondition remains unknown.
- **3 do not leave degraded**, and in each Agent 8 itself stays degraded:
- Window ad926ec19daa9626d9c996a6 (position 10, ACT-INSP-02 on XV-PBO): Agent 6 is degraded (INSPECTION_PRECONDITIONS_UNKNOWN) and Agent 8 returns review_required with the issue EVIDENCE_DECISION_REVIEW_REQUIRED, although Agent 7 judges the record complete and Agent 8 judges the proposal usable.
- Window 0d44b59aa46c68d75cd836f2 (position 8, ACT-INSP-03 on P-101B): Agent 6 is insufficient_evidence (NO_COMPATIBLE_INSPECTION_OPTIONS) and Agent 8 returns more_evidence_required with the issue EVIDENCE_DECISION_MORE_EVIDENCE_REQUIRED, although Agent 7 judges the record complete and Agent 8 judges the proposal usable.
- Window 2169eb6bf7ba0845c82dd763 (position 7, ACT-INSP-02 on XV-PBI): Agent 6 is insufficient_evidence (NO_COMPATIBLE_INSPECTION_OPTIONS) and Agent 8 returns more_evidence_required with the issue EVIDENCE_DECISION_MORE_EVIDENCE_REQUIRED, although Agent 7 judges the record complete and Agent 8 judges the proposal usable.
- The reason Agent 8 returns these decisions was read from its issue codes only; its internal ranking was not examined. In two of the three the later window gives Agent 6 no compatible option, which coincides with Agent 8 not accepting an otherwise usable proposal.

## Limits

- The inspection is simulated. No real inspection exists in the recorded data, and nothing here comes from a measurement.
- The workflow is time compressed. The inspection is treated as performed at the first cutoff and the second pass is only 300 s later, which no real inspection of the catalogue allows.
- The result is not evidence of detection quality, of the usefulness of any inspection, or of the state of any asset. The value is a constant, the category states no condition, and Agent 5 and Agent 7 do not read the content of a finding.
- The rule is arbitrary. The choice of the first option, the constant value, the research-mode label, the valid and passed-QA status, the fixed calibration date and the coverage row were fixed by hand so that a well-formed record reaches Agents 7 and 8. That Agent 7 judges every record usable follows from the construction, not from any property of the data.
- The pump action has no modelled outcome and no catalogue uncertainty. Its 8 results carry an uncertainty of 0.0 that the catalogue does not state, and the pump actions are not qualified inspection evidence.
- The coverage row claims that the observation window supports the target at the performed time, which the observations alone do not establish.
- The sample is 25 windows chosen by the selection described above, not a random draw, and the second pass reuses Agent 5 on a window 300 s later with the earlier assessments as history.
- Earlier runs of the audit hook on Windows classified no path, because the guard compared forward-slash paths. The guard now normalises separators, and in this run it allowed only validation role views, validation examples, the reference and the manifest.
