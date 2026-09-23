import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Badge, Button, Select } from "@/components/ui-kit";
import { ErrorState, LoadingState } from "@/components/States";
import { API_BASE_URL, api, apiErrorMessage } from "@/lib/api";
import type { ChatMessage, Conflict, Schedule, SlotLezione, Teacher, Week } from "@/lib/types";

export const Route = createFileRoute("/orario")({
  head: () => ({
    meta: [
      { title: "Orario settimanale · Generazione e copilota IA" },
      {
        name: "description",
        content:
          "Tabellone classi × ore, punteggio di qualità, copilota IA, deroghe rapide, approvazione ed esportazione PDF.",
      },
      { property: "og:title", content: "Orario settimanale · Generazione e copilota IA" },
      {
        property: "og:description",
        content: "Genera, correggi e approva l'orario settimanale della scuola.",
      },
    ],
  }),
  component: SchedulePage,
});

const ORE = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"];

// Backend giorno values are uppercase ("LUNEDI".."VENERDI"); these are the
// select-option values sent back to modify-slot, paired with a readable label.
const GIORNI = [
  { value: "LUNEDI", label: "Lunedì" },
  { value: "MARTEDI", label: "Martedì" },
  { value: "MERCOLEDI", label: "Mercoledì" },
  { value: "GIOVEDI", label: "Giovedì" },
  { value: "VENERDI", label: "Venerdì" },
];

// SlotLezioneResponse.ora_inizio is an int (8..13); option values must match.
const ORE_OPTIONS = [8, 9, 10, 11, 12, 13].map((h) => ({ value: h, label: `${String(h).padStart(2, "0")}:00` }));

const QUICK_ACTIONS = [
  { action_type: "force_3_hours_theory", label: "Forza 3 ore teoria" },
  { action_type: "reduce_contract_hours", label: "Riduci ore docente a contratto" },
  { action_type: "authorize_early_exit", label: "Autorizza uscita anticipata" },
  { action_type: "override_availability", label: "Deroga disponibilità" },
  { action_type: "authorize_single_classe_day", label: "Autorizza giornata mono-classe" },
  { action_type: "authorize_friday_late_start", label: "Autorizza inizio posticipato di venerdì" },
  { action_type: "authorize_short_pratica_block", label: "Autorizza blocco pratica corto" },
];

// generate/regenerate, modify-slot and apply-quick-action all reply with
// HTTP 200 even when the requested change is rejected (a locked schedule, a
// broken pairing constraint, an unassigned teacher, ...) - the body is then
// {"status": "error", "message": "..."} instead of a real Schedule. Every
// caller must check for that shape before treating the response as a
// Schedule to display, or a rejection crashes the whole page (active.slots
// is not iterable) instead of showing the backend's own error message.
type ScheduleMutationResult = Schedule & { status?: string; message?: string };

function requireSchedule(res: ScheduleMutationResult): Schedule {
  if (res.status === "error") {
    throw new Error(res.message ?? "Operazione non riuscita");
  }
  return res;
}

