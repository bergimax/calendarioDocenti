import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import type { CalendarEntry } from "@/lib/types";

export const Route = createFileRoute("/dati/calendario")({
  component: CalendarPage,
});

function CalendarPage() {
  return (
    <CrudTable<CalendarEntry & Record<string, unknown>>
      title="Calendario annuale"
      endpoint="/api/calendar"
      idKey="date_id"
      emptyHint="Nessuna data restituita dal server."
      columns={[
        { key: "data", header: "Data", render: (r) => r.data },
        { key: "ore", header: "Ore max", render: (r) => r.ore_max_giornata },
        { key: "chiusura", header: "Chiusura", render: (r) => (r.flag_chiusura ? "Sì" : "No") },
        { key: "stage", header: "Stage classe", render: (r) => r.stage_classe_id ?? "—" },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Data"
            type="date"
            value={value["data"] ?? ""}
            onChange={(e) => set("data", e.target.value)}
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
            label="Chiusura"
            value={value["flag_chiusura"] ?? "false"}
            onChange={(e) => set("flag_chiusura", e.target.value)}
          >
            <option value="false">No</option>
            <option value="true">Sì</option>
          </Select>
          <Field
            label="Classe in stage (ID)"
            value={value["stage_classe_id"] ?? ""}
            onChange={(e) => set("stage_classe_id", e.target.value)}
          />
        </>
      )}
    />
  );
}
