import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Badge, Button, Field, Select } from "@/components/ui-kit";
import { ErrorState, LoadingState } from "@/components/States";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { API_BASE_URL, api, apiErrorMessage } from "@/lib/api";
import type {
  ChatMessage,
  Conflict,
  Schedule,
  ScheduleFeedbackData,
  SlotLezione,
  Teacher,
  Week,
} from "@/lib/types";

// Column order for the weekly grid: group by corso (info, ele, este, pan,
// itc - school's own requested order), then by anno within each corso.
// "PAN." (not the full "PAN. E PAST.") because one class in the DB is named
// "III PAN. E PAST" without the trailing period - see classe_sort test.
const CORSO_ORDER = ["OP. INFORM.", "ELETTRICISTI", "ESTETISTE", "PAN.", "I.T.C."];
const ANNO_ORDER: Record<string, number> = { IV: 4, III: 3, II: 2, I: 1 };

function classeSortKey(nome: string): [number, number] {
  const corsoIdx = CORSO_ORDER.findIndex((c) => nome.includes(c));
  const annoMatch = nome.match(/^(IV|III|II|I)\b/);
  const annoIdx = annoMatch?.[1] ? (ANNO_ORDER[annoMatch[1]] ?? 99) : 99;
  return [corsoIdx === -1 ? CORSO_ORDER.length : corsoIdx, annoIdx];
}

function sortClassi<T extends { nome: string }>(classi: T[]): T[] {
  return [...classi].sort((a, b) => {
    const [ac, ay] = classeSortKey(a.nome);
    const [bc, by] = classeSortKey(b.nome);
    return ac - bc || ay - by;
  });
}

// Chat copilot is out of service for now: flip to true to show it again.
const COPILOT_ENABLED = false;

