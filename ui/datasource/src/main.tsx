import { Component, StrictMode, Suspense, lazy } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import './workspace-theme.css';
const App = lazy(() => import('./App'));
const Scheduler = lazy(() => import('./scheduler/SchedulerPage'));
const FactorMining = lazy(() => import('./factorMining/FactorMiningPage'));
const scheduler = window.location.pathname === '/scheduler' || window.location.pathname === '/scheduler/';
const factorMining = window.location.pathname === '/factor-mining' || window.location.pathname === '/factor-mining/';
const pageTitle = scheduler ? 'Scheduler' : factorMining ? 'Factor mining' : 'Research observability';
document.title = `${pageTitle} | Research operations`;

class ReadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Diagnostics intentionally exclude source payloads. */ }
  render() {
    return this.state.failed ? <main className="boundary-error" role="alert"><h1>{pageTitle} could not be displayed</h1><p>The current records have an unsupported shape. Reload to request a fresh snapshot.</p><button className="button button-primary" onClick={() => window.location.reload()}>Reload page</button></main> : this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(<StrictMode><ReadBoundary><Suspense fallback={<main role="status">Loading workspace…</main>}>{scheduler ? <Scheduler /> : factorMining ? <FactorMining /> : <App />}</Suspense></ReadBoundary></StrictMode>);
