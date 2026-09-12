import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Badge, Button, Select } from "@/components/ui-kit";
import { ErrorState, LoadingState, Panel } from "@/components/States";
import { api, apiErrorMessage } from "@/lib/api";
import type {
  AvailabilityStatus,
  Giorno,
  GiorniFasce,
  Teacher,
  TeacherAvailability,
  Week,
} from "@/lib/types";

export const Route = createFileRoute("/disponibilita")({
  head: () => ({
    meta: [
      { title: "Disponibilità docenti · Orario scolastico" },
      {
        name: "description",
        content:
          "Griglia settimanale delle disponibilità dei docenti: fasce 08:00-14:00 dal lunedì al venerdì.",
      },
      { property: "og:title", content: "Disponibilità docenti · Orario scolastico" },
      {
        property: "og:description",
        content: "Compila e salva le disponibilità settimanali dei docenti.",
      },
    ],
  }),
  component: AvailabilityPage,
});

const GIORNI: { key: Giorno; label: string }[] = [
  { key: "lunedi", label: "Lun" },
  { key: "martedi", label: "Mar" },
  { key: "mercoledi", label: "Mer" },
  { key: "giovedi", label: "Gio" },
  { key: "venerdi", label: "Ven" },
];

const FASCE = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"];

function emptyGrid(): GiorniFasce {
  const build = () =>
    FASCE.map((ora, i) => ({
      ora_inizio: ora,
      ora_fine: FASCE[i + 1] ?? "14:00",
      disponibile: false,
    }));
  return {
    lunedi: build(),
    martedi: build(),
    mercoledi: build(),
    giovedi: build(),
    venerdi: build(),
  };
}

