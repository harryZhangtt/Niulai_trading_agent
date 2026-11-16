import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Notice } from '../../components';
interface Props { children: ReactNode } interface State { failed: boolean }
export default class InformationYieldBoundary extends Component<Props, State> {
  state: State = { failed: false };
  static getDerivedStateFromError(): State { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Deliberately avoid rendering exception content. */ }
  render() { return this.state.failed ? <Notice kind="error" title="Information-yield panel unavailable"><p>The rest of the research workspace remains available. Refresh after the local evidence contract is repaired.</p></Notice> : this.props.children; }
}
