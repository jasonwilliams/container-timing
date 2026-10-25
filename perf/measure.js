// Injected into every benchmark page. Collects load/paint metrics and, for
// the dynamic variant, per-frame rendering cost while the container keeps
// gaining new painted content. Results are POSTed to /result.
(() => {
  const FRAMES = 150;
  const INSERTS_VISIBLE = 20; // new elements per frame inside the viewport
  const INSERTS_OFFSCREEN = 20; // and below the fold

  const params = new URLSearchParams(location.search);
  const mode = document.documentElement.dataset.mode;
  const result = {
    id: params.get("id"),
    page: location.pathname,
    mode,
    ua: navigator.userAgent,
    ctInterface: "PerformanceContainerTiming" in window,
    ctEntryType: (PerformanceObserver.supportedEntryTypes || []).includes(
      "container",
    ),
    elements: document.getElementsByTagName("*").length,
    viewport: [innerWidth, innerHeight, devicePixelRatio],
  };

  // Count entries without touching the DOM.
  const ct = { count: 0, firstStart: null, lastStart: null, maxSize: 0 };
  const ctLog = []; // [startTime, size] per entry, for comparing emission behaviour
  if (result.ctEntryType) {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        ct.count++;
        ct.firstStart ??= e.startTime;
        ct.lastStart = e.startTime;
        ct.maxSize = Math.max(ct.maxSize, e.size);
        ctLog.push([e.startTime, e.size]);
      }
    }).observe({ type: "container", buffered: true });
  }

  // Resolves after the next rendering update (style/layout/paint) has run on
  // the main thread: rAF callback, then a task queued from inside it.
  const afterNextPaint = () =>
    new Promise((resolve) =>
      requestAnimationFrame((rafTime) => {
        const start = performance.now();
        const ch = new MessageChannel();
        ch.port1.onmessage = () =>
          resolve({ rafTime, start, end: performance.now() });
        ch.port2.postMessage(0);
      }),
    );
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Seeded PRNG so every browser performs identical mutations.
  let seed = 0x5eed;
  const rand = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const SYL = [
    "zim",
    "tiv",
    "ro",
    "lom",
    "vex",
    "bru",
    "qua",
    "syn",
    "fen",
    "tul",
    "ka",
    "web",
    "dra",
  ];
  const word = () =>
    SYL[(rand() * SYL.length) | 0] + SYL[(rand() * SYL.length) | 0];

  async function dynamic() {
    const root = document.getElementById("ct");
    const all = [...root.querySelectorAll("span, p, h3, div")];
    const visible = all.filter((el) => {
      const r = el.getBoundingClientRect();
      return r.bottom > 0 && r.top < innerHeight && r.width > 0;
    });
    const offscreen = all.filter(
      (el) => el.getBoundingClientRect().top > innerHeight * 2,
    );
    result.dynamic = {
      visibleTargets: visible.length,
      offscreenTargets: offscreen.length,
    };

    const insert = (pool) => {
      const ref = pool[(rand() * pool.length) | 0];
      const span = document.createElement("span");
      span.textContent = word() + " ";
      ref.parentNode.insertBefore(span, ref);
    };

    const frames = [];
    let prevRaf = null;
    performance.mark("ct-loop-start");
    const loopStart = performance.now();
    for (let i = 0; i < FRAMES; i++) {
      const f = await new Promise((resolve) =>
        requestAnimationFrame((rafTime) => {
          const start = performance.now();
          for (let j = 0; j < INSERTS_VISIBLE; j++) insert(visible);
          for (let j = 0; j < INSERTS_OFFSCREEN; j++) insert(offscreen);
          const mutated = performance.now();
          const ch = new MessageChannel();
          ch.port1.onmessage = () =>
            resolve({
              rafTime,
              mutateMs: mutated - start,
              renderMs: performance.now() - mutated,
            });
          ch.port2.postMessage(0);
        }),
      );
      f.intervalMs = prevRaf === null ? null : f.rafTime - prevRaf;
      prevRaf = f.rafTime;
      frames.push(f);
    }
    result.dynamic.totalMs = performance.now() - loopStart;
    performance.mark("ct-loop-end");
    result.dynamic.frames = frames.map(
      ({ mutateMs, renderMs, intervalMs }) => ({
        mutateMs,
        renderMs,
        intervalMs,
      }),
    );
  }

  async function run() {
    const afterLoad = await afterNextPaint();
    await sleep(0); // let the load event finish so loadEventEnd is set
    const nav = performance.getEntriesByType("navigation")[0];
    result.load = {
      domContentLoaded: nav?.domContentLoadedEventEnd ?? null,
      loadEventEnd: nav?.loadEventEnd ?? null,
      firstRenderAfterLoadMs: afterLoad.end - afterLoad.start,
      settledAt: afterLoad.end,
    };

    await sleep(1500); // let initial container entries and paint timing arrive
    const paint = Object.fromEntries(
      performance.getEntriesByType("paint").map((e) => [e.name, e.startTime]),
    );
    result.load.firstPaint = paint["first-paint"] ?? null;
    result.load.fcp = paint["first-contentful-paint"] ?? null;
    result.ctAfterLoad = { ...ct };

    if (mode === "dynamic") {
      await dynamic();
      await sleep(1000);
      result.ctTotal = { ...ct };
      result.ctLog = ctLog;
    }

    document.title = "DONE";
    await fetch("/result", { method: "POST", body: JSON.stringify(result) });
    // Profiling runs: closing the last window lets Firefox quit cleanly and
    // write its shutdown profile (needs dom.allow_scripts_to_close_windows).
    if (params.has("close")) window.close();
  }

  addEventListener("load", () =>
    run().catch((e) => {
      fetch("/result", {
        method: "POST",
        body: JSON.stringify({ id: result.id, error: String(e.stack || e) }),
      });
    }),
  );
})();
