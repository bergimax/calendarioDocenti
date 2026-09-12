import { createFileRoute } from "@tanstack/react-router";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import type { Teacher } from "@/lib/types";

export const Route = createFileRoute("/dati/docenti")({
  component: TeachersPage,
});

function TeachersPage() {
  return (
    <CrudTable<Teacher & Record<string, unknown>>
      title="Docenti"
      endpoint="/api/teachers"
      idKey="teacher_id"
      emptyHint="Nessun docente restituito dal server."
      columns={[
        { key: "nome", header: "Nome", render: (r) => r.nome },
        { key: "email", header: "Email", render: (r) => r.email },
        {
          key: "tipo",
          header: "Tipo",
          render: (r) => (r.tipo === "ASSUNTO" ? "Assunto" : "Contrattista"),
        },
      ]}
      form={({ value, set }) => (
        <>
          <Field
            label="Nome"
            value={value["nome"] ?? ""}
            onChange={(e) => set("nome", e.target.value)}
          />
          <Field
            label="Email"
            value={value["email"] ?? ""}
            onChange={(e) => set("email", e.target.value)}
          />
          <Select
            label="Tipo"
            value={value["tipo"] ?? "ASSUNTO"}
            onChange={(e) => set("tipo", e.target.value)}
          >
            <option value="ASSUNTO">Assunto</option>
            <option value="CONTRATTISTA">Contrattista</option>
          </Select>
        </>
      )}
    />
  );
}