function AvailabilityPage() {
  const navigate = useNavigate();
  const [week, setWeek] = useState<string>("");
  const [copyMsg, setCopyMsg] = useState<string | null>(null);

  const weeks = useQuery({
    queryKey: ["weeks"],
    queryFn: () => api<{ weeks: Week[] }>("/api/availability/weeks"),
    retry: false,
  });

  const teachers = useQuery({
    queryKey: ["teachers"],
    queryFn: () => api<Teacher[]>("/api/teachers"),
    retry: false,
  });

  const status = useQuery({
    queryKey: ["availability-status", week],
    queryFn: () => api<AvailabilityStatus>(`/api/availability/${week}/status`),
    enabled: Boolean(week),
    retry: false,
  });

  useEffect(() => {
    const first = weeks.data?.weeks[0];
    if (!week && first) setWeek(first.start);
  }, [weeks.data, week]);

  async function copyAllFromPrevious() {
    if (!week) return;
    const list = weeks.data?.weeks ?? [];
    const idx = list.findIndex((w) => w.start === week);
    const prev = idx > 0 ? list[idx - 1] : undefined;
    if (!prev) {
      setCopyMsg("Nessuna settimana precedente disponibile.");
      return;
    }
    try {
      const res = await api<{ teachers_copied: number }>(
        `/api/availability/${week}/copy-from/${prev.start}`,
        { method: "POST" },
      );
      setCopyMsg(`Copiate ${res.teachers_copied} disponibilità dalla settimana precedente.`);
    } catch (err) {
      setCopyMsg(apiErrorMessage(err));
    }
  }

  return (
    <AppShell
      title="Disponibilità docenti"
      subtitle={week ? `Settimana dal ${week}` : "Seleziona una settimana"}
      actions={
        <>
          <Select
            value={week}
            onChange={(e) => setWeek(e.target.value)}
            className="w-56 py-1.5 text-xs"
          >
            <option value="">Settimana…</option>
            {(weeks.data?.weeks ?? []).map((w) => (
              <option key={w.start} value={w.start}>
                Settimana {w.week_num} ({w.start} → {w.end})
              </option>
            ))}
          </Select>
          <Button onClick={copyAllFromPrevious} disabled={!week}>
            Copia settimana scorsa
          </Button>
        </>
      }
      footer={
        <>
          <span className="label-mono">
            {status.data
              ? `${status.data.teachers_with_availability}/${status.data.total_teachers} docenti compilati`
              : "Stato settimana non disponibile"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button onClick={() => navigate({ to: "/menu" })}>← Indietro</Button>
            <Button
              variant="primary"
              onClick={() => navigate({ to: "/orario" })}
              disabled={!week}
            >
              Genera orario
            </Button>
          </div>
        </>
      }
    >
      <div className="max-w-5xl space-y-4">
        {copyMsg ? (
          <p className="glass rounded-xl px-3 py-2 text-xs text-muted-foreground">{copyMsg}</p>
        ) : null}

        {weeks.isLoading ? <LoadingState label="Carico le settimane…" /> : null}
        {weeks.isError ? (
          <ErrorState
            error={weeks.error}
            onRetry={() => void weeks.refetch()}
            context="Settimane non disponibili"
          />
        ) : null}

        {teachers.isLoading ? <LoadingState label="Carico i docenti…" /> : null}
        {teachers.isError ? (
          <ErrorState
            error={teachers.error}
            onRetry={() => void teachers.refetch()}
            context="Elenco docenti non disponibile"
          />
        ) : null}

        {(teachers.data ?? []).map((t) => (
          <TeacherGrid key={t.teacher_id} teacher={t} week={week} />
        ))}
      </div>
    </AppShell>
  );
}

function TeacherGrid({ teacher, week }: { teacher: Teacher; week: string }) {
  const [grid, setGrid] = useState<GiorniFasce>(emptyGrid());
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<unknown>(null);

  const query = useQuery({
    queryKey: ["availability", week, teacher.teacher_id],
    queryFn: () => api<TeacherAvailability>(`/api/availability/${week}/${teacher.teacher_id}`),
    enabled: Boolean(week),
    retry: false,
  });

  useEffect(() => {
    if (query.data?.giorni_fasce) setGrid(query.data.giorni_fasce);
  }, [query.data]);

  function toggle(giorno: Giorno, index: number) {
    setGrid((prev) => {
      const slots = [...(prev[giorno] ?? [])];
      const slot = slots[index];
      if (!slot) return prev;
      slots[index] = { ...slot, disponibile: !slot.disponibile };
      return { ...prev, [giorno]: slots };
    });
  }

  function setAll(value: boolean) {
    setGrid((prev) => {
      const next = { ...prev };
      for (const g of GIORNI) {
        next[g.key] = (prev[g.key] ?? []).map((s) => ({ ...s, disponibile: value }));
      }
      return next;
    });
  }

  async function save() {
    setSaveState("saving");
    setSaveError(null);
    try {
      await api(`/api/availability/${week}/${teacher.teacher_id}`, {
        method: "POST",
        body: { giorni_fasce: grid },
      });
      setSaveState("saved");
    } catch (err) {
      setSaveError(err);
      setSaveState("error");
    }
  }

  return (
    <Panel
      title={`${teacher.nome}${teacher.materia ? ` — ${teacher.materia}` : ""}`}
      action={
        <div className="flex items-center gap-2">
          <Badge tone={teacher.tipo === "ASSUNTO" ? "brand" : "neutral"}>
            {teacher.tipo === "ASSUNTO" ? "Assunto" : "Contrattista"}
          </Badge>
          {saveState === "saved" ? <Badge tone="ok">Salvato</Badge> : null}
        </div>
      }
    >
      {query.isError ? (
        <div className="mb-3">
          <ErrorState
            error={query.error}
            onRetry={() => void query.refetch()}
            context="Disponibilità non caricata"
          />
        </div>
      ) : null}

      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="bg-muted font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="border-b border-edge px-3 py-2 text-left font-medium">Ora</th>
            {GIORNI.map((g) => (
              <th key={g.key} className="border-b border-edge px-3 py-2 text-left font-medium">
                {g.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {FASCE.map((ora, i) => (
            <tr key={ora}>
              <td className="border-b border-edge px-3 py-1.5 font-mono text-muted-foreground">
                {ora}–{FASCE[i + 1] ?? "14:00"}
              </td>
              {GIORNI.map((g) => {
                const slot = grid[g.key]?.[i];
                const on = slot?.disponibile ?? false;
                return (
                  <td key={g.key} className="border-b border-edge px-2 py-1.5">
                    <button
                      type="button"
                      onClick={() => toggle(g.key, i)}
                      className={
                        on
                          ? "h-6 w-full rounded-md border-l-2 border-practical bg-practical/20"
                          : "h-6 w-full rounded-md border border-dashed border-edge bg-card"
                      }
                      aria-label={`${g.label} ${ora} ${on ? "disponibile" : "non disponibile"}`}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-3 flex items-center gap-2">
        <Button onClick={() => setAll(true)}>Seleziona tutto</Button>
        <Button onClick={() => setAll(false)}>Pulisci</Button>
        <Button variant="primary" onClick={save} disabled={!week || saveState === "saving"}>
          {saveState === "saving" ? "Salvo…" : "Salva"}
        </Button>
        {saveState === "error" ? (
          <span className="text-[11px] text-conflict">{apiErrorMessage(saveError)}</span>
        ) : null}
      </div>
    </Panel>
  );
}
