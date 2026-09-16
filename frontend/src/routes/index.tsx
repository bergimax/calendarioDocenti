import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { api, apiErrorMessage, setAuthToken } from "@/lib/api";
import { Button, Field } from "@/components/ui-kit";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Accedi · Orario — Pianificazione scolastica" },
      {
        name: "description",
        content:
          "Accesso alla piattaforma di generazione e ottimizzazione dell'orario scolastico settimanale.",
      },
      { property: "og:title", content: "Accedi · Orario" },
      {
        property: "og:description",
        content: "Piattaforma di gestione e ottimizzazione degli orari scolastici.",
      },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await api<{ token: string }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setAuthToken(res.token);
      navigate({ to: "/menu" });
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-background px-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-lg bg-brand font-display text-sm font-bold text-primary-foreground">
            O
          </div>
          <div>
            <div className="font-display text-base font-semibold leading-none">Orario</div>
            <div className="label-mono mt-1">Pianificazione scolastica</div>
          </div>
        </div>

        <form onSubmit={onSubmit} className="glass space-y-3 rounded-2xl p-5">
          <h1 className="font-display text-lg font-semibold">Accedi</h1>
          <Field
            label="Email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="nome@istituto.it"
          />
          <Field
            label="Password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
          {error ? <p className="text-xs text-conflict">{error}</p> : null}
          <Button type="submit" variant="primary" className="w-full" disabled={loading}>
            {loading ? "Accesso in corso…" : "Entra"}
          </Button>
          <button
            type="button"
            onClick={() => navigate({ to: "/menu" })}
            className="w-full text-center text-[11px] font-medium text-muted-foreground underline-offset-2 hover:underline"
          >
            Continua senza autenticazione
          </button>
        </form>
      </div>
    </div>
  );
}
