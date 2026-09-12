import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import type { Subject } from "@/lib/types";

export const Route = createFileRoute("/dati/materie")({
  component: SubjectsPage,
});

function SubjectsPage() {
  return (
    <CrudTable<Subject & Record<string, unknown>>
      title="Materie"
      endpoint="/api/subjects"
      idKey="materia_id"
      emptyHint="Nessuna materia restituita dal server."
      columns={[
        { key: "nome", header: "Materia", render: (r) => r.nome },
        {
          key: "tipologia",
          header: "Tipologia",
          render: (r) => (r.tipologia === "PRATICA" ? "Pratica" : "Teoria"),
        },
        { key: "peso", header: "Peso cognitivo", render: (r) => r.peso_cognitivo ?? "—" },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Nome"
            value={value["nome"] ?? ""}
            onChange={(e) => set("nome", e.target.value)}
          />
          <Select
            label="Tipologia"
            value={value["tipologia"] ?? "TEORIA"}
            onChange={(e) => set("tipologia", e.target.value)}
          >
            <option value="TEORIA">Teoria</option>
            <option value="PRATICA">Pratica</option>
          </Select>
          <Select
            label="Peso cognitivo"
            value={value["peso_cognitivo"] ?? "MEDIO"}
            onChange={(e) => set("peso_cognitivo", e.target.value)}
          >
            <option value="ALTO">Alto</option>
            <option value="MEDIO">Medio</option>
            <option value="BASSO">Basso</option>
          </Select>
        </>
      )}
    />
  );
}
