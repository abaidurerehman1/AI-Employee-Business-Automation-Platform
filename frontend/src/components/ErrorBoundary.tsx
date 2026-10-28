import { Component, type ReactNode } from "react";
import { Icon } from "./Icons";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="app-recovery" role="alert">
        <span className="empty-icon">
          <Icon name="shield" />
        </span>
        <h1>Something interrupted your workspace</h1>
        <p>Reload the application to reconnect and continue.</p>
        <button
          className="ui-button ui-button-primary"
          onClick={() => window.location.reload()}
        >
          Reload application
        </button>
      </main>
    );
  }
}
