#!/usr/bin/env python3
"""Run the container timing benchmark in one browser.

Each run launches the browser with a fresh profile, loads one page, waits for
measure.js to POST its results, then kills the browser. Configs are
interleaved run by run so drift (thermal, background load) hits all equally.

  ./run.py chrome --runs 15
  ./run.py firefox --binary <firefox>/obj-opt/dist/bin/firefox
  ./run.py servo --binary <servo>/target/release/servoshell

See README.md for setup and what each config measures.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
PAGES = HERE / "pages"
RESULTS = HERE / "results"
WIDTH, HEIGHT = 1280, 900

# name: (page, feature flag on?)
CONFIGS = {
    "A": ("static.html", False),         # baseline
    "B": ("static-noattr.html", True),   # flag on, nothing to track
    "C": ("static.html", True),          # flag on, 35k-element container
    "D0": ("dynamic.html", False),       # dynamic baseline
    "D1": ("dynamic-noattr.html", True),
    "D2": ("dynamic.html", True),
}

FIREFOX_PREFS = {
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "browser.aboutwelcome.enabled": False,
    "startup.homepage_welcome_url": "",
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.tabs.warnOnClose": False,
    "privacy.reduceTimerPrecision": False,  # full-resolution performance.now()
}


def chrome_cmd(binary, flag_on, profile, url):
    cmd = [binary or "google-chrome-canary",
           f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", "--disable-sync", "--disable-component-update",
           "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
           "--disable-backgrounding-occluded-windows",
           f"--window-size={WIDTH},{HEIGHT}", "--window-position=0,0"]
    # Pass a blink-features flag either way so both get the same infobar/viewport.
    cmd.append(f"--{'enable' if flag_on else 'disable'}-blink-features=ContainerTiming")
    return cmd + [url]


def firefox_cmd(binary, flag_on, profile, url):
    prefs = {**FIREFOX_PREFS, "dom.enable_container_timing": flag_on,
             "dom.allow_scripts_to_close_windows": True}
    (Path(profile) / "user.js").write_text("".join(
        f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()))
    return [binary or "firefox", "-no-remote", "-new-instance", "-profile", profile,
            "-width", str(WIDTH), "-height", str(HEIGHT), url]


def servo_cmd(binary, flag_on, profile, url):
    return [binary or "servoshell", f"--window-size={WIDTH}x{HEIGHT}",
            f"--pref=container_timing_enabled={'true' if flag_on else 'false'}", url]


BROWSERS = {"chrome": chrome_cmd, "firefox": firefox_cmd, "servo": servo_cmd}


class Collector:
    def __init__(self):
        self.lock = threading.Lock()
        self.results = {}
        self.events = {}

    def expect(self, run_id):
        with self.lock:
            self.events[run_id] = threading.Event()
        return self.events[run_id]

    def deliver(self, data):
        with self.lock:
            self.results[data.get("id")] = data
            ev = self.events.get(data.get("id"))
        if ev:
            ev.set()


def make_handler(collector):
    class Handler(SimpleHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            collector.deliver(json.loads(body))
            self.send_response(204)
            self.end_headers()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *args):
            pass

    return partial(Handler, directory=str(PAGES))


TRACE_CATEGORIES = "toplevel,blink.user_timing"
TRACE_SECONDS = 30


def wait_for_trace(path, started):
    # Chrome writes the trace once --trace-startup-duration has elapsed.
    deadline = started + TRACE_SECONDS + 20
    last = -1
    while time.time() < deadline:
        size = path.stat().st_size if path.exists() else -1
        if size > 0 and size == last:
            return
        last = size
        time.sleep(1)
    print(f"  trace not written: {path}", flush=True)


GECKO_PROFILER_ENV = {
    "MOZ_PROFILER_STARTUP": "1",
    "MOZ_PROFILER_STARTUP_FEATURES": "stackwalk,cpu",
    "MOZ_PROFILER_STARTUP_FILTERS": "GeckoMain",
    "MOZ_PROFILER_STARTUP_INTERVAL": "1",
    "MOZ_PROFILER_STARTUP_ENTRIES": "64000000",
    "MOZ_PROFILER_SYMBOLICATE": "1",
}


def quit_gracefully(proc, profile_file):
    # The page closes its own window (?close), so Firefox quits normally and
    # writes MOZ_PROFILER_SHUTDOWN after collecting the content processes'
    # profiles. SIGTERM is not handled gracefully, so just wait.
    try:
        proc.wait(300)  # pre-symbolication is slow
    except subprocess.TimeoutExpired:
        print("  firefox did not exit; killing it", flush=True)
    if not profile_file.exists():
        print(f"  profile not written: {profile_file}", flush=True)


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("browser", choices=BROWSERS)
    ap.add_argument("--binary")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=1, help="discarded rounds before measuring")
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--label", help="results file suffix, e.g. a build id")
    ap.add_argument("--extra-arg", action="append", default=[], help="extra browser arg")
    ap.add_argument("--trace", action="store_true",
                    help="chrome only: record a startup trace per run into results/traces/")
    ap.add_argument("--profile", action="store_true",
                    help="firefox only: record a Gecko profile per run into results/profiles/")
    args = ap.parse_args()

    configs = args.configs.split(",")
    collector = Collector()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(collector))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS / f"{args.browser}{'-' + args.label if args.label else ''}-{stamp}.jsonl"
    out = out_path.open("w")
    print(f"serving on :{port}, writing {out_path}")

    rounds = [("warmup", i) for i in range(args.warmup)] + [("run", i) for i in range(args.runs)]
    for kind, i in rounds:
        for cfg in configs:
            page, flag_on = CONFIGS[cfg]
            run_id = uuid.uuid4().hex
            url = f"http://127.0.0.1:{port}/{page}?id={run_id}" + ("&close" if args.profile else "")
            profile = tempfile.mkdtemp(prefix=f"ctbench-{args.browser}-")
            cmd = BROWSERS[args.browser](args.binary, flag_on, profile, url)
            cmd[1:1] = args.extra_arg
            trace_file = None
            if args.trace:
                trace_dir = RESULTS / "traces" / f"{args.label or args.browser}-{stamp}"
                trace_dir.mkdir(parents=True, exist_ok=True)
                trace_file = trace_dir / f"{cfg}-{kind}{i}.json"
                cmd[1:1] = [f"--trace-startup={TRACE_CATEGORIES}", f"--trace-startup-file={trace_file}",
                            f"--trace-startup-duration={TRACE_SECONDS}", "--trace-startup-format=json"]
            env = None
            profile_file = None
            if args.profile:
                profile_dir = RESULTS / "profiles" / f"{args.label or args.browser}-{stamp}"
                profile_dir.mkdir(parents=True, exist_ok=True)
                profile_file = profile_dir / f"{cfg}-{kind}{i}.json"
                env = {**os.environ, **GECKO_PROFILER_ENV, "MOZ_PROFILER_SHUTDOWN": str(profile_file)}
            ev = collector.expect(run_id)
            t0 = time.time()
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True, env=env)
            ok = ev.wait(args.timeout)
            if trace_file:
                wait_for_trace(trace_file, t0)
            if profile_file:
                quit_gracefully(proc, profile_file)
            kill(proc)
            shutil.rmtree(profile, ignore_errors=True)

            res = collector.results.get(run_id)
            status = "ok" if ok and "error" not in res else ("ERROR " + res["error"] if ok else "TIMEOUT")
            print(f"{kind} {i:2d} {cfg:3s} {time.time() - t0:5.1f}s {status}", flush=True)
            if ok and kind == "run":
                res.update(browser=args.browser, config=cfg, flag=flag_on, round=i)
                out.write(json.dumps(res) + "\n")
                out.flush()
            time.sleep(1)
    out.close()
    server.shutdown()
    print("done:", out_path)


if __name__ == "__main__":
    sys.exit(main())
