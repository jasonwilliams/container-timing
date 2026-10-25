#!/usr/bin/env python3
"""Summarise results/*.jsonl into per-browser tables and summary.json.

  ./summarize.py                     # latest file per browser
  ./summarize.py results/foo.jsonl   # specific files

Deltas compare medians of per-run values. p is a two-sided permutation test:
shuffle the runs between the two configs and count how often the gap in
medians is at least as large as the one observed.
"""
import glob
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def stats(v):
    v = [x for x in v if x is not None]
    if not v:
        return None
    return {"median": st.median(v), "p25": pct(v, .25), "p75": pct(v, .75), "n": len(v)}


def permutation_p(a, b, shuffles=20000):
    observed = abs(st.median(b) - st.median(a))
    pool, k = a + b, len(a)
    rng = random.Random(1)  # fixed seed so reruns print the same p
    hits = 0
    for _ in range(shuffles):
        rng.shuffle(pool)
        if abs(st.median(pool[k:]) - st.median(pool[:k])) >= observed:
            hits += 1
    return hits / shuffles


def per_run(r):
    m = {
        "domContentLoaded": r["load"]["domContentLoaded"],
        "fcp": r["load"]["fcp"],
        "firstRenderAfterLoad": r["load"]["firstRenderAfterLoadMs"],
        "ctEntries": (r.get("ctTotal") or r["ctAfterLoad"])["count"],
    }
    if "dynamic" in r:
        f = r["dynamic"]["frames"]
        render = [x["renderMs"] for x in f]
        intervals = [x["intervalMs"] for x in f if x["intervalMs"] is not None]
        m.update(
            frameRenderMedian=st.median(render),
            frameRenderP95=pct(render, .95),
            frameInterval=st.mean(intervals),
            loopTotal=r["dynamic"]["totalMs"],
        )
    return m


def main():
    files = sys.argv[1:]
    if not files:
        latest = {}
        for f in sorted(glob.glob(str(HERE / "results/*.jsonl"))):
            latest[Path(f).name.split("-")[0]] = f
        files = list(latest.values())

    summary = {}
    for f in files:
        runs = [json.loads(l) for l in open(f)]
        browser = runs[0]["browser"]
        by_cfg = defaultdict(list)
        for r in runs:
            by_cfg[r["config"]].append(per_run(r))
        cfg_stats = {cfg: {k: stats([m.get(k) for m in ms]) for k in ms[0]}
                     for cfg, ms in sorted(by_cfg.items())}
        summary[browser] = {"file": Path(f).name, "ua": runs[0]["ua"], "configs": cfg_stats}

        print(f"\n== {browser}  ({Path(f).name})\n{runs[0]['ua']}")
        metrics = sorted({k for c in cfg_stats.values() for k, v in c.items() if v})
        print(f"{'metric':22s}" + "".join(f"{c:>18s}" for c in cfg_stats))
        for k in metrics:
            row = ""
            for c in cfg_stats.values():
                s = c.get(k)
                row += f"{s['median']:9.1f} ±{(s['p75'] - s['p25']) / 2:6.1f}  " if s else f"{'-':>18s}"
            print(f"{k:22s}{row}")

        def delta(base, test, k):
            b, t = cfg_stats.get(base, {}).get(k), cfg_stats.get(test, {}).get(k)
            if b and t:
                d = t["median"] - b["median"]
                p = permutation_p([m[k] for m in by_cfg[base] if m.get(k) is not None],
                                  [m[k] for m in by_cfg[test] if m.get(k) is not None])
                summary[browser].setdefault("deltas", {})[f"{test}-{base}:{k}"] = {"ms": d, "p": p}
                print(f"  {test} vs {base} {k:22s} {d:+8.2f} ms ({100 * d / b['median']:+.1f}%)  p={p:.3f}")

        print("deltas (median, p < 0.05 = significant):")
        for k in ("domContentLoaded", "fcp", "firstRenderAfterLoad"):
            delta("A", "B", k)
            delta("A", "C", k)
        for k in ("frameRenderMedian", "frameRenderP95", "frameInterval", "loopTotal"):
            delta("D0", "D1", k)
            delta("D0", "D2", k)

    (HERE / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\nwrote summary.json")


if __name__ == "__main__":
    main()
