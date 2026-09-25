import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import type { Assignment, SchoolClass, Teacher } from "@/lib/types";

export const Route = createFileRoute("/dati/assegnazioni")({
  component: AssignmentsPage,
});

function AssignmentsPage() {
  const teachers = useQuery({ queryKey: ["/api/teachers"], queryFn: () => api<Teacher[]>("/api/teachers") });
  const classes = useQuery({ queryKey: ["/api/classes"], queryFn: () => api<SchoolClass[]>("/api/classes") });

  const teacherName = (id: unknown) =>
    teachers.data?.find((t) => t.teacher_id === id)?.nome ?? String(id ?? "—");
  const className = (id: unknown) =>
    classes.data?.find((c) => c.classe_id === id)?.nome ?? String(id ?? "—");

  return (
    <CrudTable<Assignment & Record<string, unknown>>
      title="Assegnazioni e monte ore"
      endpoint="/api/assignments"
      idKey="assignment_id"
      emptyHint="Nessuna assegnazione restituita dal server."
      columns={[
        { key: "docente", header: "Docente", render: (r) => teacherName(r.docente_id) },
        { key: "classe", header: "Classe", render: (r) => className(r.classe_id) },
        {
          key: "ore",
          header: "Ore",
          render: (r) => `${r.ore_erogate ?? 0} / ${r.ore_totali}`,
        },
      ]}
      form={({ value, set }) => (
        <>
          <Select
            label="Docente"
            value={value["docente_id"] ?? ""}
            onChange={(e) => set("docente_id", e.target.value)}
          >
            <option value="">Seleziona…</option>
            {(teachers.data ?? []).map((t) => (
              <option key={t.teacher_id} value={t.teacher_id}>
                {t.nome}
              </option>
            ))}
          </Select>
          <Select
            label="Classe"
            value={value["classe_id"] ?? ""}
            onChange={(e) => set("classe_id", e.target.value)}
          >
            <option value="">Seleziona…</option>
            {(classes.data ?? []).map((c) => (
              <option key={c.classe_id} value={c.classe_id}>
                {c.nome}
              </option>
            ))}
          </Select>
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