function SchedulePage() {
  const [week, setWeek] = useState("");
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<unknown>(null);
  const [highlightTeacher, setHighlightTeacher] = useState<string | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<SlotLezione | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const weeks = useQuery({
    queryKey: ["weeks"],
    queryFn: () => api<{ weeks: Week[] }>("/api/availability/weeks"),
    retry: false,
  });

  const existing = useQuery({
    queryKey: ["schedule", week],
    queryFn: () => api<Schedule>(`/api/schedule/${week}`),
    enabled: Boolean(week),
    retry: false,
  });

  const active = schedule ?? existing.data ?? null;

  const classi = useMemo(() => {
    if (!active) return [] as { id: string; nome: string }[];
    if (active.classes?.length) {
      return active.classes.map((c) => ({ id: c.classe_id, nome: c.nome }));
    }
    const seen = new Map<string, string>();
    for (const s of active.slots) seen.set(s.classe_id, s.classe_nome ?? s.classe_id);
    for (const sc of active.stage_cells ?? []) seen.set(sc.classe_id, sc.classe_nome ?? sc.classe_id);
    return [...seen].map(([id, nome]) => ({ id, nome }));
  }, [active]);

  async function generate(endpoint: "generate" | "regenerate") {
    setGenerating(true);
    setGenError(null);
    try {
      const body =
        endpoint === "generate" ? { week_start: week, include_preferences: true } : {};
      const path =
        endpoint === "generate" ? "/api/schedule/generate" : `/api/schedule/${week}/regenerate`;
      const res = await api<ScheduleMutationResult>(path, { method: "POST", body });
      setSchedule(requireSchedule(res));
    } catch (err) {
      setGenError(err);
    } finally {
      setGenerating(false);
    }
  }

  async function applyQuickAction(actionType: string) {
    try {
      const res = await api<ScheduleMutationResult>(`/api/schedule/${week}/apply-quick-action`, {
        method: "POST",
        body: { action_type: actionType, parameters: {} },
      });
      const updated = requireSchedule(res);
      setSchedule(updated);
      setNotice(`Deroga applicata · nuovo punteggio ${Math.round(updated.quality_score)}`);
    } catch (err) {
      setNotice(apiErrorMessage(err));
    }
  }

  async function approve() {
    try {
      const res = await api<{ status: string; message?: string }>(`/api/schedule/${week}/approve`, {
        method: "POST",
        body: { schedule_id: active?.schedule_id },
      });
      if (res.status === "error") throw new Error(res.message ?? "Approvazione non riuscita");
      setNotice("Orario approvato.");
      setSchedule(null);
      void existing.refetch();
    } catch (err) {
      setNotice(apiErrorMessage(err));
    }
  }

  async function exportPdf() {
    try {
      const res = await api<{ pdf_url: string }>(`/api/schedule/${week}/export-pdf`);
      window.open(`${API_BASE_URL}${res.pdf_url}`, "_blank", "noopener");
    } catch (err) {
      setNotice(apiErrorMessage(err));
    }
  }

  const conflicts: Conflict[] = active?.conflicts ?? [];
  const approved = active?.stato === "APPROVATO";

  return (
    <AppShell
      title="Orario settimanale"
      subtitle={week ? `Settimana dal ${week}` : "Seleziona una settimana"}
      actions={
        <>
          <Select
            value={week}
            onChange={(e) => {
              setWeek(e.target.value);
              setSchedule(null);
            }}
            className="w-52 py-1.5 text-xs"
          >
            <option value="">Settimana…</option>
            {(weeks.data?.weeks ?? []).map((w) => (
              <option key={w.start} value={w.start}>
                Settimana {w.week_num} ({w.start})
              </option>
            ))}
          </Select>
          {conflicts.length ? (
            <Badge tone="conflict">{conflicts.length} conflitti</Badge>
          ) : null}
          <Button variant="solid" onClick={exportPdf} disabled={!active}>
            Esporta PDF
          </Button>
        </>
      }
      rail={
        <SidePanel
          week={week}
          schedule={active}
          conflicts={conflicts}
          onScheduleUpdate={setSchedule}
          onQuickAction={applyQuickAction}
          selectedSlot={selectedSlot}
          onCloseSlot={() => setSelectedSlot(null)}
          onSlotUpdated={(s) => {
            setSchedule(s);
            setSelectedSlot(null);
          }}
        />
      }
      footer={
        <>
          <span className="label-mono">
            {active
              ? `${classi.length} classi · ${active.slots.length} lezioni · stato ${active.stato ?? "BOZZA"}`
              : "Nessun orario caricato"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button onClick={() => generate("regenerate")} disabled={!week || generating}>
              Genera da zero
            </Button>
            <Button variant="primary" onClick={approve} disabled={!active || approved}>
              {approved ? "Approvato" : "Approva settimana"}
            </Button>
          </div>
        </>
      }
    >
      <div className="space-y-4">
        {notice ? (
          <p className="glass rounded-xl px-3 py-2 text-xs text-muted-foreground">{notice}</p>
        ) : null}

        {weeks.isError ? (
          <ErrorState
            error={weeks.error}
            onRetry={() => void weeks.refetch()}
            context="Elenco settimane non disponibile"
          />
        ) : null}

        <div className="flex items-start gap-3">
          <div className="flex-1">
            <div className="flex items-end justify-between">
              <div>
                <div className="label-mono">Qualità orario</div>
                <div className="mt-1 font-display text-4xl font-bold leading-none">
                  {active?.quality_score != null ? Math.round(active.quality_score) : "—"}
                  <span className="text-lg text-muted-foreground">/100</span>
                </div>
              </div>
              <div className="label-mono">
                {active?.quality_level ? `Livello ${active.quality_level}` : "In attesa del solver"}
              </div>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-edge">
              <div
                className="h-full rounded-full bg-brand transition-[width] duration-700"
                style={{ width: `${active?.quality_score ?? 0}%` }}
              />
            </div>
          </div>
          <Button
            variant="primary"
            onClick={() => generate("generate")}
            disabled={!week || generating}
          >
            {generating ? "Solver in esecuzione…" : "Genera nuovo orario"}
          </Button>
        </div>

        <div className="flex items-center gap-4 font-mono text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-theory bg-theory/20" />
            Teoria
          </span>
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-practical bg-practical/20" />
            Pratica
          </span>
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-conflict bg-conflict/20" />
            Conflitto
          </span>
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-dashed border-edge" />
            Libera
          </span>
        </div>

        {generating ? <LoadingState label="Il solver sta calcolando l'orario (30-60s)…" /> : null}
        {genError ? (
          <ErrorState
            error={genError}
            onRetry={() => generate("generate")}
            context="Generazione non riuscita"
          />
        ) : null}
        {!generating && !genError && existing.isError && !schedule ? (
          <ErrorState
            error={existing.error}
            onRetry={() => void existing.refetch()}
            context="Orario della settimana non disponibile"
          />
        ) : null}

        {active ? (
          <ScheduleTable
            schedule={active}
            classi={classi}
            highlightTeacher={highlightTeacher}
            onHighlightTeacher={setHighlightTeacher}
            onSelectSlot={setSelectedSlot}
          />
        ) : null}

        <div className="flex items-center gap-2">
          {QUICK_ACTIONS.map((a) => (
            <Button
              key={a.action_type}
              onClick={() => applyQuickAction(a.action_type)}
              disabled={!active}
            >
              {a.label}
            </Button>
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function ScheduleTable({
  schedule,
  classi,
  highlightTeacher,
  onHighlightTeacher,
  onSelectSlot,
}: {
  schedule: Schedule;
  classi: { id: string; nome: string }[];
  highlightTeacher: string | null;
  onHighlightTeacher: (id: string | null) => void;
  onSelectSlot: (slot: SlotLezione) => void;
}) {
  const [giorno, setGiorno] = useState("lunedi");

  const byCell = new Map<string, SlotLezione>();
  for (const s of schedule.slots) {
    // s.giorno comes from the backend as "LUNEDI".."VENERDI" (uppercase);
    // the tab state below is lowercase for the nice capitalize styling.
    if (s.giorno !== giorno.toUpperCase()) continue;
    const oraKey = `${String(s.ora_inizio).padStart(2, "0")}:00`;
    byCell.set(`${oraKey}|${s.classe_id}`, s);
  }
  const stageClassi = new Set(
    (schedule.stage_cells ?? [])
      .filter((sc) => sc.giorno === giorno.toUpperCase())
      .map((sc) => sc.classe_id),
  );
  const classeIndex = new Map(classi.map((c, i) => [c.id, i]));

  // A joint lesson can span more than 2 classi (a 4-way group is stored as
  // one ClasseAccoppiata row per pair, see backend docstring). Group classi
  // that actually co-occur this hour by following classe_accoppiata_id
  // edges, instead of only skipping one named partner - otherwise a 3rd/4th
  // class in the group re-uses a column already merged into an earlier
  // class's colSpan and every following column shifts left.
  function groupForHour(ora: string): {
    cellSlots: Map<string, SlotLezione>;
    groupOf: Map<string, string[]>;
  } {
    const cellSlots = new Map<string, SlotLezione>();
    for (const c of classi) {
      const slot = byCell.get(`${ora}|${c.id}`);
      if (slot) cellSlots.set(c.id, slot);
    }

    const parent = new Map<string, string>();
    for (const id of cellSlots.keys()) parent.set(id, id);
    function find(x: string): string {
      while (parent.get(x) !== x) x = parent.get(x) as string;
      return x;
    }

    for (const [classeId, slot] of cellSlots) {
      const partner = slot.classe_accoppiata_id;
      if (slot.accoppiata && partner && parent.has(partner)) {
        const ra = find(classeId);
        const rb = find(partner);
        if (ra !== rb) parent.set(ra, rb);
      }
    }

    const byRoot = new Map<string, string[]>();
    for (const id of cellSlots.keys()) {
      const root = find(id);
      const group = byRoot.get(root) ?? [];
      group.push(id);
      byRoot.set(root, group);
    }
    const groupOf = new Map<string, string[]>();
    for (const id of cellSlots.keys()) groupOf.set(id, byRoot.get(find(id)) as string[]);
    return { cellSlots, groupOf };
  }

  return (
    <div className="glass overflow-hidden rounded-2xl">
      <div className="flex items-center gap-1 border-b border-edge px-3 py-2">
        {["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"].map((g) => (
          <button
            key={g}
            type="button"
            onClick={() => setGiorno(g)}
            className={
              g === giorno
                ? "rounded-md bg-brand px-3 py-1 text-[11px] font-semibold capitalize text-primary-foreground"
                : "rounded-md px-3 py-1 text-[11px] font-medium capitalize text-muted-foreground hover:bg-accent/50"
            }
          >
            {g}
          </button>
        ))}
      </div>
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="bg-muted font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="w-16 border-b border-edge px-3 py-2 text-left font-medium">Ora</th>
            {classi.map((c) => (
              <th key={c.id} className="border-b border-edge px-3 py-2 text-left font-medium">
                {c.nome}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ORE.map((ora) => {
            const skip = new Set<string>();
            const { cellSlots, groupOf } = groupForHour(ora);
            return (
              <tr key={ora}>
                <td className="border-b border-edge px-3 py-2 font-mono text-muted-foreground">
                  {ora}
                </td>
                {classi.map((c) => {
                  if (skip.has(c.id)) return null;
                  if (stageClassi.has(c.id)) {
                    return (
                      <td key={c.id} className="border-b border-edge px-2 py-2">
                        <div className="rounded-md border border-warn bg-warn/20 px-2 py-1 text-center font-semibold text-warn">
                          STAGE
                        </div>
                      </td>
                    );
                  }
                  const slot = cellSlots.get(c.id);
                  if (!slot) {
                    return (
                      <td key={c.id} className="border-b border-edge px-2 py-2">
                        <div className="rounded-md border border-dashed border-edge bg-card px-2 py-1 text-muted-foreground">
                          Libera
                        </div>
                      </td>
                    );
                  }
                  const group = groupOf.get(c.id) ?? [c.id];
                  let colSpan = 1;
                  if (group.length > 1) {
                    const indices = group
                      .map((id) => classeIndex.get(id) as number)
                      .sort((a, b) => a - b);
                    const first = indices[0] as number;
                    const contiguous = indices.every((idx, i) => idx === first + i);
                    // Only merge into one cell when the group is an unbroken
                    // run of columns; otherwise leave each classe its own
                    // cell rather than risk an invalid colSpan.
                    if (contiguous) {
                      colSpan = group.length;
                      for (const id of group) if (id !== c.id) skip.add(id);
                    }
                  }
                  const paired = colSpan > 1;
                  const tone = slot.conflitto
                    ? "border-conflict bg-conflict/10"
                    : slot.materia_tipo === "PRATICA"
                      ? "border-practical bg-practical/10"
                      : "border-theory bg-theory/10";
                  const dimmed =
                    highlightTeacher && slot.docente_id !== highlightTeacher ? "opacity-35" : "";
                  return (
                    <td
                      key={c.id}
                      colSpan={colSpan}
                      className="border-b border-edge px-2 py-2"
                    >
                      <button
                        type="button"
                        onClick={() => onSelectSlot(slot)}
                        title={`Monte ore residuo non disponibile senza backend`}
                        className={`w-full rounded-md border-l-2 px-2 py-1 text-left transition-opacity ${tone} ${dimmed}`}
                      >
                        <span
                          role="link"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation();
                            onHighlightTeacher(
                              highlightTeacher === slot.docente_id ? null : slot.docente_id,
                            );
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.stopPropagation();
                              onHighlightTeacher(slot.docente_id);
                            }
                          }}
                          className="font-semibold underline-offset-2 hover:underline"
                        >
                          {slot.docente_nome ?? slot.docente_id}
                          {paired ? " · accoppiata" : ""}
                        </span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SidePanel({
  week,
  schedule,
  conflicts,
  onScheduleUpdate,
  onQuickAction,
  selectedSlot,
  onCloseSlot,
  onSlotUpdated,
}: {
  week: string;
  schedule: Schedule | null;
  conflicts: Conflict[];
  onScheduleUpdate: (s: Schedule) => void;
  onQuickAction: (actionType: string) => void;
  selectedSlot: SlotLezione | null;
  onCloseSlot: () => void;
  onSlotUpdated: (s: Schedule) => void;
}) {
  return (
    <>
      <div className="flex items-center gap-2 border-b border-edge px-4 py-3">
        <span className="size-2 rounded-full bg-brand" />
        <span className="font-display text-sm font-semibold">Copilota Orario</span>
      </div>

      {selectedSlot ? (
        <ModifySlotPanel
          week={week}
          slot={selectedSlot}
          onClose={onCloseSlot}
          onUpdated={onSlotUpdated}
        />
      ) : null}

      <div className="border-b border-edge px-4 py-3">
        <div className="label-mono">Conflitti</div>
        <div className="mt-2 space-y-2">
          {conflicts.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">Nessun conflitto segnalato.</p>
          ) : (
            conflicts.map((c) => (
              <div key={c.conflict_id} className="rounded-lg bg-conflict/5 p-2 ring-1 ring-conflict/20">
                <div className="text-xs font-semibold text-conflict">{c.description}</div>
                {c.suggested_action ? (
                  <button
                    type="button"
                    onClick={() => onQuickAction(c.suggested_action!.action_type)}
                    className="mt-1 text-[11px] font-semibold text-brand"
                  >
                    {c.suggested_action.label}
                  </button>
                ) : null}
              </div>
            ))
          )}
        </div>
      </div>

      <ChatPanel week={week} schedule={schedule} onScheduleUpdate={onScheduleUpdate} />
    </>
  );
}

function ModifySlotPanel({
  week,
  slot,
  onClose,
  onUpdated,
}: {
  week: string;
  slot: SlotLezione;
  onClose: () => void;
  onUpdated: (s: Schedule) => void;
}) {
  const [giorno, setGiorno] = useState(slot.giorno);
  const [ora, setOra] = useState(slot.ora_inizio);
  const [docente, setDocente] = useState(slot.docente_id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const teachers = useQuery({
    queryKey: ["teachers"],
    queryFn: () => api<Teacher[]>("/api/teachers"),
    retry: false,
  });

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await api<ScheduleMutationResult>(`/api/schedule/${week}/modify-slot`, {
        method: "POST",
        body: {
          slot_id: slot.slot_id,
          changes: { docente_id: docente, giorno, ora_inizio: ora },
        },
      });
      onUpdated(requireSchedule(res));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border-b border-edge px-4 py-3">
      <div className="flex items-center">
        <span className="label-mono">Modifica slot</span>
        <button type="button" onClick={onClose} className="ml-auto text-[11px] text-muted-foreground">
          Chiudi
        </button>
      </div>
      <Select label="Giorno" value={giorno} onChange={(e) => setGiorno(e.target.value)}>
        {GIORNI.map(({ value, label }) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>
      <Select label="Ora" value={ora} onChange={(e) => setOra(Number(e.target.value))}>
        {ORE_OPTIONS.map(({ value, label }) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>
      <Select label="Docente" value={docente} onChange={(e) => setDocente(e.target.value)}>
        {(teachers.data ?? [{ teacher_id: slot.docente_id, nome: slot.docente_nome ?? slot.docente_id }]).map(
          (t) => (
            <option key={t.teacher_id} value={t.teacher_id}>
              {t.nome}
            </option>
          ),
        )}
      </Select>
      {error ? <p className="text-[11px] text-conflict">{apiErrorMessage(error)}</p> : null}
      <Button variant="primary" className="w-full" onClick={submit} disabled={busy}>
        {busy ? "Ricalcolo…" : "Salva e ricalcola"}
      </Button>
    </div>
  );
}

function ChatPanel({
  week,
  schedule,
  onScheduleUpdate,
}: {
  week: string;
  schedule: Schedule | null;
  onScheduleUpdate: (s: Schedule) => void;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);

  const history = useQuery({
    queryKey: ["chat", week],
    queryFn: () => api<{ messages: ChatMessage[] }>(`/api/chat/history/${week}`),
    enabled: Boolean(week),
    retry: false,
  });

  const shown = messages.length ? messages : (history.data?.messages ?? []);

  async function send() {
    if (!input.trim() || !week) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...(m.length ? m : (history.data?.messages ?? [])), { role: "admin", text }]);
    setSending(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          schedule_id: schedule?.schedule_id,
          week_start: week,
          message: text,
        }),
      });
      if (!res.ok || !res.body) throw new Error(`Errore ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      setMessages((m) => [...m, { role: "ai", text: "", streaming: true }]);

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          try {
            const payload = JSON.parse(line.slice(5).trim()) as {
              type?: string;
              text?: string;
              new_schedule?: Schedule;
            };
            if (payload.new_schedule) onScheduleUpdate(payload.new_schedule);
            setMessages((m) => {
              const next = [...m];
              const last = next[next.length - 1];
              if (last && last.role === "ai") {
                next[next.length - 1] = {
                  ...last,
                  text: payload.text ?? last.text,
                  streaming: payload.type !== "ready",
                };
              }
              return next;
            });
          } catch {
            /* frammento non JSON */
          }
        }
      }
      setMessages((m) =>
        m.map((msg, i) => (i === m.length - 1 ? { ...msg, streaming: false } : msg)),
      );
    } catch (err) {
      setMessages((m) => [
        ...m.map((msg, i) => (i === m.length - 1 && msg.streaming ? { ...msg, streaming: false } : msg)),
        { role: "ai", text: `Copilota non disponibile: ${apiErrorMessage(err)}` },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-4 text-[13px]">
        {shown.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            Chiedi al copilota di spostare lezioni o risolvere conflitti in linguaggio naturale.
          </p>
        ) : null}
        {shown.map((m, i) =>
          m.role === "admin" ? (
            <div
              key={i}
              className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-brand px-3 py-2 text-primary-foreground"
            >
              {m.text}
            </div>
          ) : (
            <div
              key={i}
              className="animate-fade-up max-w-[90%] rounded-2xl rounded-bl-md bg-card px-3 py-2 text-foreground/80 ring-1 ring-edge"
            >
              {m.text}
              {m.streaming ? <span className="animate-pulse"> ▋</span> : null}
            </div>
          ),
        )}
      </div>
      <div className="border-t border-edge p-3">
        <div className="flex items-center gap-2 rounded-xl bg-background px-3 py-2 ring-1 ring-edge">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void send();
            }}
            placeholder="Chiedi al copilota…"
            className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending}
            className="text-xs font-semibold text-brand disabled:opacity-50"
          >
            Invia
          </button>
        </div>
      </div>
    </>
  );
}
