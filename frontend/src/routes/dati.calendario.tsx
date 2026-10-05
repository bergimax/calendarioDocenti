import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { useQuery } from "@tanstack/react-query";
import { Field, Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import type { CalendarEntry, SchoolClass } from "@/lib/types";

export const Route = createFileRoute("/dati/calendario")({
  component: CalendarPage,
});

function CalendarPage() {
  const classes = useQuery({ queryKey: ["/api/classes"], queryFn: () => api<SchoolClass[]>("/api/classes") });
  return (
    <CrudTable<CalendarEntry & Record<string, unknown>>
      title="Calendario annuale"
      endpoint="/api/calendar"
      idKey="date_id"
      emptyHint="Nessuna data restituita dal server."
      columns={[
        { key: "data", header: "Data", render: (r) => r.data },
        { key: "gruppo", header: "Gruppo", render: (r) => r.gruppo ?? "tutte le classi" },
        { key: "ore", header: "Ore max", render: (r) => r.ore_max_giornata },
        {
          key: "ora_inizio_min",
          header: "Ingresso non prima di",
          render: (r) => (r.ora_inizio_min ? `${r.ora_inizio_min}:00` : "8:00"),
        },
        { key: "chiusura", header: "Chiusura", render: (r) => (r.flag_chiusura ? "Sì" : "No") },
        {
          key: "stage_gruppo",
          header: "Stage gruppo",
          render: (r) => (r.flag_stage_gruppo ? "Sì" : "No"),
        },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Data"
            type="date"
            value={value["data"] ?? ""}
            onChange={(e) => set("data", e.target.value)}
          />
          <Field
            label="Gruppo (vuoto = tutte le classi)"
            value={value["gruppo"] ?? ""}
            onChange={(e) => set("gruppo", e.target.value)}
            placeholder="es. PRIME, SECONDE, TERZE, QUARTE"
          />
          <Select
            label="Ore max giornata"
            value={value["ore_max_giornata"] ?? "5"}
            onChange={(e) => set("ore_max_giornata", e.target.value)}
          >
            <option value="4">4</option>
            <option value="5">5</option>
            <option value="6">6</option>
          </Select>
          <Select
            label="Ingresso non prima di"
            value={value["ora_inizio_min"] ?? ""}
            onChange={(e) => set("ora_inizio_min", e.target.value)}
          >
            <option value="">8:00 (nessun vincolo)</option>
            <option value="9">9:00</option>
            <option value="10">10:00</option>
            <option value="11">11:00</option>
            <option value="12">12:00</option>
            <option value="13">13:00</option>
          </Select>
          <Select
            label="Chiusura"
            value={value["flag_chiusura"] ?? "false"}
            onChange={(e) => set("flag_chiusura", e.target.value)}
          >
            <option value="false">No</option>
            <option value="true">Sì</option>
          </Select>
          <Select
            label="Tutto il gruppo in stage"
            value={value["flag_stage_gruppo"] ?? "false"}
            onChange={(e) => set("flag_stage_gruppo", e.target.value)}
          >
            <option value="false">No</option>
            <option value="true">Sì (richiede Gruppo impostato sopra)</option>
          </Select>
          <Select
            label="Singola classe in stage (alternativa a Gruppo)"
            value={value["flag_stage_classe_id"] ?? ""}
            onChange={(e) => set("flag_stage_classe_id", e.target.value)}
          >
            <option value="">Nessuna</option>
            {(classes.data ?? []).map((c) => (
              <option key={c.classe_id} value={c.classe_id}>
                {c.nome}
              </option>
            ))}
          </Select>
        </>
      )}
    />
  );
}
