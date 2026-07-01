# Origin Trial for Container Timing API

This document describes the Chrome experimental feature enabling developers to monitor when annotated sections of the DOM are displayed on screen and have finished their initial paint. The Container Timing API is currently available in Chrome Canary and Beta (v145+) behind a flag.

## Key Resources

- **Chrome Status Page**: [Container Timing API](https://chromestatus.com/feature/5110962817073152)
- **Explainer**: [GitHub Repository](https://github.com/WICG/container-timing)
- **Specification**: [WICG Container Timing](https://wicg.github.io/container-timing/)
- **Issue Tracker**: [GitHub Issues](https://github.com/WICG/container-timing/issues)
- **Blog Post**: [Container Timing: Measuring Web Components Performance](https://blogs.igalia.com/dape/2026/02/10/container-timing-measuring-web-components-performance/)

## Implementation in Chrome v147+

Chrome v147 introduced support for the Container Timing API behind the experimental web platform features flag. The API allows developers to mark sections of the DOM with the `containertiming` attribute and receive performance entries when those sections are painted.

### Basic Usage

Mark a container element with the `containertiming` attribute and observe performance entries:

```html
<div containertiming="my-component">
  <header>...</header>
  <main>...</main>
  <footer>...</footer>
</div>

<script>
  const observer = new PerformanceObserver((list) => {
    let perfEntries = list.getEntries();
    perfEntries.forEach((entry) => {
      console.log("Container painted:", entry.identifier);
      console.log("First render:", entry.firstRenderTime);
      console.log("Latest paint:", entry.startTime);
      console.log("Painted area:", entry.size);
      console.log("Last painted element:", entry.lastPaintedElement);
    });
  });
  observer.observe({ entryTypes: ["container"] });
</script>
```

### Ignoring Parts of the Container

Use the `containertimingignore` attribute to exclude specific subtrees from tracking:

```html
<div containertiming="main-content">
  <main>...</main>
  <!-- This aside and its children will be ignored -->
  <aside containertimingignore>...</aside>
</div>
```

### PerformanceContainerTiming Properties

The API exposes the following properties via `PerformanceContainerTiming` entries:

- `entryType`: Always `"container"`
- `identifier`: The value of the element's `containertiming` attribute
- `startTime`: Timestamp of the latest container paint
- `firstRenderTime`: Timestamp of the first paint for this container
- `intersectionRect`: The bounding box of all paints accumulated within this container
- `size`: The size of the combined region painted so far
- `lastPaintedElement`: The last element that was painted
- `duration`: Always set to 0

## Feature Detection

Developers can check for Container Timing support using:

```javascript
if (PerformanceObserver.supportedEntryTypes.includes("container")) {
  // Container Timing is supported
  console.log("Container Timing API is available");
} else {
  console.log("Container Timing API is not supported");
}
```

You can also verify that the API constructor exists:

```javascript
if (typeof PerformanceContainerTiming !== "undefined") {
  console.log("PerformanceContainerTiming is available");
}
```

## Local Testing

To test the Container Timing API locally in Chrome:

1. **Enable Experimental Web Platform Features**:
   - Navigate to `chrome://flags/#enable-experimental-web-platform-features`
   - Set the flag to `Enabled`
   - Restart Chrome

2. **Alternative: Command Line Flag**:
   - Launch Chrome with: `--enable-blink-features=ContainerTiming`

3. **Verify Support**:
   - Open DevTools Console
   - Run: `PerformanceObserver.supportedEntryTypes`
   - Verify that `"container"` appears in the array

4. **Try the Examples**:
   - Clone the repository: `git clone https://github.com/WICG/container-timing.git`
   - Install dependencies: `npm install`
   - Start the examples server: `npm run start`
   - Open the provided examples in your browser

## Best Practices

1. **Set attributes early**: Add the `containertiming` attribute before the element is added to the document for complete tracking
2. **Use meaningful identifiers**: Choose descriptive names for the `containertiming` attribute to make analytics easier
3. **Strategic placement**: Apply `containertiming` to semantic sections that matter for your metrics (e.g., "hero-section", "product-grid", "checkout-form")
4. **Ignore irrelevant content**: Use `containertimingignore` on ads, analytics scripts, or decorative elements that shouldn't affect your component metrics

## Known Limitations

- Shadow DOM support is not included in the initial implementation (see [Non-Goals](./README.md#shadow-dom))
- Built-in composite elements (MathML, SVG) are not automatically registered as containers
- Setting `containertiming` retroactively (after painting has started) will only capture subsequent paint events

## Feedback and Issues

Please report issues or provide feedback:

- [GitHub Issues](https://github.com/WICG/container-timing/issues)
- [W3C Web Performance Working Group](https://www.w3.org/webperf/)
