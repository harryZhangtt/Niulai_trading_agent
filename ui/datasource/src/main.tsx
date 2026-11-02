import { Component, StrictMode } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

class ReadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Diagnostics intentionally exclude source payloads. */ }
  render() {
    return this.state.failed ? <main className="boundary-error" role="alert"><h1>Datasource could not be displayed</h1><p>The current records have an unsupported shape. Reload to request a fresh snapshot.</p><button className="button button-primary" onClick={() => window.location.reload()}>Reload datasource</button></main> : this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(<StrictMode><ReadBoundary><App /></ReadBoundary></StrictMode>);
