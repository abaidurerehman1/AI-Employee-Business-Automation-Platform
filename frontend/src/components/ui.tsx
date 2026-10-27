import {
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";

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
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="ui-dialog"
      onCancel={onClose}
      onClose={onClose}
      aria-labelledby="dialog-title"
    >
      <div className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <Button
          variant="secondary"
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          ✕
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
    <div className="table-scroll">
      <table aria-label={label}>{children}</table>
    </div>
  );
}
