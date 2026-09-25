import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field } from "@/components/ui-kit";
import type { SchoolClass } from "@/lib/types";

export const Route = createFileRoute("/dati/classi")({
  component: ClassesPage,
});

function ClassesPage() {
  return (
    <CrudTable<SchoolClass & Record<string, unknown>>
      title="Classi"
      endpoint="/api/classes"
      idKey="classe_id"
      emptyHint="Nessuna classe restituita dal server."
      columns={[{ key: "nome", header: "Classe", render: (r) => r.nome }]}
      form={({ value, set }) => (
        <>
          <Field
            label="Nome classe"
            value={value["nome"] ?? ""}
            onChange={(e) => set("nome", e.target.value)}
            placeholder="1A"
          />
        </>
      )}
    />
  );
}
