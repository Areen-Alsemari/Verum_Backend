"""Report the Agent 5 candidate evaluation: the validation split and the 181-window sample.

Subcommand split reads the score files of the previous and the new Agent 5 written by
evaluate_agent5_candidates.py and prints the measures, the controls and the pre-registered stop
rule; every interval resamples whole episodes, never single windows. Subcommand sample compares
the stored bundles of two runs of run_runner_sample.py. Neither opens the release folder.
See reports/agent5_candidates_results.md for the commands.
"""

from __future__ import annotations

import gzip
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SEED, RESAMPLES = 20261108, 1000
SHUFFLES = tuple(f"shuffle{s}" for s in range(5))
COARSE = {
    "pump": "pump",
    "restriction_position_visible": "restriction",
    "restriction_obstruction": "restriction",
    "leak": "leak",
    "bias": "sensor fault",
    "drift": "sensor fault",
    "stuck": "sensor fault",
    "misroute_a": "misrouting",
}
TARGETS = ("-P-101A", "-P-101B", "-PT-001", "-PT-201", "-PT-202A", "-PT-202B", "-PT-203")
ROLES = {5: "diagnostic_reasoning", 6: "inspection_planning", 8: "evidence_verification_decision"}
Views = dict[str, dict[str, Any]]


def load(path: str | Path) -> dict[str, Any]:
    """A gzipped JSON file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        value: dict[str, Any] = json.load(f)
    return value


def injected(w: dict[str, Any]) -> tuple[set[str], set[tuple[str, Any]]]:
    """Coarse families and mechanism-asset pairs of the injected components."""
    comps = w["components"]
    return {COARSE[c["mechanism"]] for c in comps}, {(c["mechanism"], c["asset_id"]) for c in comps}


def hits(hyps: list[dict[str, Any]], w: dict[str, Any], k: int) -> tuple[int, int]:
    """Family and exact match within the first k hypotheses; no hypothesis is a miss."""
    fams, pairs = injected(w)
    top = hyps[:k]
    family = any(COARSE[h["mechanism"]] in fams for h in top)
    exact = any((h["mechanism"], h["asset"]) in pairs for h in top)
    return int(family), int(exact)


def boot(per_episode: dict[str, list[float]]) -> tuple[float, float]:
    """95% percentile interval of a paired mean difference, resampling whole episodes."""
    eps = sorted(per_episode)
    rnd = random.Random(SEED)
    vals = []
    for _ in range(RESAMPLES):
        pick = [eps[rnd.randrange(len(eps))] for _ in eps]
        total = sum(per_episode[e][1] for e in pick)
        vals.append(sum(per_episode[e][0] for e in pick) / total if total else 0.0)
    vals.sort()
    return vals[int(0.025 * RESAMPLES)], vals[int(0.975 * RESAMPLES) - 1]


def family_of_id(hyp_id: str) -> str:
    """Family and named target of a candidate identifier HYP-A2-NN-<family>-<target>."""
    rest = hyp_id.split("-", 3)[3]
    if rest.endswith("-family-level"):
        return rest.removesuffix("-family-level")
    for target in TARGETS:
        if rest.endswith(target):
            return f"{rest.removesuffix(target)} @{target[1:]}"
    return rest


def difference(views: Views, windows: Views, faulty: list[str], v: str, k: int, which: int) -> Any:
    """Point difference of variant v against prev and its episode interval (k 0 is coverage)."""
    per: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for i in faulty:
        new, old = views[i][v]["hyps"], views[i]["prev"]["hyps"]
        if k == 0:
            d = int(bool(new)) - int(bool(old))
        else:
            d = hits(new, windows[i], k)[which] - hits(old, windows[i], k)[which]
        per[windows[i]["episode_id"]][0] += d
        per[windows[i]["episode_id"]][1] += 1
    return (sum(p[0] for p in per.values()) / len(faulty), *boot(per))


def identity(views: Views, windows: Views, ids: list[str]) -> list[str]:
    """Identity controls; returns the windows that gain candidates."""
    with_prev = [i for i in ids if views[i]["prev"]["hyps"]]
    gained = [i for i in ids if not views[i]["prev"]["hyps"] and views[i]["new"]["hyps"]]
    rest = [i for i in ids if not views[i]["prev"]["hyps"] and i not in set(gained)]

    def same(a: str, b: str, key: str, rows: list[str]) -> str:
        return f"{sum(views[i][a][key] == views[i][b][key] for i in rows)} of {len(rows)}"

    versions = sorted({views[i][v]["version"] for i in ids for v in ("prev_absent", "absent")})
    free = sum(1 for i in gained if not windows[i]["components"])
    print("\n## identity\n| control | windows |\n|---|---|")
    whole = same("prev_absent", "absent", "digest", ids)
    print(f"| absent: whole response equals previous | {whole} |")
    unversioned = same("prev_absent", "absent", "digest_unversioned", ids)
    print(f"| absent: equal apart from the implementation version | {unversioned} |")
    print(f"| implementation versions (previous, new) | {', '.join(versions)} |")
    print(f"| previous hypothesis: equal apart from the version | "
          f"{same('prev', 'new', 'digest_unversioned', with_prev)} |")  # fmt: skip
    print(f"| no hypothesis, no candidate: equal apart from the version | "
          f"{same('prev', 'new', 'digest_unversioned', rest)} |")  # fmt: skip
    print(f"| windows that gain candidates | {len(gained)} (faulty {len(gained) - free}, "
          f"fault-free {free}) |")  # fmt: skip
    return gained


def measures(views: Views, windows: Views, faulty: list[str]) -> dict[str, int]:
    """Coverage and accuracy of every variant; returns coverage by variant."""
    n = len(faulty)
    coverage = {}
    print("\n## faulty windows\n| variant | coverage | family top-1 | family top-3 | exact top-1 "
          "| exact top-3 |\n|---|---|---|---|---|---|")  # fmt: skip
    for v in ("prev", "new", "absent", *SHUFFLES):
        cov = sum(bool(views[i][v]["hyps"]) for i in faulty)
        rates = [sum(hits(views[i][v]["hyps"], windows[i], k)[w] for i in faulty) / n
                 for k, w in ((1, 0), (3, 0), (1, 1), (3, 1))]  # fmt: skip
        coverage[v] = cov
        print(f"| {v} | {cov} ({cov / n:.3f}) | " + " | ".join(f"{r:.3f}" for r in rates) + " |")
    return coverage


def differences(views: Views, windows: Views, faulty: list[str]) -> dict[str, Any]:
    """Paired differences against prev with 95% intervals over whole episodes."""
    print("\n## paired differences against prev, 95% interval from 1,000 resamples of whole "
          "episodes\n| variant | measure | difference | interval |\n|---|---|---|---|")  # fmt: skip
    found = {}
    measures_ = (("coverage", 0, 0), ("family top-1", 1, 0), ("family top-3", 3, 0),
                 ("exact top-1", 1, 1), ("exact top-3", 3, 1))  # fmt: skip
    for v in ("new", "absent", *SHUFFLES):
        for label, k, which in measures_:
            if v in SHUFFLES and label != "family top-1":
                continue
            point, lo, hi = difference(views, windows, faulty, v, k, which)
            found[(v, label)] = (point, lo, hi)
            print(f"| {v} | {label} | {point:+.3f} | {lo:+.3f} to {hi:+.3f} |")
    return found


def fault_free(views: Views, free: list[str], gained: list[str]) -> dict[str, int]:
    """Hypotheses on fault-free windows; returns the confident count by variant."""
    confident = {}
    print("\n## fault-free windows\n| variant | windows with a hypothesis | hypotheses | "
          "score >= 0.9 | null score |\n|---|---|---|---|---|")  # fmt: skip
    for v in ("prev", "new", "absent", *SHUFFLES):
        hs = [h for i in free for h in views[i][v]["hyps"]]
        confident[v] = sum(1 for h in hs if h["score"] is not None and h["score"] >= 0.9)
        print(f"| {v} | {sum(bool(views[i][v]['hyps']) for i in free)} | {len(hs)} | "
              f"{confident[v]} | {sum(1 for h in hs if h['score'] is None)} |")  # fmt: skip
    print("\n| fault-free window that gains candidates | first candidate | candidates |")
    print("|---|---|---|")
    for i in sorted(set(gained) & set(free)):
        hyps = views[i]["new"]["hyps"]
        print(f"| {i} | {family_of_id(hyps[0]['id'])} | {len(hyps)} |")
    return confident


def by_family(views: Views, windows: Views, faulty: list[str], gained: list[str]) -> None:
    """Accuracy by injected family and the first candidate of each gaining window."""
    groups: dict[str, list[str]] = defaultdict(list)
    for i in faulty:
        one = len(windows[i]["components"]) == 1
        groups[next(iter(injected(windows[i])[0])) if one else "several components"].append(i)
    print("\n## by injected family\n| injected | windows | no hypothesis before | gain a candidate "
          "| family top-1 before | after | exact top-1 before | after |")  # fmt: skip
    print("|---|---|---|---|---|---|---|---|")
    for g, ws in sorted(groups.items()):
        nb = sum(not views[i]["prev"]["hyps"] for i in ws)
        ga = sum(1 for i in ws if i in set(gained))
        rates = [sum(hits(views[i][v]["hyps"], windows[i], 1)[w] for i in ws) / len(ws)
                 for w, v in ((0, "prev"), (0, "new"), (1, "prev"), (1, "new"))]  # fmt: skip
        print(f"| {g} | {len(ws)} | {nb} | {ga} | " + " | ".join(f"{r:.3f}" for r in rates) + " |")
    counts: Counter[tuple[str, str]] = Counter()
    for i in gained:
        inj = ", ".join(sorted(injected(windows[i])[0])) or "fault-free"
        counts[(family_of_id(views[i]["new"]["hyps"][0]["id"]), inj)] += 1
    print("\n| first candidate | injected | windows |\n|---|---|---|")
    for (k, inj), m in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"| {k} | {inj} | {m} |")
    sizes = Counter(len(views[i]["new"]["hyps"]) for i in gained)
    print("candidates per gaining window:", dict(sorted(sizes.items())))


def split_report(prev_file: str, new_file: str) -> None:
    """Measures, controls and the stop rule on the validation split."""
    prev, new = load(prev_file), load(new_file)
    ids = sorted(prev)
    if sorted(new) != ids:
        raise SystemExit("the two score files hold different windows")
    windows = {i: new[i]["window"] for i in ids}
    views = {i: {**prev[i]["variants"], **new[i]["variants"]} for i in ids}
    faulty = [i for i in ids if windows[i]["components"]]
    free = [i for i in ids if not windows[i]["components"]]
    episodes = len({windows[i]["episode_id"] for i in ids})
    print(f"windows {len(ids)}, faulty {len(faulty)}, fault-free {len(free)}, episodes {episodes}")
    gained = identity(views, windows, ids)
    coverage = measures(views, windows, faulty)
    diffs = differences(views, windows, faulty)
    confident = fault_free(views, free, gained)
    by_family(views, windows, faulty, gained)
    point, lo, hi = diffs[("new", "family top-1")]
    best = max(diffs[(s, "family top-1")][0] for s in SHUFFLES)
    rule = (coverage["new"] > coverage["prev"], lo > 0, confident["new"] <= confident["prev"],
            point > best)  # fmt: skip
    print("\n## stop rule")
    print(f"(a) coverage {coverage['prev']} -> {coverage['new']}: {rule[0]}")
    print(f"(b) family top-1 {point:+.3f} ({lo:+.3f} to {hi:+.3f}), lower bound above 0: {rule[1]}")
    print(f"(c) fault-free score >= 0.9: {confident['prev']} -> {confident['new']}: {rule[2]}")
    print(f"(d) gain {point:+.3f} above the largest shuffle gain {best:+.3f}: {rule[3]}")
    print("outcome:", "adopt" if all(rule) else "remove")


def hypotheses(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """The Agent 5 hypotheses of a stored bundle."""
    found: list[dict[str, Any]] = (bundle["reports"][ROLES[5]].get("result") or {}).get(
        "hypotheses", []
    )
    return found


def decision(bundle: dict[str, Any]) -> str:
    """The Agent 8 decision state of a stored bundle."""
    return str((bundle["reports"][ROLES[8]].get("result") or {}).get("decision_state"))


def sample_report(before_dir: str, after_dir: str) -> None:
    """Changes of Agents 5, 6 and 8 between two stored runs of the 181-window sample."""
    before, after = Path(before_dir) / "bundles", Path(after_dir) / "bundles"
    ids = sorted(p.name for p in before.glob("*.json.gz"))
    if ids != sorted(p.name for p in after.glob("*.json.gz")):
        raise SystemExit("the two runs hold different windows")
    changed: Counter[int] = Counter()
    statuses: Counter[tuple[str, str]] = Counter()
    decisions: Counter[tuple[str, str]] = Counter()
    named, options, escalated = [0, 0], [0, 0], []
    for name in ids:
        b, a = load(before / name), load(after / name)
        for n, role in ROLES.items():
            changed[n] += json.dumps(b["reports"][role], sort_keys=True) != json.dumps(
                a["reports"][role], sort_keys=True
            )
        rb, ra = b["reports"][ROLES[6]], a["reports"][ROLES[6]]
        statuses[(rb["status"], ra["status"])] += 1
        decisions[(decision(b), decision(a))] += 1
        for k, bundle in enumerate((b, a)):
            options[k] += len((bundle["reports"][ROLES[6]].get("result") or {}).get("options", []))
            comps = [c for h in hypotheses(bundle) for c in h["components"]]
            named[k] += any(c.get("asset_id") or c.get("tag_id") for c in comps)
        w = a["window"]
        if not w.get("fault") and decision(b) != decision(a):
            escalated.append(f"{w['window_id']} ({w['set']}, {decision(b)} -> {decision(a)})")
    print(f"windows {len(ids)}")
    for n in ROLES:
        print(f"| Agent {n} report changed | {changed[n]} of {len(ids)} |")
    print("fault-free windows whose Agent 8 decision changes:", "; ".join(escalated) or "none")
    print("windows whose hypotheses name an asset or tag, before and after:", named)
    print("Agent 6 options in all windows, before and after:", options)
    print("\n| Agent 6 status before | after | windows |\n|---|---|---|")
    for (x, y), m in sorted(statuses.items()):
        print(f"| {x} | {y} | {m} |")
    print("\n| Agent 8 decision before | after | windows |\n|---|---|---|")
    for (x, y), m in sorted(decisions.items()):
        print(f"| {x} | {y} | {m} |")


def main() -> None:
    """Command line: split PREV NEW, or sample BEFORE AFTER."""
    if len(sys.argv) != 4 or sys.argv[1] not in ("split", "sample"):
        raise SystemExit("usage: report_agent5_candidates.py split PREV NEW | sample BEFORE AFTER")
    (split_report if sys.argv[1] == "split" else sample_report)(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
