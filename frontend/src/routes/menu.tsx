import { createFileRoute, Link } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";

export const Route = createFileRoute("/menu")({
  head: () => ({
    meta: [
      { title: "Panoramica · Orario scolastico" },
      {
        name: "description",
        content: "Menu principale: setup, disponibilità docenti, generazione orario e dati scuola.",
      },
      { property: "og:title", content: "Panoramica · Orario scolastico" },
      { property: "og:description", content: "Menu principale della piattaforma orari." },
    ],
  }),
  component: MenuPage,
});

const CARDS = [
  {
    to: "/setup",
    title: "Setup iniziale",
    desc: "Carica calendario e anagrafiche, valida ed applica correzioni.",
  },
  {
    to: "/disponibilita",
    title: "Disponibilità docenti",
    desc: "Griglia settimanale ore × giorni per ogni docente.",
  },
  {
    to: "/orario",
    title: "Genera orario",
    desc: "Solver, copilota IA, deroghe, approvazione ed esportazione PDF.",
  },
  {
    to: "/dati",
    title: "Dati scuola",
    desc: "Calendario, docenti, classi, materie, assegnazioni, accoppiamenti.",
  },
] as const;

function MenuPage() {
  return (
    <AppShell title="Panoramica" subtitle="Anno formativo in corso">
      <div className="grid max-w-4xl grid-cols-2 gap-4">
        {CARDS.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="glass rounded-2xl p-5 transition-colors hover:bg-accent/40"
          >
            <h2 className="font-display text-sm font-semibold">{c.title}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{c.desc}</p>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}
