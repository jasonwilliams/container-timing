# Container Timing performance benchmark

Measures what Container Timing costs a browser: page load, and the
main-thread cost of each frame while a large container keeps gaining new
content. Each browser is compared against itself with the feature turned off,
never against another browser.

The test page (`stress-source.html`) is a stress page from Bas (Mozilla): one
container root (`<div id="ct" containertiming="stress-root">`) holding about
35,000 elements, made up of wide flat lists, a 500-deep nest of divs, a grid,
and a block of 4,000 spans at the top.

## Requirements

- Python 3.9+ (standard library only).
- At least one browser with Container Timing:
  - **Chrome / Chromium**: Canary works as is. The script passes
    `--enable-blink-features=ContainerTiming` or `--disable-blink-features=ContainerTiming`.
  - **Firefox**: a Nightly or local build. Use an optimised build. Debug builds are far
    too slow to measure. A `mozconfig` like this works:
    ```
    ac_add_options --enable-optimize
    ac_add_options --disable-debug
    mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-opt
    ```
    The script toggles the `dom.enable_container_timing` pref.
  - **Servo**: a release build (`./mach build --release`). The script passes
    `--pref=container_timing_enabled=true|false`.

## Running

```sh
cd perf
./generate.py                  # builds pages/ from stress-source.html
./run.py chrome                # 15 runs of every config (~15 min)
./run.py firefox --binary ~/firefox/obj-opt/dist/bin/firefox --label nightly
./run.py servo --binary ~/servo/target/release/servoshell
./summarize.py                 # tables for the latest results file per browser
```

`run.py` opens a real browser window for every run. Leave the machine alone
while it runs, with nothing else busy, and on mains power. Keep the browser
window visible: if it is covered or on another workspace, the browser may
stop producing frames (on Wayland it gets none at all), and the changing-page
configs time out.

Results go to `results/<browser>[-label]-<timestamp>.jsonl`, one JSON line per
run. `summarize.py` prints a table per browser, the change versus flag off and
a p-value, and writes `summary.json`. Pass result files to compare specific
runs: `./summarize.py results/a.jsonl results/b.jsonl`.

Useful `run.py` options:

| Option            |                                                                                                                  |
| ----------------- | ---------------------------------------------------------------------------------------------------------------- |
| `--binary PATH`   | Browser to run. Defaults to `google-chrome-canary`, `firefox` or `servoshell` on `PATH`.                         |
| `--runs N`        | Measured rounds (default 15). Each round runs every config once, interleaved, so drift affects them all equally. |
| `--warmup N`      | Rounds to run and discard first (default 1).                                                                     |
| `--configs A,C`   | Run only some configs.                                                                                           |
| `--label NAME`    | Added to the results file name, e.g. a build or commit.                                                          |
| `--extra-arg ARG` | Extra browser argument (repeatable).                                                                             |

## Configs

| Config | Page                                        | Feature | What it shows                                        |
| ------ | ------------------------------------------- | ------- | ---------------------------------------------------- |
| A      | static                                      | off     | Baseline                                             |
| B      | static, `containertiming` attribute removed | on      | Cost of turning the feature on with nothing to track |
| C      | static                                      | on      | Load cost of tracking the 35k-element container      |
| D0     | changing                                    | off     | Baseline for the changing page                       |
| D1     | changing, attribute removed                 | on      | Per-frame cost of the feature with nothing to track  |
| D2     | changing                                    | on      | Per-frame cost of tracking the container             |

On the changing page, every frame for 150 frames adds 40 spans: 20 next to
elements on screen and 20 more than two viewport heights down. A seeded random
number generator picks the same places in every browser.

## How it measures

`measure.js` is injected into every page. It does not touch the page while
measuring: the container observer only counts entries.

**Per-frame cost.** Inside each `requestAnimationFrame` callback the page
inserts the spans, then posts a message to itself through a `MessageChannel`.
The message is a new task, so it can't run until the browser has finished
that frame's rendering work (style, layout, paint). The time from the end of
the insertions to the message arriving is that frame's main-thread rendering
cost. Each run reports the median and 95th percentile of its 150 frames.

**Page load.** DOMContentLoaded and first contentful paint come from the
Navigation and Paint Timing APIs. "First frame after load" uses the same
rAF and MessageChannel technique once, after the `load` event.

**Significance.** `summarize.py` compares the medians of the per-run values
with a permutation test (20,000 shuffles). p < 0.05 counts as a real
difference.

## Caveats

- **Main thread only.** Work done on other threads (raster, compositor, GPU)
  isn't counted. For Chrome, `--trace` records a trace that covers every thread
  (see below).
- **Compare a browser with itself.** Window size, engine and scheduling
  differ, so absolute times can't be compared across browsers.
- **"First frame after load" measures different work in each browser.** It
  depends on how much rendering a browser has already done by the time `load`
  fires:
  - **Chromium** lays the page out while `measure.js` first runs, because reading
    `innerWidth` forces a synchronous layout. The frame then contains pre-paint
    and paint.
  - **Firefox** has already painted before `load`, so the frame is a small
    follow-up.
  - **Servo** does its whole first layout synchronously as soon as the HTML has
    loaded, before DOMContentLoaded, so the frame has no work left and reads
    about 0.1 ms.

  Use DOMContentLoaded and FCP to compare load cost.

- Firefox `privacy.reduceTimerPrecision` is turned off for these runs so
  `performance.now()` has full resolution.

## Digging deeper

**Chrome trace.** `./run.py chrome --trace --configs D0,D2 --runs 5` saves a
startup trace per run into `results/traces/`.
`./trace_threads.py results/traces/<dir>` then adds up how busy every thread
was during the changing-page loop, per config.

**Firefox profile.** `./run.py firefox --profile --configs D2 --runs 3 --binary ...`
saves a Gecko profile per run into `results/profiles/` (the page closes its own
window so Firefox shuts down cleanly and writes the profile).
`./profile_ct.py results/profiles/<dir>/*.json` reports what share of
main-thread time was spent in container timing code, and what that code called
and was called from. Profiles can also be opened at
[profiler.firefox.com](https://profiler.firefox.com).

## Files

| File                 |                                                                               |
| -------------------- | ----------------------------------------------------------------------------- |
| `stress-source.html` | The original stress page.                                                     |
| `generate.py`        | Removes the page's own HUD and script, injects `measure.js`, writes `pages/`. |
| `measure.js`         | In-page measurement; POSTs results back to `run.py`.                          |
| `run.py`             | Serves `pages/`, launches the browser per run, collects results.              |
| `summarize.py`       | Per-config medians, deltas and p-values.                                      |
| `trace_threads.py`   | Per-thread busy time from Chrome traces.                                      |
| `profile_ct.py`      | Container timing breakdown from a Firefox profile.                            |

`pages/`, `results/` and `summary.json` are generated and gitignored.
