import { createFileRoute, Link } from "@tanstack/react-router";
import { Panel } from "@/components/States";

export const Route = createFileRoute("/dati/")({
  component: DataIndex,
});

const SECTIONS = [
  { to: "/dati/calendario", label: "Calendario", desc: "Date, ore massime, chiusure e stage." },
  { to: "/dati/docenti", label: "Docenti", desc: "Anagrafica e tipologia contrattuale." },
  { to: "/dati/classi", label: "Classi", desc: "Elenco delle classi dell'istituto." },
  { to: "/dati/materie", label: "Materie", desc: "Tipologia e peso cognitivo." },
  {
    to: "/dati/assegnazioni",
    label: "Assegnazioni",
    desc: "Docente × classe × materia e monte ore.",
  },
  { to: "/dati/accoppiamenti", label: "Accoppiamenti", desc: "Classi in lezione congiunta." },
] as const;

function DataIndex() {
  return (
    <Panel title="Sezioni disponibili">
      <div className="grid grid-cols-3 gap-3">
        {SECTIONS.map((s) => (
          <Link
            key={s.to}
            to={s.to}
            className="rounded-xl border border-edge bg-card p-3 transition-colors hover:border-brand/50"
          >
            <p className="text-xs font-semibold">{s.label}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">{s.desc}</p>
          </Link>
        ))}
      </div>
    </Panel>
  );
}
