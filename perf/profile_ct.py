#!/usr/bin/env python3
"""Container timing cost breakdown from a Firefox shutdown profile.

Finds the content process that ran the benchmark page, keeps samples between
the ct-loop-start / ct-loop-end marks, and reports how much main-thread time
was spent under container timing code, what it called, and who called it.

  ./profile_ct.py results/profiles/<dir>/D2-run0.json [...]
"""
import json
import sys
from collections import Counter

CT = "ContainerTiming"


def table(t, name):
    tab = t[name]
    return tab["schema"], tab["data"]


def short(fn):
    # Drop argument lists so overloads/templates group together.
    depth, out = 0, []
    for ch in fn:
        if ch == "(":
            depth += 1
        if depth == 0:
            out.append(ch)
        if ch == ")":
            depth -= 1
    return "".join(out).replace(" (in libxul.so)", "").strip()


def loop_window(t, strings):
    schema, data = table(t, "markers")
    marks = {}
    for m in data:
        d = m[schema["data"]] if len(m) > schema["data"] else None
        if not isinstance(d, dict) or d.get("type") != "UserTiming":
            continue
        name = d.get("name")
        if name in ("ct-loop-start", "ct-loop-end"):
            marks[name] = m[schema["startTime"]]
    return marks.get("ct-loop-start"), marks.get("ct-loop-end")


def analyse(path):
    p = json.load(open(path))
    threads = [t for sp in p.get("processes", []) for t in sp["threads"]]
    page = next(t for t in threads if t.get("name") == "GeckoMain"
                and any(CT in s for s in t["stringTable"]))
    strings = page["stringTable"]
    start, end = loop_window(page, strings)

    fs, frames = table(page, "frameTable")
    ss, stacks = table(page, "stackTable")
    sms, samples = table(page, "samples")
    names = [short(strings[f[fs["location"]]]) for f in frames]

    def chain(stack):  # leaf first
        out = []
        while stack is not None:
            out.append(names[stacks[stack][ss["frame"]]])
            stack = stacks[stack][ss["prefix"]]
        return out

    total, in_ct = 0, 0
    callee, caller, entry = Counter(), Counter(), Counter()
    thirds = [[0, 0], [0, 0], [0, 0]]
    span = (end - start) if start is not None else None
    for s in samples:
        tm, st = s[sms["time"]], s[sms["stack"]]
        if start is not None and not (start <= tm <= end) or st is None:
            continue
        total += 1
        c = chain(st)
        idx = [i for i, n in enumerate(c) if CT in n]
        third = min(2, int(3 * (tm - start) / span)) if span else 0
        thirds[third][0] += 1
        if not idx:
            continue
        in_ct += 1
        thirds[third][1] += 1
        top = idx[-1]  # outermost container timing frame
        entry[c[top]] += 1
        caller[c[top + 1] if top + 1 < len(c) else "(root)"] += 1
        callee[c[idx[0] - 1] if idx[0] > 0 else "(self)"] += 1

    print(f"== {path}")
    print(f"loop window: {'%.0f' % span + ' ms' if span else 'whole profile (marks missing)'}, "
          f"page main-thread samples: {total}")
    print(f"under container timing: {in_ct} samples ({100 * in_ct / total:.1f}% of main-thread samples)")
    print("by loop third (CT share):", ", ".join(
        f"{100 * b / a:.1f}%" if a else "-" for a, b in thirds))
    for title, ctr in (("entry points", entry), ("called by", caller), ("time spent in (callee of innermost CT frame)", callee)):
        print(f"  {title}:")
        for n, k in ctr.most_common(8):
            print(f"    {100 * k / in_ct:5.1f}%  {n}")


if __name__ == "__main__":
    for f in sys.argv[1:]:
        analyse(f)
