import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";

export const Route = createFileRoute("/dati")({
  head: () => ({
    meta: [
      { title: "Dati scuola · Orario scolastico" },
      {
        name: "description",
        content:
          "Gestione di calendario, docenti, classi, materie, assegnazioni e accoppiamenti dell'istituto.",
      },
      { property: "og:title", content: "Dati scuola · Orario scolastico" },
      {
        property: "og:description",
        content: "Modifica in qualsiasi momento le anagrafiche della scuola.",
      },
    ],
  }),
  component: DataLayout,
});

const TABS = [
  { to: "/dati", label: "Riepilogo", exact: true },
  { to: "/dati/calendario", label: "Calendario", exact: false },
  { to: "/dati/docenti", label: "Docenti", exact: false },
  { to: "/dati/classi", label: "Classi", exact: false },
  { to: "/dati/materie", label: "Materie", exact: false },
  { to: "/dati/assegnazioni", label: "Assegnazioni", exact: false },
  { to: "/dati/accoppiamenti", label: "Accoppiamenti", exact: false },
] as const;

function DataLayout() {
  return (
    <AppShell title="Dati scuola" subtitle="Gestione anagrafiche">
      <div className="mb-4 flex flex-wrap items-center gap-1">
        {TABS.map((t) => (
          <Link
            key={t.to}
            to={t.to}
            activeOptions={{ exact: t.exact }}
            className="rounded-md px-3 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent/50"
            activeProps={{ className: "bg-brand text-primary-foreground font-semibold" }}
          >
            {t.label}
          </Link>
        ))}
      </div>
      <Outlet />
    </AppShell>
  );
}
