import {
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
  useEffect,
  useState,
} from "react";
import { api, type Session } from "./api/client";
import { ApplicationShell } from "./components/ApplicationShell";

function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
function usePath() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return path;
}
function Brand() {
  return (
    <button className="brand" onClick={() => navigate("/")} type="button">
      <span className="brand-mark">A</span>
      <span>AI Employee</span>
    </button>
  );
}
function AuthShell({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <aside className="auth-story">
        <Brand />
        <div>
          <p className="eyebrow">One platform. Your entire team.</p>
          <h1>Build a workforce that never stops moving.</h1>
          <p>
            Secure access for every person and every AI employee in your
            organization.
          </p>
        </div>
        <p className="story-foot">Phase 2 · Identity & access</p>
      </aside>
      <section className="auth-panel">
        <div className="auth-card">
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          {children}
        </div>
      </section>
    </main>
  );
}
function Field({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
function Status({ message, error }: { message?: string; error?: string }) {
  return message || error ? (
    <div className={`notice ${error ? "notice-error" : ""}`}>
      {error || message}
    </div>
  ) : null;
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      onLogin(
        await api.login(
          String(form.get("email")),
          String(form.get("password")),
        ),
      );
      navigate("/app");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthShell eyebrow="Welcome back" title="Sign in to your workspace">
      <form onSubmit={submit}>
        <Field
          label="Work email"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        <div className="form-row">
          <button
            className="text-button"
            type="button"
            onClick={() => navigate("/forgot-password")}
          >
            Forgot password?
          </button>
        </div>
        <Status error={error} />
        <button className="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="switch">
        New here?{" "}
        <button className="text-button" onClick={() => navigate("/register")}>
          Create an account
        </button>
        <br />
        <button
          className="text-button resend-link"
          onClick={() => navigate("/resend-verification")}
        >
          Resend verification email
        </button>
      </p>
    </AuthShell>
  );
}

function Register() {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const result = await api.register({
        full_name: String(form.get("name")),
        organization_name: String(form.get("organization")),
        email: String(form.get("email")),
        password: String(form.get("password")),
      });
      setMessage(result.message);
      formElement.reset();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to register");
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthShell eyebrow="Create workspace" title="Start building your AI team">
      <form onSubmit={submit}>
        <div className="field-grid">
          <Field label="Your name" name="name" required minLength={2} />
          <Field
            label="Organization"
            name="organization"
            required
            minLength={2}
          />
        </div>
        <Field label="Work email" name="email" type="email" required />
        <Field
          label="Password"
          name="password"
          type="password"
          required
          minLength={12}
          placeholder="12 characters minimum"
        />
        <Status message={message} error={error} />
        <button className="primary" disabled={busy}>
          {busy ? "Creating…" : "Create workspace"}
        </button>
      </form>
      <p className="switch">
        Already have an account?{" "}
        <button className="text-button" onClick={() => navigate("/login")}>
          Sign in
        </button>
      </p>
    </AuthShell>
  );
}

function TokenAction({ mode }: { mode: "verify" | "reset" }) {
  const [message, setMessage] = useState(
    mode === "verify" ? "Verifying your email…" : "",
  );
  const [error, setError] = useState("");
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  useEffect(() => {
    if (mode === "verify")
      api
        .verifyEmail(token)
        .then((result) => setMessage(result.message))
        .catch((reason: Error) => setError(reason.message));
  }, [mode, token]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      setMessage(
        (
          await api.resetPassword(
            token,
            String(new FormData(event.currentTarget).get("password")),
          )
        ).message,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    }
  }
  return (
    <AuthShell
      eyebrow={mode === "verify" ? "Email verification" : "Secure recovery"}
      title={
        mode === "verify" ? "Confirming your account" : "Choose a new password"
      }
    >
      {mode === "reset" && (
        <form onSubmit={submit}>
          <Field
            label="New password"
            name="password"
            type="password"
            minLength={12}
            required
          />
          <button className="primary">Update password</button>
        </form>
      )}
      <Status message={message} error={error} />
      <p className="switch">
        <button className="text-button" onClick={() => navigate("/login")}>
          Return to sign in
        </button>
      </p>
    </AuthShell>
  );
}

function ForgotPassword() {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      setMessage(
        (
          await api.forgotPassword(
            String(new FormData(event.currentTarget).get("email")),
          )
        ).message,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    }
  }
  return (
    <AuthShell eyebrow="Account recovery" title="Reset your password">
      <p className="helper">
        Enter your account email and we’ll send a secure one-time link.
      </p>
      <form onSubmit={submit}>
        <Field label="Work email" name="email" type="email" required />
        <Status message={message} error={error} />
        <button className="primary">Send reset link</button>
      </form>
      <p className="switch">
        <button className="text-button" onClick={() => navigate("/login")}>
          Back to sign in
        </button>
      </p>
    </AuthShell>
  );
}

function ResendVerification() {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      setMessage(
        (
          await api.resendVerification(
            String(new FormData(event.currentTarget).get("email")),
          )
        ).message,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    }
  }
  return (
    <AuthShell
      eyebrow="Email verification"
      title="Send a new verification link"
    >
      <p className="helper">
        Enter the email address used to create your workspace.
      </p>
      <form onSubmit={submit}>
        <Field label="Work email" name="email" type="email" required />
        <Status message={message} error={error} />
        <button className="primary">Send verification link</button>
      </form>
      <p className="switch">
        <button className="text-button" onClick={() => navigate("/login")}>
          Back to sign in
        </button>
      </p>
    </AuthShell>
  );
}

function AcceptInvitation({ session }: { session: Session | null }) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  async function accept() {
    if (!session) return navigate("/login");
    try {
      setMessage((await api.acceptInvitation(session, token)).message);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to accept invitation",
      );
    }
  }
  return (
    <AuthShell
      eyebrow="Organization invitation"
      title="Join your new workspace"
    >
      <p className="helper">
        Accept this invitation to add the organization to your account.
      </p>
      <Status message={message} error={error} />
      <button className="primary" onClick={accept}>
        {session ? "Accept invitation" : "Sign in to continue"}
      </button>
    </AuthShell>
  );
}

function App() {
  const path = usePath();
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    api
      .session()
      .then(setSession)
      .catch(() => setSession(null))
      .finally(() => setChecking(false));
  }, []);
  if (checking)
    return (
      <div className="splash">
        <Brand />
        <span>Loading secure workspace…</span>
      </div>
    );
  if (path === "/register") return <Register />;
  if (path === "/forgot-password") return <ForgotPassword />;
  if (path === "/resend-verification") return <ResendVerification />;
  if (path === "/reset-password") return <TokenAction mode="reset" />;
  if (path === "/verify-email") return <TokenAction mode="verify" />;
  if (path === "/accept-invitation")
    return <AcceptInvitation session={session} />;
  if (path === "/app" && session)
    return (
      <ApplicationShell
        session={session}
        setSession={setSession}
        navigate={navigate}
      />
    );
  if (path === "/login" || !session) return <Login onLogin={setSession} />;
  return (
    <ApplicationShell
      session={session}
      setSession={setSession}
      navigate={navigate}
    />
  );
}
export default App;
