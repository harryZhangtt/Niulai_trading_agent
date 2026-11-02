import { start, identity, health } from './server.mjs';

const port = Number(process.env.DATASOURCE_PORT || 7270);
if (process.argv.includes('--status')) {
  const existing = await health(port); const expected = await identity();
  const ours = existing?.app === expected.app && existing.workspace_id === expected.workspace_id &&
    existing.server_fingerprint === expected.server_fingerprint;
  console.log(ours ? JSON.stringify({ app: expected.app, status: existing.status, port, read_only: true }) :
    'No matching datasource server is running. The port may be occupied or the server may need restarting.');
  process.exitCode = ours ? 0 : 1;
} else {
  let service;
  try {
    service = await start({ port });
    console.log(`Datasource ready at http://localhost:${port}/datasource (read-only). Ctrl+C stops this server.`);
    let stopping = false;
    const stop = async () => {
      if (stopping) return; stopping = true;
      const timeout = setTimeout(() => process.exit(1), 3000).unref();
      await service.close(); clearTimeout(timeout); process.exit(0);
    };
    process.on('SIGINT', stop); process.on('SIGTERM', stop);
  } catch (error) {
    if (error.code === 'EADDRINUSE') {
      const expected = await identity(); let existing;
      for (let attempt = 0; attempt < 20; attempt++) {
        existing = await health(port);
        if (!existing || existing.status !== 'starting') break;
        await new Promise(resolve => setTimeout(resolve, 150));
      }
      if (existing?.app === expected.app && existing.workspace_id === expected.workspace_id &&
          existing.server_fingerprint === expected.server_fingerprint && existing.status === 'ready') {
        console.log(`Datasource is already running at http://localhost:${port}/datasource; reused existing server.`);
      } else {
        console.error(`Port ${port} is occupied or an older datasource server is running. No process was stopped. Stop its owning terminal, then run pnpm run dev again.`);
        process.exitCode = 1;
      }
    } else {
      console.error('Datasource startup failed. Verify project-local dependencies (pnpm install) and the research Python environment. No unrelated process was stopped.');
      process.exitCode = 1;
    }
  }
}
