import { withPortal } from './client.mjs';

const [provider, name, args = '{}'] = process.argv.slice(2);
if (!provider || !name) {
  process.stderr.write('Usage: node shared/market_data_mcp/query.mjs PROVIDER TOOL [JSON_ARGUMENTS]\n');
  process.exitCode = 2;
} else {
  try {
    await withPortal(provider, async client => {
      const result = await client.callTool({ name, arguments: JSON.parse(args) }, undefined, { timeout: 75000 });
      process.stdout.write(`${JSON.stringify(result)}\n`);
      if (result.isError) process.exitCode = 1;
    });
  } catch {
    process.stderr.write('Portal client failed. Run tests and inspect portal_status; raw errors are suppressed.\n');
    process.exitCode = 1;
  }
}
