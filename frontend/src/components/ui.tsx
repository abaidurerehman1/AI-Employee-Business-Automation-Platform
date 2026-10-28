import {
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { Icon } from "./Icons";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary";
}) {
  return (
    <button
      className={`ui-button ui-button-${variant} ${className}`}
      {...props}
    />
  );
}

export function Dialog({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="ui-dialog"
      onCancel={onClose}
      onClose={onClose}
      aria-labelledby={titleId}
      aria-label={title}
    >
      <div className="dialog-heading">
        <h2 id={titleId}>{title}</h2>
        <Button
          variant="secondary"
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <Icon name="close" className="button-icon" />
        </Button>
      </div>
      {children}
    </dialog>
  );
}

export function State({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`panel-state${error ? " panel-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

export function Table({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label={`${label} scroll area`}
    >
      <table aria-label={label}>{children}</table>
    </div>
  );
}

export function Skeleton({ label = "Loading workspace…" }: { label?: string }) {
  return (
    <div className="loading-skeleton" role="status" aria-label={label}>
      <span className="sr-only">{label}</span>
      <div />
      <div />
      <div />
    </div>
  );
}
export function Badge({ children }: { children: ReactNode }) {
  return <span className="ui-badge">{children}</span>;
}
export function Pagination({
  page,
  total,
  pageSize = 20,
  onChange,
}: {
  page: number;
  total: number;
  pageSize?: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="ui-pagination">
      <span>
        {total} results · Page {page}
      </span>
      <Button
        variant="secondary"
        disabled={page === 1}
        onClick={() => onChange(page - 1)}
      >
        Previous
      </Button>
      <Button
        variant="secondary"
        disabled={page * pageSize >= total}
        onClick={() => onChange(page + 1)}
      >
        Next
      </Button>
    </div>
  );
}
export function Dropdown({
  label,
  trigger,
  children,
}: {
  label: string;
  trigger: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node) && ref.current)
        ref.current.open = false;
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  return (
    <details
      className="ui-dropdown"
      ref={ref}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && ref.current) {
          ref.current.open = false;
          ref.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary role="button" aria-label={label} aria-expanded={open}>
        {trigger}
      </summary>
      <div
        className="ui-dropdown-content"
        onClick={() => {
          if (ref.current) ref.current.open = false;
        }}
      >
        {children}
      </div>
    </details>
  );
}
