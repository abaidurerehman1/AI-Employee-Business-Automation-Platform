import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type KnowledgeDocument, type Session } from "../api/client";
import { Button, State } from "./ui";

export function Knowledge({
  organizationId,
  session,
  canManage,
}: {
  organizationId: string;
  session: Session;
  canManage: boolean;
}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setDocuments(await api.documents(organizationId));
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to load documents",
      );
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useEffect(() => {
    void Promise.resolve().then(load);
    const interval = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(interval);
  }, [load]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.size) return;
    setBusy(true);
    setError("");
    try {
      await api.uploadDocument(organizationId, session, file);
      form.reset();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }
  async function remove(document: KnowledgeDocument) {
    if (
      !window.confirm(`Delete "${document.filename}" and its indexed contents?`)
    )
      return;
    setBusy(true);
    try {
      await api.deleteDocument(organizationId, session, document.id);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }
  async function retry(document: KnowledgeDocument) {
    setBusy(true);
    try {
      await api.retryDocument(organizationId, session, document.id);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retry failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="shell-card">
      <div className="card-heading">
        <h2>Knowledge documents</h2>
        <p>
          Upload approved company information for AI employees. PDF, DOCX or
          UTF-8 TXT, up to 10 MB.
        </p>
      </div>
      {canManage && (
        <form className="knowledge-upload" onSubmit={upload}>
          <label className="field">
            <span>Choose a document</span>
            <input type="file" name="file" accept=".pdf,.docx,.txt" required />
          </label>
          <Button disabled={busy}>
            {busy ? "Working…" : "Upload document"}
          </Button>
        </form>
      )}
      {error && <State error>{error}</State>}
      {loading ? (
        <State>Loading documents…</State>
      ) : documents.length === 0 ? (
        <State>
          No documents yet. Upload one to give your agents company knowledge.
        </State>
      ) : (
        <div className="agent-list">
          {documents.map((document) => (
            <article className="agent-card" key={document.id}>
              <div>
                <strong>{document.filename}</strong>
                <p>
                  {document.status === "ready"
                    ? `Ready · ${document.chunk_count} passages`
                    : document.status}
                </p>
                {document.error_message && (
                  <p role="alert">{document.error_message}</p>
                )}
              </div>
              {canManage && (
                <div className="agent-actions">
                  {document.status === "failed" && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => retry(document)}
                    >
                      Retry
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => remove(document)}
                  >
                    Delete
                  </Button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
