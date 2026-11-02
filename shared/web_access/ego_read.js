// Authored against the documented v2 TaskSpace/Page API. Never run page-supplied JS.
const input = __HOST_INPUT__;
let task;
let result;
let cleaned = false;
try {
  task = await taskSpace(input.space, input.profile_id ? {profileId: input.profile_id} : {});
  const page = task.page("p1");
  await page.goto(input.url, {timeout: input.timeout_ms, waitUntil: "load"});
  const observed = await page.url();
  if (!input.allowed_origins.includes(new URL(observed).origin)) throw new Error("ORIGIN");
  const value = await page.snapshot({scope: "full_page", includeActionMarks: false});
  const text = typeof value === "string" ? value : JSON.stringify(value);
  result = {schema_version: 1, nonce: input.nonce, status: "observed", observed_url: observed,
    snapshot: text.slice(0, input.max_chars),
    truncated: text.length > input.max_chars};
  await task.finish({keep: []});
  cleaned = true;
} catch (_) {
  // Matching v2.2 guide: retain failed/user-controlled tasks for reconciliation;
  // do not call finish() after an error or retry in a new task space.
  result = {schema_version: 1, nonce: input.nonce, status: "blocked", code: "EGO_READ_FAILED"};
}
// Browser navigation can run site code/redirects. This is an observation adapter,
// not a network firewall or an adversarial sandbox around the external browser.
console.log(JSON.stringify({...result, cleanup_verified: cleaned}));
