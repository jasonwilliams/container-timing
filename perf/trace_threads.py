#!/usr/bin/env python3
"""Per-thread busy time during the dynamic loop, from Chrome startup traces.

Sums top-level task durations (category "toplevel") on every thread between
the ct-loop-start and ct-loop-end user-timing marks, then compares configs.

  ./trace_threads.py results/traces/<dir>
"""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

# Top-level task events; nested ones are skipped to avoid double counting.
TASKS = {"ThreadControllerImpl::RunTask", "ThreadPool_RunTask", "RunTask"}


def busy_by_thread(path):
    data = json.load(open(path))
    events = data["traceEvents"] if isinstance(data, dict) else data
    pnames, tnames = {}, {}
    marks = {}
    for e in events:
        if e.get("ph") == "M" and e["name"] == "process_name":
            pnames[e["pid"]] = e["args"]["name"]
        elif e.get("ph") == "M" and e["name"] == "thread_name":
            tnames[(e["pid"], e["tid"])] = e["args"]["name"]
        elif e.get("name") in ("ct-loop-start", "ct-loop-end"):
            marks[e["name"]] = e["ts"]
    if len(marks) != 2:
        raise SystemExit(f"{path}: loop marks missing ({marks})")
    start, end = marks["ct-loop-start"], marks["ct-loop-end"]

    busy = defaultdict(float)
    for e in events:
        if e.get("ph") != "X" or e.get("name") not in TASKS:
            continue
        a, b = max(e["ts"], start), min(e["ts"] + e.get("dur", 0), end)
        if b > a:
            pname = pnames.get(e["pid"], "?").split(" ")[0]
            tname = tnames.get((e["pid"], e["tid"]), "?")
            # Pool workers get numbered names; group them.
            tname = tname.rstrip("0123456789").rstrip("/_ ")
            busy[f"{pname}/{tname}"] += (b - a) / 1000
    return busy, (end - start) / 1000


def main():
    by_cfg = defaultdict(list)
    for f in sorted(Path(sys.argv[1]).glob("*-run*.json")):
        by_cfg[f.name.split("-")[0]].append(busy_by_thread(f))

    cfgs = sorted(by_cfg)
    threads = sorted({t for runs in by_cfg.values() for b, _ in runs for t in b},
                     key=lambda t: -st.median(b.get(t, 0) for b, _ in by_cfg[cfgs[0]]))
    print(f"{'thread (busy ms during loop, median)':42s}" + "".join(f"{c:>10s}" for c in cfgs)
          + ("      delta" if len(cfgs) == 2 else ""))
    for t in threads:
        meds = [st.median(b.get(t, 0) for b, _ in by_cfg[c]) for c in cfgs]
        if max(meds) < 5:
            continue
        row = f"{t:42s}" + "".join(f"{m:10.1f}" for m in meds)
        if len(meds) == 2:
            row += f"  {meds[1] - meds[0]:+8.1f} ({100 * (meds[1] - meds[0]) / meds[0]:+.1f}%)"
        print(row)
    print(f"{'loop wall time':42s}" + "".join(
        f"{st.median(w for _, w in by_cfg[c]):10.1f}" for c in cfgs))
    print("runs:", {c: len(v) for c, v in by_cfg.items()})


if __name__ == "__main__":
    main()
