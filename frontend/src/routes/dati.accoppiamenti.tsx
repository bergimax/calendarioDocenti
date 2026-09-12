import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field } from "@/components/ui-kit";
import type { ClassPairing } from "@/lib/types";

export const Route = createFileRoute("/dati/accoppiamenti")({
  component: PairingsPage,
});

function PairingsPage() {
  return (
    <CrudTable<ClassPairing & Record<string, unknown>>
      title="Accoppiamenti classi"
      endpoint="/api/class-pairings"
      idKey="pairing_id"
      emptyHint="Nessun accoppiamento restituito dal server."
      columns={[
        { key: "a", header: "Classe A", render: (r) => r.classe_a_id },
        { key: "b", header: "Classe B", render: (r) => r.classe_b_id },
        { key: "materia", header: "Materia comune", render: (r) => r.materia_id },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Classe A (ID)"
            value={value["classe_a_id"] ?? ""}
            onChange={(e) => set("classe_a_id", e.target.value)}
          />
          <Field
            label="Classe B (ID)"
            value={value["classe_b_id"] ?? ""}
            onChange={(e) => set("classe_b_id", e.target.value)}
          />
          <Field
            label="Materia comune (ID)"
            value={value["materia_id"] ?? ""}
            onChange={(e) => set("materia_id", e.target.value)}
          />
        </>
      )}
    />
  );
}
