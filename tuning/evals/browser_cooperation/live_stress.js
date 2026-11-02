// Explicit development harness, never an agent-callable production script.
// One owned blank page; no external site requests or user-profile inspection.
const input = __HOST_INPUT__;
const levels = [1, 2, 4, 8];
const observations = [];
let task;
try {
  task = await taskSpace(input.space);
  const page = task.page("p1");
  await page.goto("about:blank", {timeout: 10000, waitUntil: "load"});
  await page.evaluate(({marker}) => {
    document.title = "Owned browser load fixture";
    const heading = document.createElement("h1");
    heading.textContent = marker;
    const amount = document.createElement("p");
    amount.textContent = "Controlled amount: 12345.67 USD";
    document.body.replaceChildren(heading, amount);
  }, {marker: input.marker});
  for (const concurrency of levels) {
    const samples = [];
    let mismatches = 0;
    for (let wave = 0; wave < 8 / concurrency; wave++) {
      const results = await Promise.all(Array.from({length: concurrency}, async () => {
        const started = performance.now();
        const value = await page.snapshot({scope: "full_page", includeActionMarks: false});
        const text = typeof value === "string" ? value : JSON.stringify(value);
        return {duration_ms: performance.now() - started,
          valid: text.includes(input.marker) && text.includes("12345.67 USD")};
      }));
      for (const result of results) {
        samples.push(result.duration_ms);
        if (!result.valid) mismatches++;
      }
    }
    samples.sort((a,b) => a-b);
    observations.push({concurrency, calls: samples.length, mismatches,
      p50_ms: samples[Math.ceil(samples.length * .50)-1],
      p95_ms: samples[Math.ceil(samples.length * .95)-1]});
  }
  await task.finish({keep: []});
  console.log(JSON.stringify({schema_version:1, nonce:input.nonce, status:"completed",
    observations, external_site_requests:0, cleanup_verified:true}));
} catch (_) {
  // Retain the same task on an SDK/user-control error. No new-space retry.
  console.log(JSON.stringify({schema_version:1, nonce:input.nonce, status:"blocked",
    observations, code:"OWNED_FIXTURE_SDK_FAILED", cleanup_verified:false}));
}
