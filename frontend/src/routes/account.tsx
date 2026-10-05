import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Button, Field } from "@/components/ui-kit";
import { Panel } from "@/components/States";
import { api, apiErrorMessage } from "@/lib/api";

export const Route = createFileRoute("/account")({
  head: () => ({
    meta: [
      { title: "Account · Orario scolastico" },
      { name: "description", content: "Cambia la password del tuo account." },
    ],
  }),
  component: AccountPage,
});

const MIN_LENGTH = 8;

function AccountPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setDone(false);
    if (next.length < MIN_LENGTH) {
      setError(`La nuova password deve avere almeno ${MIN_LENGTH} caratteri.`);
      return;
    }
    if (next !== confirm) {
      setError("La conferma non coincide con la nuova password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Account" subtitle="Cambia password">
      <div className="max-w-md">
        <Panel title="Cambia password">
          <form onSubmit={onSubmit} className="space-y-3">
            <Field
              label="Password attuale"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
            <Field
              label="Nuova password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
            <Field
              label="Conferma nuova password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
            {error ? <p className="text-xs text-conflict">{error}</p> : null}
            {done ? (
              <p className="text-xs text-muted-foreground">
                Password aggiornata. Le altre sessioni aperte sono state chiuse.
              </p>
            ) : null}
            <Button type="submit" variant="primary" className="w-full" disabled={busy}>
              {busy ? "Salvo…" : "Salva nuova password"}
            </Button>
          </form>
        </Panel>
      </div>
    </AppShell>
  );
}