export const Route = createFileRoute("/orario")({
  head: () => ({
    meta: [
      { title: "Orario settimanale · Generazione e conflitti" },
      {
        name: "description",
        content:
          "Tabellone classi × ore, punteggio di qualità, deroghe rapide, approvazione ed esportazione PDF.",
      },
      { property: "og:title", content: "Orario settimanale · Generazione e conflitti" },
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

// Fields each quick action's dialog collects, and which the backend deroga
// actually scopes by (see app/domain/solver.py _deroga_active call sites) -
// leaving a select on its "Tutti/e" default applies the deroga school-wide,
// same as the old unscoped buttons did.
type QuickActionField = "classe" | "docente" | "giorno" | "max_hours";

const QUICK_ACTIONS: {
  action_type: string;
  label: string;
  description: string;
  fields: QuickActionField[];
  maxHoursLabel?: string;
  maxHoursDefault?: number;
  maxHoursPlaceholder?: string;
}[] = [
  {
    action_type: "force_3_hours_theory",
    label: "Forza ore teoria",
    description:
      "Di norma non si superano 2 ore consecutive di teoria dello stesso docente sulla stessa classe. Qui puoi autorizzare un tetto più alto per tutta la settimana.",
    fields: ["classe", "docente", "max_hours"],
    maxHoursLabel: "Ore consecutive massime",
    maxHoursDefault: 3,
  },
  {
    action_type: "reduce_contract_hours",
    label: "Riduci ore docente a contratto",
    description:
      "Abbassa il monte ore target di questa settimana per un docente a contratto.",
    fields: ["docente", "max_hours"],
    maxHoursLabel: "Ore massime questa settimana",
    maxHoursPlaceholder: "Vuoto = dimezza il target",
  },
  {
    action_type: "authorize_early_exit",
    label: "Autorizza uscita anticipata",
    description:
      "Permette a un docente a contratto di avere buchi orari (uscire e rientrare) invece di un blocco continuo.",
    fields: ["docente"],
  },
  {
    action_type: "override_availability",
    label: "Deroga disponibilità",
    description: "Ignora, solo per questa settimana, la disponibilità dichiarata dal docente.",
    fields: ["docente"],
  },
  {
    action_type: "authorize_single_classe_day",
    label: "Autorizza giornata mono-classe",
    description: "Permette a un docente di passare un'intera giornata su una sola classe.",
    fields: ["docente", "classe", "giorno"],
  },
  {
    action_type: "authorize_friday_late_start",
    label: "Autorizza inizio posticipato di venerdì",
    description: "Permette a una classe di non iniziare alle 8:00 il venerdì.",
    fields: ["classe"],
  },
  {
    action_type: "authorize_short_pratica_block",
    label: "Autorizza blocco pratica corto",
    description:
      "Permette un blocco di laboratorio più corto di 3 ore, o non contiguo, per una classe.",
    fields: ["classe"],
  },
];

// generate/regenerate, modify-slot and apply-quick-action all reply with
// HTTP 200 even when the requested change is rejected (a locked schedule, a
// broken pairing constraint, an unassigned teacher, ...) - the body is then
// {"status": "error", "message": "..."} instead of a real Schedule. Every
// caller must check for that shape before treating the response as a
// Schedule to display, or a rejection crashes the whole page (active.slots
// is not iterable) instead of showing the backend's own error message.
type ScheduleMutationResult = Schedule & {
  status?: string;
  message?: string;
  conflicting_constraints?: string[];
  suggested_deroghe?: string[];
};

// "infeasible" and "timeout" also come back as HTTP 200 with no slots, so
// the check is on the shape (no slots array), not only on status === "error".
function requireSchedule(res: ScheduleMutationResult): Schedule {
  if (res.status === "error" || !Array.isArray(res.slots)) {
    const parts = [res.message ?? "Operazione non riuscita"];
    if (res.conflicting_constraints?.length) {
      parts.push(`Conflitti: ${res.conflicting_constraints.join("; ")}`);
    }
    if (res.suggested_deroghe?.length) {
      parts.push(`Deroghe suggerite: ${res.suggested_deroghe.join(", ")}`);
    }
    throw new Error(parts.join(" "));
  }
  return res;
}

// The red cell the admin clicked: `chiavi` are the conflicts it belongs to,
// the rest locates the hour (classe/giorno/ora) for "reject".
// A free hour the admin clicked, to assign a lesson to it by hand.
type FreeCell = { classe_id: string; classe_nome: string; giorno: string; ora: number };

type ConflictSelection = { chiavi: string[]; classe_id: string; giorno: string; ora: number };

function SchedulePage() {
  const [week, setWeek] = useState("");
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<unknown>(null);
  const [highlightTeacher, setHighlightTeacher] = useState<string | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<SlotLezione | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflictSel, setConflictSel] = useState<ConflictSelection | null>(null);
  const [selectedCell, setSelectedCell] = useState<FreeCell | null>(null);

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
      return sortClassi(active.classes.map((c) => ({ id: c.classe_id, nome: c.nome })));
    }
    const seen = new Map<string, string>();
    for (const s of active.slots) seen.set(s.classe_id, s.classe_nome ?? s.classe_id);
    for (const sc of active.stage_cells ?? []) seen.set(sc.classe_id, sc.classe_nome ?? sc.classe_id);
    return sortClassi([...seen].map(([id, nome]) => ({ id, nome })));
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

  // Applies a suggested_action straight from a conflict card, scoped to
  // that conflict's own classe/docente/giorno (unlike the top-bar
  // QuickActionDialog buttons, which default to school-wide unless the
  // admin picks a scope).
  async function applyQuickAction(
    actionType: string,
    opts?: {
      classId?: string | null | undefined;
      teacherId?: string | null | undefined;
      giorno?: string | null | undefined;
    },
  ) {
    try {
      const res = await api<ScheduleMutationResult>(`/api/schedule/${week}/apply-quick-action`, {
        method: "POST",
        body: {
          action_type: actionType,
          class_id: opts?.classId ?? undefined,
          teacher_id: opts?.teacherId ?? undefined,
          giorno: opts?.giorno ?? undefined,
        },
      });
      const updated = requireSchedule(res);
      setSchedule(updated);
      setNotice(`Deroga applicata · nuovo punteggio ${Math.round(updated.quality_score)}`);
    } catch (err) {
      setNotice(apiErrorMessage(err));
    }
  }

  // Approve (the conflicts of the clicked cell go away, the cell turns back
  // to normal) or reject (that lesson is removed and its hour left free).
  async function resolveConflict(kind: "approve" | "reject") {
    if (!conflictSel) return;
    try {
      const res = await api<ScheduleMutationResult>(
        `/api/schedule/${week}/conflicts/${kind}`,
        {
          method: "POST",
          body:
            kind === "approve"
              ? { chiavi: conflictSel.chiavi }
              : {
                  classe_id: conflictSel.classe_id,
                  giorno: conflictSel.giorno,
                  ora_inizio: conflictSel.ora,
                },
        },
      );
      setSchedule(requireSchedule(res));
      setConflictSel(null);
      setSelectedSlot(null);
      setNotice(kind === "approve" ? "Conflitto approvato." : "Ora liberata.");
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
              setConflictSel(null);
              setSelectedCell(null);
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
          selectedCell={selectedCell}
          onCloseCell={() => setSelectedCell(null)}
          onCellAssigned={(s, message) => {
            setSchedule(s);
            setSelectedCell(null);
            setConflictSel(null);
            setNotice(message ? `Lezione assegnata. ${message}` : "Lezione assegnata.");
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
            Lezione
          </span>
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-conflict bg-conflict/20" />
            Conflitto
          </span>
          <span className="flex items-center gap-1.5">
            <i className="size-2.5 rounded-sm border border-unavailable bg-unavailable/20" />
            Docente indisponibile
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
            onSelectSlot={(slot) => {
              setSelectedSlot(slot);
              setSelectedCell(null);
            }}
            conflictSel={conflictSel}
            onSelectConflict={setConflictSel}
            onSelectCell={(cell) => {
              setSelectedCell(cell);
              setSelectedSlot(null);
            }}
          />
        ) : null}

        {active && conflictSel ? (
          <ConflictBand
            conflicts={conflicts.filter((c) => c.chiave && conflictSel.chiavi.includes(c.chiave))}
            onApprove={() => void resolveConflict("approve")}
            onReject={() => void resolveConflict("reject")}
            onClose={() => setConflictSel(null)}
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {QUICK_ACTIONS.map((a) => (
            <QuickActionDialog
              key={a.action_type}
              action={a}
              classi={classi}
              week={week}
              disabled={!active}
              onApplied={(updated, message) => {
                setSchedule(updated);
                setNotice(message);
              }}
              onError={setNotice}
            />
          ))}
        </div>
      </div>
    </AppShell>
  );
}

// Band under the grid for the conflict(s) of the clicked red cell.
function ConflictBand({
  conflicts,
  onApprove,
  onReject,
  onClose,
}: {
  conflicts: Conflict[];
  onApprove: () => void;
  onReject: () => void;
  onClose: () => void;
}) {
  return (
    <div className="glass rounded-2xl border-l-2 border-conflict p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="label-mono text-conflict">Conflitto</div>
          <ul className="mt-1 space-y-1 text-xs">
            {conflicts.length ? (
              conflicts.map((c) => <li key={c.conflict_id}>{c.description}</li>)
            ) : (
              <li className="text-muted-foreground">Nessuna descrizione disponibile.</li>
            )}
          </ul>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="primary" onClick={onApprove} disabled={!conflicts.length}>
            Approva
          </Button>
          <Button onClick={onReject}>Rifiuta</Button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Chiudi"
            className="rounded-md px-2 py-1 text-muted-foreground hover:bg-accent/50"
          >
            ×
          </button>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Approva: il conflitto sparisce e le ore tornano blu. Rifiuta: la lezione viene tolta e
        l&apos;ora resta libera.
      </p>
    </div>
  );
}

function ScheduleTable({
  schedule,
  classi,
  highlightTeacher,
  onHighlightTeacher,
  onSelectSlot,
  conflictSel,
  onSelectConflict,
  onSelectCell,
}: {
  schedule: Schedule;
  classi: { id: string; nome: string }[];
  highlightTeacher: string | null;
  onHighlightTeacher: (id: string | null) => void;
  onSelectSlot: (slot: SlotLezione) => void;
  conflictSel: ConflictSelection | null;
  onSelectConflict: (sel: ConflictSelection | null) => void;
  onSelectCell: (cell: FreeCell | null) => void;
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
  // Empty hours the solver reports as uncovered ("classe_unfilled"): the
  // "Libera" cell is painted red there instead of the neutral dashed box.
  const unfilled = new Set<string>();
  for (const c of schedule.conflicts ?? []) {
    if (c.giorno !== giorno.toUpperCase() || !c.classe_id) continue;
    for (const h of c.ore ?? []) unfilled.add(`${c.classe_id}|${h}`);
  }
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
      <div className="overflow-x-auto">
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
                      const oraNum = Number.parseInt(ora, 10);
                      if (unfilled.has(`${c.id}|${oraNum}`)) {
                        const chiavi = (schedule.conflicts ?? [])
                          .filter(
                            (k) =>
                              k.chiave &&
                              k.classe_id === c.id &&
                              k.giorno === giorno.toUpperCase() &&
                              k.ore?.includes(oraNum),
                          )
                          .map((k) => k.chiave as string);
                        const similar = chiavi.some((k) => conflictSel?.chiavi.includes(k));
                        return (
                          <td key={c.id} className="border-b border-edge px-2 py-2">
                            <button
                              type="button"
                              onClick={() => {
                                onSelectCell({
                                  classe_id: c.id,
                                  classe_nome: c.nome,
                                  giorno: giorno.toUpperCase(),
                                  ora: oraNum,
                                });
                                onSelectConflict({
                                  chiavi,
                                  classe_id: c.id,
                                  giorno: giorno.toUpperCase(),
                                  ora: oraNum,
                                });
                              }}
                              title="Ora non coperta: docenti o monte ore insufficienti"
                              className={`w-full rounded-md border border-conflict bg-conflict/10 px-2 py-1 text-left font-semibold text-conflict ${
                                similar ? "ring-2 ring-conflict" : ""
                              }`}
                            >
                              Scoperta
                            </button>
                          </td>
                        );
                      }
                      return (
                        <td key={c.id} className="border-b border-edge px-2 py-2">
                          <button
                            type="button"
                            onClick={() => {
                              onSelectConflict(null);
                              onSelectCell({
                                classe_id: c.id,
                                classe_nome: c.nome,
                                giorno: giorno.toUpperCase(),
                                ora: oraNum,
                              });
                            }}
                            title="Assegna una lezione a mano"
                            className="w-full rounded-md border border-dashed border-edge bg-card px-2 py-1 text-left text-muted-foreground hover:border-brand"
                          >
                            Libera
                          </button>
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
                    const tone = slot.indisponibile
                      ? "border-unavailable bg-unavailable/15"
                      : slot.conflitto
                        ? "border-conflict bg-conflict/10"
                        : "border-theory bg-theory/10";
                    const dimmed =
                      highlightTeacher && !conflictSel && slot.docente_id !== highlightTeacher
                        ? "opacity-35"
                        : "";
                    // same conflict as the red cell the admin clicked
                    const similar = (slot.conflitto_chiavi ?? []).some((k) =>
                      conflictSel?.chiavi.includes(k),
                    );
                    return (
                      <td
                        key={c.id}
                        colSpan={colSpan}
                        className="border-b border-edge px-2 py-2"
                      >
                        <button
                          type="button"
                          onClick={() => {
                            onSelectSlot(slot);
                            onSelectConflict(
                              slot.conflitto && slot.conflitto_chiavi?.length
                                ? {
                                    chiavi: slot.conflitto_chiavi,
                                    classe_id: slot.classe_id,
                                    giorno: slot.giorno,
                                    ora: slot.ora_inizio,
                                  }
                                : null,
                            );
                          }}
                          title={`Monte ore residuo non disponibile senza backend`}
                          className={`w-full rounded-md border-l-2 px-2 py-1 text-left transition-opacity ${tone} ${dimmed} ${
                            similar ? "ring-2 ring-conflict" : ""
                          }`}
                        >
                          <span
                            role="link"
                            tabIndex={0}
                            // No stopPropagation: a click on the name is a click on
                            // the cell too (conflict band, manual-edit panel), it
                            // just also highlights the docente.
                            onClick={() => {
                              onHighlightTeacher(
                                highlightTeacher === slot.docente_id ? null : slot.docente_id,
                              );
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") onHighlightTeacher(slot.docente_id);
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
  selectedCell,
  onCloseCell,
  onCellAssigned,
}: {
  week: string;
  schedule: Schedule | null;
  conflicts: Conflict[];
  onScheduleUpdate: (s: Schedule) => void;
  onQuickAction: (
    actionType: string,
    opts?: {
      classId?: string | null | undefined;
      teacherId?: string | null | undefined;
      giorno?: string | null | undefined;
    },
  ) => void;
  selectedSlot: SlotLezione | null;
  onCloseSlot: () => void;
  onSlotUpdated: (s: Schedule) => void;
  selectedCell: FreeCell | null;
  onCloseCell: () => void;
  onCellAssigned: (s: Schedule, message?: string) => void;
}) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  return (
    <>
      <div className="flex items-center gap-2 border-b border-edge px-4 py-3">
        <span className="size-2 rounded-full bg-brand" />
        <span className="font-display text-sm font-semibold">Pannello orario</span>
      </div>

      {selectedCell ? (
        <AssignSlotPanel
          key={`${selectedCell.classe_id}|${selectedCell.giorno}|${selectedCell.ora}`}
          week={week}
          cell={selectedCell}
          onClose={onCloseCell}
          onAssigned={onCellAssigned}
        />
      ) : null}

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
                  confirmingId === c.conflict_id ? (
                    <div className="mt-1 flex items-center gap-2 text-[11px]">
                      <span className="text-muted-foreground">
                        Applicare &ldquo;{c.suggested_action.label}&rdquo;?
                      </span>
                      <button
                        type="button"
                        className="font-semibold text-conflict"
                        onClick={() => {
                          setConfirmingId(null);
                          onQuickAction(c.suggested_action!.action_type, {
                            classId: c.classe_id,
                            teacherId: c.docente_id,
                            giorno: c.giorno,
                          });
                        }}
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
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmingId(c.conflict_id)}
                      className="mt-1 text-[11px] font-semibold text-brand"
                    >
                      {c.suggested_action.label}
                    </button>
                  )
                ) : null}
              </div>
            ))
          )}
        </div>
      </div>

      <FeedbackPanel week={week} schedule={schedule} />

      {COPILOT_ENABLED ? (
        <ChatPanel week={week} schedule={schedule} onScheduleUpdate={onScheduleUpdate} />
      ) : null}
    </>
  );
}

// Manual assignment ("forzatura") of a lesson to a free hour: pick one of the
// docente/materia pairs assigned to the classe. Rules that can be relaxed
// end up as conflicts; the backend refuses only what can't be broken.
function AssignSlotPanel({
  week,
  cell,
  onClose,
  onAssigned,
}: {
  week: string;
  cell: FreeCell;
  onClose: () => void;
  onAssigned: (s: Schedule, message?: string) => void;
}) {
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const options = useQuery({
    queryKey: ["assignable", week, cell.classe_id],
    queryFn: () =>
      api<{
        options: {
          docente_id: string;
          docente_nome: string;
          materia_id: string;
          materia_nome: string;
          ore_residue: number;
        }[];
      }>(`/api/schedule/${week}/assignable/${cell.classe_id}`),
    retry: false,
  });

  const list = options.data?.options ?? [];
  const selected = choice || (list[0] ? `${list[0].docente_id}|${list[0].materia_id}` : "");

  async function submit() {
    const [docente_id, materia_id] = selected.split("|");
    setBusy(true);
    setError(null);
    try {
      const res = await api<ScheduleMutationResult>(`/api/schedule/${week}/assign-slot`, {
        method: "POST",
        body: {
          classe_id: cell.classe_id,
          giorno: cell.giorno,
          ora_inizio: cell.ora,
          docente_id,
          materia_id,
        },
      });
      onAssigned(requireSchedule(res), res.message);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border-b border-edge px-4 py-3">
      <div className="flex items-center">
        <span className="label-mono">Assegna ora libera</span>
        <button type="button" onClick={onClose} className="ml-auto text-[11px] text-muted-foreground">
          Chiudi
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {cell.classe_nome} · {GIORNI.find((g) => g.value === cell.giorno)?.label ?? cell.giorno} ·{" "}
        {String(cell.ora).padStart(2, "0")}:00
      </p>
      <Select label="Docente e materia" value={selected} onChange={(e) => setChoice(e.target.value)}>
        {list.map((o) => (
          <option key={`${o.docente_id}|${o.materia_id}`} value={`${o.docente_id}|${o.materia_id}`}>
            {o.docente_nome} · {o.materia_nome} ({o.ore_residue}h residue)
          </option>
        ))}
      </Select>
      {options.isError ? <p className="text-[11px] text-conflict">{apiErrorMessage(options.error)}</p> : null}
      {error ? <p className="text-[11px] text-conflict">{apiErrorMessage(error)}</p> : null}
      <Button variant="primary" className="w-full" onClick={submit} disabled={busy || !selected}>
        {busy ? "Assegno…" : "Forza assegnazione"}
      </Button>
    </div>
  );
}

function QuickActionDialog({
  action,
  classi,
  week,
  disabled,
  onApplied,
  onError,
}: {
  action: (typeof QUICK_ACTIONS)[number];
  classi: { id: string; nome: string }[];
  week: string;
  disabled: boolean;
  onApplied: (schedule: Schedule, message: string) => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [classeId, setClasseId] = useState("");
  const [docenteId, setDocenteId] = useState("");
  const [giorno, setGiorno] = useState("");
  const [maxHours, setMaxHours] = useState(action.maxHoursDefault ? String(action.maxHoursDefault) : "");
  const [busy, setBusy] = useState(false);

  const teachers = useQuery({
    queryKey: ["teachers"],
    queryFn: () => api<Teacher[]>("/api/teachers"),
    enabled: open && action.fields.includes("docente"),
    retry: false,
  });

  function reset() {
    setClasseId("");
    setDocenteId("");
    setGiorno("");
    setMaxHours(action.maxHoursDefault ? String(action.maxHoursDefault) : "");
  }

  async function submit() {
    setBusy(true);
    try {
      const res = await api<ScheduleMutationResult>(`/api/schedule/${week}/apply-quick-action`, {
        method: "POST",
        body: {
          action_type: action.action_type,
          class_id: classeId || undefined,
          teacher_id: docenteId || undefined,
          giorno: giorno || undefined,
          max_hours: maxHours ? Number(maxHours) : undefined,
        },
      });
      const updated = requireSchedule(res);
      onApplied(updated, `Deroga applicata · nuovo punteggio ${Math.round(updated.quality_score)}`);
      setOpen(false);
      reset();
    } catch (err) {
      onError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button disabled={disabled}>{action.label}</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{action.label}</DialogTitle>
          <DialogDescription>{action.description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {action.fields.includes("classe") ? (
            <Select label="Classe" value={classeId} onChange={(e) => setClasseId(e.target.value)}>
              <option value="">Tutte le classi</option>
              {classi.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nome}
                </option>
              ))}
            </Select>
          ) : null}
          {action.fields.includes("docente") ? (
            <Select label="Docente" value={docenteId} onChange={(e) => setDocenteId(e.target.value)}>
              <option value="">Tutti i docenti</option>
              {(teachers.data ?? []).map((t) => (
                <option key={t.teacher_id} value={t.teacher_id}>
                  {t.nome}
                </option>
              ))}
            </Select>
          ) : null}
          {action.fields.includes("giorno") ? (
            <Select label="Giorno" value={giorno} onChange={(e) => setGiorno(e.target.value)}>
              <option value="">Tutta la settimana</option>
              {GIORNI.map(({ value, label }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          ) : null}
          {action.fields.includes("max_hours") ? (
            <Field
              label={action.maxHoursLabel ?? "Ore massime"}
              type="number"
              min={1}
              value={maxHours}
              onChange={(e) => setMaxHours(e.target.value)}
              placeholder={action.maxHoursPlaceholder}
            />
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
            Annulla
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {busy ? "Applico…" : "Applica e ricalcola"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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

// Admin rating of the generated schedule (1-5) plus the reasons it went
// wrong. Only collected for now (append-only, see OrarioFeedback on the
// backend); nothing feeds back into the solver yet.
function FeedbackPanel({ week, schedule }: { week: string; schedule: Schedule | null }) {
  const [voto, setVoto] = useState(0);
  const [motivi, setMotivi] = useState<string[]>([]);
  const [nota, setNota] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const feedback = useQuery({
    queryKey: ["feedback", week, schedule?.quality_score ?? null],
    queryFn: () => api<ScheduleFeedbackData>(`/api/schedule/${week}/feedback`),
    enabled: Boolean(week && schedule),
    retry: false,
  });

  if (!schedule) return null;

  const current = feedback.data?.current ?? null;
  const labels = new Map((feedback.data?.motivi_disponibili ?? []).map((m) => [m.code, m.label]));
  // The rating snapshots the score it was given to: a different score now
  // means the week was regenerated/edited since.
  const outdated = current !== null && current.quality_score !== schedule.quality_score;

  async function save() {
    if (!voto) return;
    setSaving(true);
    setMessage(null);
    try {
      await api(`/api/schedule/${week}/feedback`, {
        method: "POST",
        body: { voto, motivi, nota: nota.trim() || null },
      });
      setVoto(0);
      setMotivi([]);
      setNota("");
      setMessage("Valutazione salvata.");
      await feedback.refetch();
    } catch (err) {
      setMessage(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="border-t border-edge p-4 text-xs">
      <div className="font-display text-sm font-semibold">Valuta questo orario</div>

      {current ? (
        <p className="mt-1 text-[11px] text-muted-foreground">
          Ultimo voto: {"★".repeat(current.voto)}
          {"☆".repeat(5 - current.voto)}
          {current.motivi.length
            ? ` · ${current.motivi.map((m) => labels.get(m) ?? m).join(", ")}`
            : ""}
          {outdated ? " (riferito a una versione precedente dell'orario)" : ""}
        </p>
      ) : null}

      <div className="mt-2 flex gap-1" role="radiogroup" aria-label="Voto">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={voto === n}
            aria-label={`${n} su 5`}
            onClick={() => setVoto(n)}
            className={`text-xl leading-none ${n <= voto ? "text-warn" : "text-muted-foreground/40"}`}
          >
            ★
          </button>
        ))}
      </div>

      {voto > 0 ? (
        <>
          <p className="mt-3 text-[11px] text-muted-foreground">
            {voto <= 3 ? "Cosa non va?" : "Qualcosa da migliorare?"} (facoltativo)
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(feedback.data?.motivi_disponibili ?? []).map((m) => {
              const on = motivi.includes(m.code);
              return (
                <button
                  key={m.code}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    setMotivi((cur) => (on ? cur.filter((c) => c !== m.code) : [...cur, m.code]))
                  }
                  className={`rounded-full px-2.5 py-1 text-[11px] ring-1 ${
                    on
                      ? "bg-brand text-primary-foreground ring-brand"
                      : "bg-background text-foreground/80 ring-edge"
                  }`}
                >
                  {m.label}
                </button>
              );
            })}
          </div>
          <textarea
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            maxLength={2000}
            rows={2}
            placeholder="Note (facoltative)…"
            className="mt-2 w-full resize-none rounded-xl bg-background px-3 py-2 text-xs outline-none ring-1 ring-edge placeholder:text-muted-foreground"
          />
          <Button variant="primary" className="mt-2" onClick={() => void save()} disabled={saving}>
            {saving ? "Salvo…" : "Salva valutazione"}
          </Button>
        </>
      ) : null}

      {message ? <p className="mt-2 text-[11px] text-muted-foreground">{message}</p> : null}
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
