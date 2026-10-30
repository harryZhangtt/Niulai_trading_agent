import path from 'node:path';
const app = process.env.BENCH_APP;
const tools = process.env.UI_TOOL_ROOT;
const output = process.env.BENCH_OUTPUT;
if (!app || !tools || !output) throw new Error('BENCH_APP, UI_TOOL_ROOT and BENCH_OUTPUT are required absolute local paths');
export default {
  root: app,
  cacheDir: path.join(output, 'vite-cache'),
  resolve: { alias: [
    { find: /^react-dom\/client$/, replacement: path.join(tools, 'node_modules/react-dom/client.js') },
    { find: /^react-dom$/, replacement: path.join(tools, 'node_modules/react-dom/index.js') },
    { find: /^react\/jsx-runtime$/, replacement: path.join(tools, 'node_modules/react/jsx-runtime.js') },
    { find: /^react$/, replacement: path.join(tools, 'node_modules/react/index.js') },
  ] },
  server: { host: '127.0.0.1', port: Number(process.env.BENCH_PORT ?? 5193), strictPort: true, fs: { allow: [app, tools] } },
  build: { outDir: path.join(output, 'dist'), emptyOutDir: true },
};
