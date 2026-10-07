import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { classeSortValue } from "@/lib/classi";
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
      newTitle="Nuova classe"
      emptyHint="Nessuna classe restituita dal server."
      defaultSort="nome"
      columns={[
        { key: "nome", header: "Classe", render: (r) => r.nome, sortValue: (r) => classeSortValue(r.nome) },
      ]}
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
