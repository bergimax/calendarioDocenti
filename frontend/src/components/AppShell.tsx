import { Link, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { isSegreteria } from "@/lib/api";

const NAV = [
  { to: "/menu", label: "Panoramica" },
  { to: "/disponibilita", label: "Disponibilità" },
  { to: "/orario", label: "Orario" },
  { to: "/dati", label: "Dati scuola" },
  { to: "/setup", label: "Setup iniziale" },
] as const;

export function AppShell({
  title,
  subtitle,
  actions,
  children,
  footer,
  rail,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  rail?: ReactNode;
}) {
  const navigate = useNavigate();
  const segreteria = isSegreteria();
  // La segreteria vede solo disponibilità e orario (sola lettura).
  const nav = NAV.filter((i) => !segreteria || i.to === "/menu" || i.to === "/disponibilita" || i.to === "/orario");

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="glass-panel flex w-60 shrink-0 flex-col border-r border-edge">
        <div className="flex items-center gap-2.5 border-b border-edge px-5 py-4">
          <div className="grid size-8 place-items-center rounded-lg bg-brand font-display text-sm font-bold text-primary-foreground">
            O
          </div>
          <div>
            <div className="font-display text-sm font-semibold leading-none">Orario</div>
            <div className="label-mono mt-1">Istituto</div>
          </div>
        </div>
        <nav className="space-y-0.5 p-3 text-sm">
          {nav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="flex items-center gap-2.5 rounded-lg px-3 py-2 font-medium text-muted-foreground transition-colors hover:bg-accent/60"
              activeProps={{ className: "bg-accent text-accent-foreground font-semibold" }}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto border-t border-edge p-3">
          <div className="flex items-center gap-2.5 px-2 py-1.5">
            <div className="grid size-8 place-items-center rounded-full bg-muted text-xs font-semibold">
              MA
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold">{segreteria ? "Segreteria" : "Amministratore"}</div>
              <div className="label-mono">{segreteria ? "Sola lettura" : "School Admin"}</div>
            </div>
          </div>
          <Link
            to="/account"
            className="mt-1 block w-full rounded-lg px-2 py-1.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-accent/60"
            activeProps={{ className: "bg-accent text-accent-foreground" }}
          >
            Cambia password
          </Link>
          <button
            type="button"
            onClick={() => navigate({ to: "/", replace: true })}
            className="mt-1 w-full rounded-lg px-2 py-1.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-accent/60"
          >
            Esci
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="glass-panel flex h-14 shrink-0 items-center gap-4 border-b border-edge px-6">
          <h1 className="font-display text-base font-semibold tracking-tight">{title}</h1>
          {subtitle ? <span className="label-mono">{subtitle}</span> : null}
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </header>

        <div className="flex min-h-0 flex-1">
          <section className="min-w-0 flex-1 overflow-auto p-5">{children}</section>
          {rail ? (
            <aside className="glass-panel flex w-[340px] shrink-0 flex-col border-l border-edge">
              {rail}
            </aside>
          ) : null}
        </div>

        {footer ? (
          <footer className="glass-panel flex h-14 shrink-0 items-center gap-3 border-t border-edge px-6">
            {footer}
          </footer>
        ) : null}
      </main>
    </div>
  );
}
