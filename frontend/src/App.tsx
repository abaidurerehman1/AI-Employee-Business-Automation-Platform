import { useEffect, useState } from 'react'
import { getHealth, type HealthResponse } from './api/client'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'success'; health: HealthResponse }
  | { kind: 'error'; message: string }

const labels: Array<[keyof Pick<HealthResponse, 'api' | 'database' | 'redis'>, string]> = [
  ['api', 'FastAPI'],
  ['database', 'PostgreSQL'],
  ['redis', 'Redis'],
]

function App() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    getHealth(controller.signal)
      .then((health) => setState({ kind: 'success', health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({
          kind: 'error',
          message: error instanceof Error ? error.message : 'Unable to reach the API',
        })
      })

    return () => controller.abort()
  }, [])

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">Foundation · Phase 1</p>
        <h1>Your AI workforce starts here.</h1>
        <p className="intro">
          The application foundation is online and ready for agents, campaigns, conversations,
          and business workflows.
        </p>

        <div className="status-card" aria-live="polite">
          <div className="status-heading">
            <div>
              <p className="section-label">System health</p>
              <h2>Infrastructure</h2>
            </div>
            <span className={`overall ${state.kind}`}>
              {state.kind === 'loading' && 'Checking'}
              {state.kind === 'success' && state.health.status}
              {state.kind === 'error' && 'Offline'}
            </span>
          </div>

          {state.kind === 'loading' && <p className="message">Connecting to the platform…</p>}
          {state.kind === 'error' && <p className="message error">{state.message}</p>}
          {state.kind === 'success' && (
            <div className="services">
              {labels.map(([key, label]) => (
                <div className="service" key={key}>
                  <span className={`dot ${state.health[key].status}`} />
                  <span>{label}</span>
                  <strong>{state.health[key].status}</strong>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </main>
  )
}

export default App

