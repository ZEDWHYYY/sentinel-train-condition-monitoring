"use client";

import { Component, type ReactNode } from "react";

type Props = { label: string; children: ReactNode };
type State = { error: Error | null };

// Keeps a rendering failure inside one panel; it never hides a failed prediction as a completed result.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error(`[${this.props.label}]`, error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="card space-y-2 border-fault p-4">
        <p className="font-semibold text-fault">The {this.props.label} view could not be displayed.</p>
        <p className="text-sm muted">
          The stored results are unaffected and can still be downloaded. Details: {this.state.error.message}
        </p>
        <button className="btn btn-sm" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
