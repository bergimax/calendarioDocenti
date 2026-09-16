import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, apiErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui-kit";
import { EmptyState, ErrorState, LoadingState, Panel } from "@/components/States";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

/**
 * Tabella generica per le sezioni "Dati scuola".
 * Legge dall'endpoint indicato ed espone creazione, modifica e rimozione.
 */
export function CrudTable<T extends Record<string, unknown>>({
  title,
  endpoint,
  idKey,
  columns,
  form,
  emptyHint,
}: {
  title: string;
  endpoint: string;
  idKey: keyof T & string;
  columns: Column<T>[];
  form: (args: {
    value: Record<string, string>;
    set: (key: string, val: string) => void;
  }) => ReactNode;
  emptyHint?: string;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);

  const query = useQuery({
    queryKey: [endpoint],
    queryFn: () => api<T[]>(endpoint),
    retry: false,
  });

  function set(key: string, val: string) {
    setDraft((d) => ({ ...d, [key]: val }));
  }

  async function submit() {
    setBusy(true);
    setActionError(null);
    try {
      if (editingId) {
        await api(`${endpoint}/${editingId}`, { method: "PUT", body: draft });
      } else {
        await api(endpoint, { method: "POST", body: draft });
      }
      setDraft({});
      setEditingId(null);
      await query.refetch();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setConfirmingId(null);
    setActionError(null);
    try {
      await api(`${endpoint}/${id}`, { method: "DELETE" });
      await query.refetch();
    } catch (err) {
      setActionError(err);
    }
  }

  const rows = query.data ?? [];

  return (
    <div className="grid max-w-6xl gap-4 lg:grid-cols-[1fr_320px]">
      <Panel title={title}>
        {query.isLoading ? <LoadingState /> : null}
        {query.isError ? (
          <ErrorState
            error={query.error}
            onRetry={() => void query.refetch()}
            context="Dati non disponibili"
          />
        ) : null}
        {!query.isLoading && !query.isError && rows.length === 0 ? (
          <EmptyState title="Nessun record" {...(emptyHint ? { hint: emptyHint } : {})} />
        ) : null}
        {rows.length > 0 ? (
          <table className="w-full border-collapse text-[11px]">
            <thead>
              <tr className="bg-muted font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {columns.map((c) => (
                  <th key={c.key} className="border-b border-edge px-3 py-2 text-left font-medium">
                    {c.header}
                  </th>
                ))}
                <th className="border-b border-edge px-3 py-2 text-right font-medium">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const id = String(row[idKey]);
                return (
                  <tr key={id}>
                    {columns.map((c) => (
                      <td key={c.key} className="border-b border-edge px-3 py-2">
                        {c.render(row)}
                      </td>
                    ))}
                    <td className="border-b border-edge px-3 py-2 text-right">
                      {confirmingId === id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-muted-foreground">Confermi?</span>
                          <button
                            type="button"
                            className="font-semibold text-conflict"
                            onClick={() => void remove(id)}
                          >
                            Sì
                          </button>
                          <button
                            type="button"
                            className="font-semibold text-muted-foreground"
                            onClick={() => setConfirmingId(null)}
                          >
                            Annulla
                          </button>
                        </span>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="mr-3 font-semibold text-brand"
                            onClick={() => {
                              setEditingId(id);
                              const next: Record<string, string> = {};
                              for (const [k, v] of Object.entries(row)) next[k] = String(v ?? "");
                              setDraft(next);
                            }}
                          >
                            Modifica
                          </button>
                          <button
                            type="button"
                            className="font-semibold text-conflict"
                            onClick={() => setConfirmingId(id)}
                          >
                            Rimuovi
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
      </Panel>

      <Panel title={editingId ? "Modifica record" : "Nuovo record"}>
        <div className="space-y-3">
          {form({ value: draft, set })}
          {actionError ? (
            <p className="text-[11px] text-conflict">{apiErrorMessage(actionError)}</p>
          ) : null}
          <div className="flex gap-2">
            <Button variant="primary" className="flex-1" onClick={submit} disabled={busy}>
              {busy ? "Salvo…" : editingId ? "Aggiorna" : "Aggiungi"}
            </Button>
            {editingId ? (
              <Button
                onClick={() => {
                  setEditingId(null);
                  setDraft({});
                }}
              >
                Annulla
              </Button>
            ) : null}
          </div>
        </div>
      </Panel>
    </div>
  );
}
