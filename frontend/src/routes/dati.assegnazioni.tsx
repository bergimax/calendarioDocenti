import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field } from "@/components/ui-kit";
import type { Assignment } from "@/lib/types";

export const Route = createFileRoute("/dati/assegnazioni")({
  component: AssignmentsPage,
});

function AssignmentsPage() {
  return (
    <CrudTable<Assignment & Record<string, unknown>>
      title="Assegnazioni e monte ore"
      endpoint="/api/assignments"
      idKey="assignment_id"
      emptyHint="Nessuna assegnazione restituita dal server."
      columns={[
        { key: "docente", header: "Docente", render: (r) => r.docente_id },
        { key: "classe", header: "Classe", render: (r) => r.classe_id },
        { key: "materia", header: "Materia", render: (r) => r.materia_id },
        {
          key: "ore",
          header: "Ore",
          render: (r) => `${r.ore_erogate ?? 0} / ${r.ore_totali}`,
        },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Docente (ID)"
            value={value["docente_id"] ?? ""}
            onChange={(e) => set("docente_id", e.target.value)}
          />
          <Field
            label="Classe (ID)"
            value={value["classe_id"] ?? ""}
            onChange={(e) => set("classe_id", e.target.value)}
          />
          <Field
            label="Materia (ID)"
            value={value["materia_id"] ?? ""}
            onChange={(e) => set("materia_id", e.target.value)}
          />
          <Field
            label="Ore totali"
            type="number"
            value={value["ore_totali"] ?? ""}
            onChange={(e) => set("ore_totali", e.target.value)}
          />
        </>
      )}
    />
  );
}
