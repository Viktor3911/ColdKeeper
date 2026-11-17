import { useEffect, useId, useRef, type ReactNode } from "react";

import { ApiError } from "../api/client";
import type { PointStatus } from "../api/types";
import { STATUS_LABELS } from "../format";
import styles from "./ui.module.css";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

const ICON_PATHS: Record<PointStatus, string> = {
  normal: "M3 8.5l3 3 7-7",
  pending: "M8 4v4l3 2M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z",
  alarm: "M8 2L1.5 13.5h13L8 2zM8 6.5v3.5M8 11.8v.2",
  sensor_error: "M4 4l8 8M12 4l-8 8",
  offline: "M2 6.5a9 9 0 0 1 12 0M4.5 9a5.5 5.5 0 0 1 7 0M8 12.5v.2M2 2l12 12",
  no_data: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z",
};

/** Status as text and an icon — never only a color. */
export function StatusBadge({ status, label }: { status: PointStatus; label?: string }) {
  return (
    <span className={cx(styles.badge, styles[status])}>
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d={ICON_PATHS[status]} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      {label ?? STATUS_LABELS[status]}
    </span>
  );
}

export function DemoBadge({ title = "Симулированные данные или демо-настройки" }: { title?: string }) {
  return (
    <span className={cx(styles.badge, styles.demo)} title={title}>
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M5 2h6M6 2v4L2.5 13h11L10 6V2" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
      Демо
    </span>
  );
}

export function Loading({ what = "данные" }: { what?: string }) {
  return (
    <div className={styles.state} role="status">
      Загружаем {what}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className={styles.state}>{children}</div>;
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Не удалось загрузить данные.";
  return (
    <div className={cx(styles.state, styles.stateError)} role="alert">
      <p>{message}</p>
      {retry && (
        <button type="button" className="secondary" onClick={retry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Не удалось сохранить. Повторите попытку.";
  return (
    <div className={styles.formError} role="alert">
      {message}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx(styles.card, className)}>{children}</section>;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className={styles.field}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <span className={styles.hint}>{hint}</span>}
    </div>
  );
}

export function FormGrid({ children }: { children: ReactNode }) {
  return <div className={styles.formGrid}>{children}</div>;
}

export function Actions({ children }: { children: ReactNode }) {
  return <div className={styles.actions}>{children}</div>;
}

export function Secret({ children }: { children: ReactNode }) {
  return <code className={styles.secret}>{children}</code>;
}

export function TableWrap({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className={styles.tableWrap} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <span className={styles.hint}>{children}</span>;
}

/** Native <dialog>: focus trap, Esc and backdrop come from the browser. */
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
  const closingByProps = useRef(false);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) {
      // The native "close" event also fires for this programmatic close; it must not reach onClose,
      // otherwise switching from one dialog to the next would immediately close the next one.
      closingByProps.current = true;
      dialog.close();
    }
  }, [open]);
  function handleClose() {
    if (closingByProps.current) {
      closingByProps.current = false;
      return;
    }
    onClose();
  }
  return (
    <dialog ref={ref} className={styles.dialog} aria-labelledby={titleId} onClose={handleClose}>
      {open && (
        <div className={styles.dialogBody}>
          <div className={styles.dialogTitle}>
            <h2 id={titleId}>{title}</h2>
            <button type="button" className={styles.close} onClick={onClose} aria-label="Закрыть">
              ×
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
