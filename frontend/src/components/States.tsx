import type { ReactNode } from "react";
import { apiErrorMessage } from "@/lib/api";

export function LoadingState({ label = "Caricamento…" }: { label?: string }) {
  return (
    <div className="glass flex items-center gap-3 rounded-2xl p-5 text-sm text-muted-foreground">
      <span className="size-2 animate-pulse rounded-full bg-brand" />
      {label}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  context,
}: {
  error: unknown;
  onRetry?: () => void;
  context?: string;
}) {
  return (
    <div className="glass rounded-2xl border-l-2 border-conflict p-5">
      <p className="font-display text-sm font-semibold text-conflict">
        {context ?? "Richiesta non riuscita"}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{apiErrorMessage(error)}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-lg bg-ink px-3 py-1.5 text-xs font-semibold text-primary-foreground"
        >
          Riprova
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-edge p-8 text-center">
      <p className="font-display text-sm font-semibold">{title}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Panel({
  title,
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="glass rounded-2xl">
      {title ? (
        <div className="flex items-center gap-3 border-b border-edge px-4 py-3">
          <h2 className="font-display text-sm font-semibold">{title}</h2>
          <div className="ml-auto">{action}</div>
        </div>
      ) : null}
      <div className="p-4">{children}</div>
    </div>
  );
}
