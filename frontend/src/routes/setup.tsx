import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Badge, Button, Field, Select } from "@/components/ui-kit";
import { ErrorState, LoadingState, Panel } from "@/components/States";
import { api, apiErrorMessage } from "@/lib/api";
import type { FileType, UploadResult, ValidationResponse } from "@/lib/types";

export const Route = createFileRoute("/setup")({
  head: () => ({
    meta: [
      { title: "Setup iniziale · Orario scolastico" },
      {
        name: "description",
        content:
          "Caricamento calendario PDF e anagrafiche CSV, validazione automatica e correzioni prima del salvataggio.",
      },
      { property: "og:title", content: "Setup iniziale · Orario scolastico" },
      {
        property: "og:description",
        content: "Carica i file dell'anno formativo e valida i dati estratti.",
      },
    ],
  }),
  component: SetupPage,
});

const FILES: { type: FileType; label: string; endpoint: string; accept: string }[] = [
  { type: "calendario", label: "Calendario PDF", endpoint: "/api/calendar/upload", accept: ".csv,.pdf" },
  { type: "docenti", label: "Docenti CSV", endpoint: "/api/teachers/upload", accept: ".csv" },
  { type: "classi", label: "Classi CSV", endpoint: "/api/classes/upload", accept: ".csv" },
  { type: "materie", label: "Materie CSV", endpoint: "/api/subjects/upload", accept: ".csv" },
  {
    type: "assegnazioni",
    label: "Assegnazioni CSV",
    endpoint: "/api/assignments/upload",
    accept: ".csv",
  },
  {
    type: "accoppiamenti",
    label: "Accoppiamenti CSV",
    endpoint: "/api/class-pairings/upload",
    accept: ".csv",
  },
];

type UploadState = {
  status: "idle" | "uploading" | "done" | "error";
  fileName?: string;
  fileId?: string | undefined;
  message?: string;
};

