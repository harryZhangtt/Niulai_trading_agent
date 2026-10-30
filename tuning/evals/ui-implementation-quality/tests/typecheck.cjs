const fs = require('node:fs');
const path = require('node:path');
const toolRoot = process.env.UI_TOOL_ROOT;
const app = process.env.BENCH_APP;
if (!toolRoot || !app) throw new Error('Absolute UI_TOOL_ROOT and BENCH_APP required');
const ts = require(path.join(toolRoot, 'node_modules/typescript'));
function files(directory) { return fs.readdirSync(directory, { withFileTypes: true }).flatMap(item => item.isDirectory() ? files(path.join(directory, item.name)) : /\.tsx?$/.test(item.name) ? [path.join(directory, item.name)] : []); }
const program = ts.createProgram([...files(path.join(app, 'src')), ...files(path.join(app, 'vendor'))], {
  strict: true, noEmit: true, skipLibCheck: true, jsx: ts.JsxEmit.React,
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  esModuleInterop: true, lib: ['lib.es2022.d.ts', 'lib.dom.d.ts'],
  paths: { react: [path.join(toolRoot, 'node_modules/@types/react/index.d.ts')], 'react-dom/client': [path.join(toolRoot, 'node_modules/@types/react-dom/client.d.ts')] },
});
const diagnostics = ts.getPreEmitDiagnostics(program);
if (diagnostics.length) {
  process.stderr.write(ts.formatDiagnosticsWithColorAndContext(diagnostics, { getCurrentDirectory: () => app, getCanonicalFileName: value => value, getNewLine: () => '\n' }));
  process.exitCode = 1;
} else process.stdout.write('TypeScript validation passed.\n');
