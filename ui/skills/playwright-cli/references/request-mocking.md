# Request Mocking

Intercept, mock, modify, and block network requests.

## CLI Route Commands

```bash
# Mock with custom status
python3 ui/tools/run.py playwright-cli route "**/*.jpg" --status=404

# Mock with JSON body
python3 ui/tools/run.py playwright-cli route "**/api/users" --body='[{"id":1,"name":"Alice"}]' --content-type=application/json

# Mock with custom headers
python3 ui/tools/run.py playwright-cli route "**/api/data" --body='{"ok":true}' --header="X-Custom: value"

# Remove headers from requests
python3 ui/tools/run.py playwright-cli route "**/*" --remove-header=cookie,authorization

# List active routes
python3 ui/tools/run.py playwright-cli route-list

# Remove a route or all routes
python3 ui/tools/run.py playwright-cli unroute "**/*.jpg"
python3 ui/tools/run.py playwright-cli unroute
```

## URL Patterns

```
**/api/users           - Exact path match
**/api/*/details       - Wildcard in path
**/*.{png,jpg,jpeg}    - Match file extensions
**/search?q=*          - Match query parameters
```

## Advanced Mocking with run-code

For conditional responses, request body inspection, response modification, or delays:

### Conditional Response Based on Request

```bash
python3 ui/tools/run.py playwright-cli run-code "async page => {
  await page.route('**/api/login', route => {
    const body = route.request().postDataJSON();
    if (body.username === 'admin') {
      route.fulfill({ body: JSON.stringify({ token: 'mock-token' }) });
    } else {
      route.fulfill({ status: 401, body: JSON.stringify({ error: 'Invalid' }) });
    }
  });
}"
```

### Modify Real Response

```bash
python3 ui/tools/run.py playwright-cli run-code "async page => {
  await page.route('**/api/user', async route => {
    const response = await route.fetch();
    const json = await response.json();
    json.isPremium = true;
    await route.fulfill({ response, json });
  });
}"
```

### Simulate Network Failures

```bash
python3 ui/tools/run.py playwright-cli run-code "async page => {
  await page.route('**/api/offline', route => route.abort('internetdisconnected'));
}"
# Options: connectionrefused, timedout, connectionreset, internetdisconnected
```

### Delayed Response

```bash
python3 ui/tools/run.py playwright-cli run-code "async page => {
  await page.route('**/api/slow', async route => {
    await new Promise(r => setTimeout(r, 3000));
    route.fulfill({ body: JSON.stringify({ data: 'loaded' }) });
  });
}"
```