function SetupPage() {
  const navigate = useNavigate();
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [validating, setValidating] = useState(false);
  const [validationError, setValidationError] = useState<unknown>(null);
  const [correction, setCorrection] = useState<{ fileType: FileType; entity: string } | null>(null);
  const [schoolName, setSchoolName] = useState("");
  const [schoolYear, setSchoolYear] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);

  const fileIds = Object.values(uploads)
    .map((u) => u.fileId)
    .filter((id): id is string => Boolean(id));

  async function upload(type: FileType, endpoint: string, file: File) {
    setUploads((p) => ({ ...p, [type]: { status: "uploading", fileName: file.name } }));
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api<UploadResult>(endpoint, { method: "POST", body: form });
      setUploads((p) => ({
        ...p,
        [type]: { status: "done", fileName: file.name, fileId: res.file_id },
      }));
    } catch (err) {
      setUploads((p) => ({
        ...p,
        [type]: { status: "error", fileName: file.name, message: apiErrorMessage(err) },
      }));
    }
  }

  async function runValidation() {
    setValidating(true);
    setValidationError(null);
    try {
      const res = await api<ValidationResponse>("/api/setup/validate", {
        method: "POST",
        body: { file_ids: fileIds },
      });
      setValidation(res);
    } catch (err) {
      setValidationError(err);
      setValidation(null);
    } finally {
      setValidating(false);
    }
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      // Like /schedule's mutating endpoints, this replies HTTP 200 even when
      // the save is rejected server-side (status: "error", e.g. a DB error) -
      // must check before navigating away as if it had succeeded.
      const res = await api<{ status: string; message?: string }>("/api/setup/save", {
        method: "POST",
        body: {
          file_ids: fileIds,
          corrections_applied: [],
          school_name: schoolName,
          school_year: schoolYear,
        },
      });
      if (res.status === "error") throw new Error(res.message ?? "Salvataggio non riuscito");
      navigate({ to: "/disponibilita" });
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell
      title="Setup iniziale anno"
      subtitle="Caricamento e validazione dati"
      actions={
        <Button variant="solid" onClick={runValidation} disabled={fileIds.length === 0 || validating}>
          {validating ? "Validazione…" : "Procedi alla validazione"}
        </Button>
      }
    >
      <div className="grid max-w-6xl gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Panel title="1 · Caricamento file">
            <div className="grid grid-cols-2 gap-3">
              {FILES.map((f) => {
                const state = uploads[f.type];
                return (
                  <label
                    key={f.type}
                    className="cursor-pointer rounded-xl border border-dashed border-edge bg-card/60 p-3 transition-colors hover:border-brand/50"
                  >
                    <input
                      type="file"
                      accept={f.accept}
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void upload(f.type, f.endpoint, file);
                      }}
                    />
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold">{f.label}</span>
                      {state?.status === "done" ? (
                        <Badge tone="ok">Caricato</Badge>
                      ) : state?.status === "uploading" ? (
                        <Badge tone="brand">Invio…</Badge>
                      ) : state?.status === "error" ? (
                        <Badge tone="conflict">Errore</Badge>
                      ) : (
                        <Badge>Vuoto</Badge>
                      )}
                    </div>
                    <p className="mt-1 truncate text-[11px] text-muted-foreground">
                      {state?.fileName ?? "Trascina o clicca per selezionare"}
                    </p>
                    {state?.status === "error" ? (
                      <p className="mt-1 text-[11px] text-conflict">{state.message}</p>
                    ) : null}
                  </label>
                );
              })}
            </div>
          </Panel>

          <Panel title="2 · Validazione e anteprima">
            {validating ? <LoadingState label="Analisi dei file in corso…" /> : null}
            {validationError ? (
              <ErrorState
                error={validationError}
                onRetry={runValidation}
                context="Validazione non riuscita"
              />
            ) : null}
            {!validating && !validationError && !validation ? (
              <p className="text-xs text-muted-foreground">
                Carica i file e avvia la validazione per vedere l'anteprima dei dati estratti.
              </p>
            ) : null}
            {validation ? (
              <div className="space-y-3">
                {Object.entries(validation.results).map(([type, result]) => (
                  <div key={type} className="rounded-xl border border-edge bg-card p-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold capitalize">{type}</span>
                      {result?.success ? <Badge tone="ok">OK</Badge> : <Badge tone="conflict">Errori</Badge>}
                    </div>
                    {result?.preview ? (
                      <div className="mt-2 flex flex-wrap gap-3 font-mono text-[11px] text-muted-foreground">
                        {Object.entries(result.preview).map(([k, v]) => (
                          <span key={k}>
                            {k}: <b className="text-foreground">{String(v)}</b>
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {(result?.warnings ?? []).map((w, i) => (
                      <div
                        key={i}
                        className="mt-2 flex items-center gap-2 rounded-lg bg-warn/10 px-2 py-1.5 text-[11px]"
                      >
                        <span className="flex-1">{w.issue}</span>
                        <button
                          type="button"
                          className="font-semibold text-brand"
                          onClick={() =>
                            setCorrection({
                              fileType: type as FileType,
                              entity: w.entity,
                            })
                          }
                        >
                          Correggi
                        </button>
                      </div>
                    ))}
                    {(result?.errors ?? []).map((e, i) => (
                      <p key={i} className="mt-2 text-[11px] text-conflict">
                        {Object.values(e).join(" · ")}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>

          <ManualCalendar fileId={uploads["calendario"]?.fileId} />
        </div>

        <div className="space-y-4">
          {correction ? (
            <CorrectionForm
              fileType={correction.fileType}
              entity={correction.entity}
              fileId={uploads[correction.fileType]?.fileId}
              onClose={() => setCorrection(null)}
              onApplied={() => {
                setCorrection(null);
                void runValidation();
              }}
            />
          ) : null}

          <Panel title="3 · Conferma e salvataggio">
            <div className="space-y-3">
              <Field
                label="Nome istituto"
                value={schoolName}
                onChange={(e) => setSchoolName(e.target.value)}
                placeholder="Istituto XYZ"
              />
              <Field
                label="Anno formativo"
                value={schoolYear}
                onChange={(e) => setSchoolYear(e.target.value)}
                placeholder="2026-2027"
              />
              <div className="rounded-lg bg-muted p-3 font-mono text-[11px] text-muted-foreground">
                File caricati: {fileIds.length}/6 · Stato:{" "}
                {validation?.overall_status ?? "non validato"}
              </div>
              {saveError ? <ErrorState error={saveError} context="Salvataggio non riuscito" /> : null}
              <Button
                variant="primary"
                className="w-full"
                disabled={!validation?.can_proceed || saving}
                onClick={save}
              >
                {saving ? "Salvataggio…" : "Salva e inizia"}
              </Button>
            </div>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}

function CorrectionForm({
  fileType,
  entity,
  fileId,
  onClose,
  onApplied,
}: {
  fileType: FileType;
  entity: string;
  fileId?: string | undefined;
  onClose: () => void;
  onApplied: () => void;
}) {
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function checkField(next: string) {
    setValue(next);
    if (!field || !next) return;
    try {
      const res = await api<{ valid: boolean; message: string }>("/api/setup/validate-field", {
        method: "POST",
        body: { file_type: fileType, entity, field, new_value: next },
      });
      setFeedback(res.message);
    } catch (err) {
      setFeedback(apiErrorMessage(err));
    }
  }

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      await api("/api/setup/apply-correction", {
        method: "POST",
        body: { file_id: fileId, correction: { field, entity, new_value: value } },
      });
      onApplied();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Correzione dato"
      action={
        <button type="button" onClick={onClose} className="text-[11px] text-muted-foreground">
          Chiudi
        </button>
      }
    >
      <div className="space-y-3">
        <p className="font-mono text-[11px] text-muted-foreground">
          {fileType} · {entity}
        </p>
        <Field label="Campo" value={field} onChange={(e) => setField(e.target.value)} placeholder="email" />
        <Field
          label="Nuovo valore"
          value={value}
          onChange={(e) => void checkField(e.target.value)}
          placeholder="nome@scuola.it"
        />
        {feedback ? <p className="text-[11px] text-muted-foreground">{feedback}</p> : null}
        {error ? <ErrorState error={error} context="Correzione non applicata" /> : null}
        <Button variant="primary" className="w-full" disabled={busy} onClick={apply}>
          {busy ? "Applico…" : "Salva correzione"}
        </Button>
      </div>
    </Panel>
  );
}

function ManualCalendar({ fileId }: { fileId?: string | undefined }) {
  const [data, setData] = useState("");
  const [ore, setOre] = useState("5");
  const [chiusura, setChiusura] = useState(false);
  const [stageClasse, setStageClasse] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ total_dates_loaded: number }>("/api/calendar/add-date-manual", {
        method: "POST",
        body: {
          file_id: fileId,
          date: data,
          ore_max_giornata: Number(ore),
          flag_chiusura: chiusura,
          flag_stage_classe_id: stageClasse || null,
        },
      });
      setMsg(`Data aggiunta · totale ${res.total_dates_loaded}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Inserimento manuale calendario (fallback OCR)">
      <div className="grid grid-cols-4 items-end gap-3">
        <Field label="Data" type="date" value={data} onChange={(e) => setData(e.target.value)} />
        <Select label="Ore max giornata" value={ore} onChange={(e) => setOre(e.target.value)}>
          <option value="4">4</option>
          <option value="5">5</option>
          <option value="6">6</option>
        </Select>
        <Field
          label="Classe in stage (ID)"
          value={stageClasse}
          onChange={(e) => setStageClasse(e.target.value)}
          placeholder="cl_1a"
        />
        <label className="flex items-center gap-2 pb-2 text-xs">
          <input
            type="checkbox"
            checked={chiusura}
            onChange={(e) => setChiusura(e.target.checked)}
          />
          Chiusura
        </label>
      </div>
      {msg ? <p className="mt-2 text-[11px] text-ok">{msg}</p> : null}
      {error ? (
        <div className="mt-2">
          <ErrorState error={error} context="Data non aggiunta" />
        </div>
      ) : null}
      <Button className="mt-3" onClick={add} disabled={busy || !data}>
        {busy ? "Aggiungo…" : "+ Aggiungi data"}
      </Button>
    </Panel>
  );
}
