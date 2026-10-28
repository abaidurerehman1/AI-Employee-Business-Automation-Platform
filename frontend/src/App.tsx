import {
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, ApiError, type Session } from "./api/client";
import { ApplicationShell } from "./components/ApplicationShell";
import { Icon } from "./components/Icons";
import { PasswordField } from "./components/Identity";

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
      <span className="brand-mark">
        <Icon name="sparkles" className="brand-icon" />
      </span>
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
        <p className="story-foot">Your people. Your AI. One workspace.</p>
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
  if (props.type === "password")
    return <PasswordField label={label} {...props} />;
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
function Status({ message, error }: { message?: string; error?: string }) {
  return message || error ? (
    <div
      role={error ? "alert" : "status"}
      className={`notice ${error ? "notice-error" : ""}`}
    >
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
      const returnPath =
        new URLSearchParams(window.location.search).get("next") ??
        (window.location.pathname.startsWith("/app")
          ? window.location.pathname + window.location.search
          : null);
      navigate(
        returnPath?.startsWith("/accept-invitation?token=") ||
          returnPath?.startsWith("/app/") ||
          returnPath === "/app"
          ? returnPath
          : "/app",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthShell eyebrow="Welcome back" title="Sign in to your workspace">
      {new URLSearchParams(window.location.search).has("expired") && (
        <Status message="Your session expired. Sign in again." />
      )}
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
  const [busy, setBusy] = useState(false);
  const verification = useRef<{
    token: string;
    result: ReturnType<typeof api.verifyEmail>;
  } | null>(null);
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  useEffect(() => {
    if (mode !== "verify") return;
    if (verification.current?.token !== token)
      verification.current = { token, result: api.verifyEmail(token) };
    let active = true;
    verification.current.result
      .then((result) => {
        if (active) {
          setMessage(result.message);
          setError("");
        }
      })
      .catch((reason: Error) => {
        if (active) {
          setMessage("");
          setError(reason.message);
        }
      });
    return () => {
      active = false;
    };
  }, [mode, token]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
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
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthShell
      eyebrow={mode === "verify" ? "Email verification" : "Secure recovery"}
      title={
        mode === "verify" ? "Confirming your account" : "Choose a new password"
      }
    >
      {mode === "reset" && !message && (
        <form onSubmit={submit}>
          <Field
            label="New password"
            name="password"
            type="password"
            minLength={12}
            required
          />
          <button className="primary" disabled={busy}>
            {busy ? "Updating?" : "Update password"}
          </button>
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
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
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
    } finally {
      setBusy(false);
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
        <button className="primary" disabled={busy}>
          {busy ? "Sending?" : "Send reset link"}
        </button>
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
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
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
    } finally {
      setBusy(false);
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
        <button className="primary" disabled={busy}>
          {busy ? "Sending?" : "Send verification link"}
        </button>
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
  const [busy, setBusy] = useState(false);
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  async function accept() {
    if (!session) {
      const invitationPath = `/accept-invitation?token=${encodeURIComponent(token)}`;
      return navigate(`/login?next=${encodeURIComponent(invitationPath)}`);
    }
    setBusy(true);
    setError("");
    try {
      setMessage((await api.acceptInvitation(session, token)).message);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to accept invitation",
      );
    } finally {
      setBusy(false);
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
      {message ? (
        <button
          className="primary"
          onClick={() => window.location.assign("/app")}
        >
          Open workspace
        </button>
      ) : (
        <button className="primary" disabled={busy} onClick={accept}>
          {busy
            ? "Accepting?"
            : session
              ? "Accept invitation"
              : "Sign in to continue"}
        </button>
      )}
    </AuthShell>
  );
}

function App() {
  const path = usePath();
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  useEffect(() => {
    const expired = () => {
      setSession(null);
      navigate("/login?expired=1");
    };
    window.addEventListener("identity:expired", expired);
    const denied = () => navigate("/access-denied");
    window.addEventListener("identity:denied", denied);
    return () => {
      window.removeEventListener("identity:expired", expired);
      window.removeEventListener("identity:denied", denied);
    };
  }, []);
  useEffect(() => {
    api
      .session()
      .then(setSession)
      .catch((reason: Error) => {
        setSession(null);
        if (!(reason instanceof ApiError && reason.status === 401))
          setConnectionError(reason.message);
      })
      .finally(() => setChecking(false));
  }, []);
  if (checking)
    return (
      <div className="splash">
        <Brand />
        <span>Loading secure workspace…</span>
      </div>
    );
  if (connectionError)
    return (
      <AuthShell
        eyebrow="Connection unavailable"
        title="Unable to load your workspace"
      >
        <Status error={connectionError} />
        <button className="primary" onClick={() => window.location.reload()}>
          Retry connection
        </button>
      </AuthShell>
    );
  if (path === "/register") return <Register />;
  if (path === "/access-denied")
    return (
      <AuthShell eyebrow="Workspace security" title="Access denied">
        <p>
          Your current role does not allow this action. Ask your workspace
          administrator for access.
        </p>
        <button className="primary" onClick={() => navigate("/app")}>
          Return to workspace
        </button>
      </AuthShell>
    );
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
