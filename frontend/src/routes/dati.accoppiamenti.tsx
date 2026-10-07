import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CrudTable } from "@/components/CrudTable";
import { Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import type { ClassPairing, SchoolClass, Teacher } from "@/lib/types";

export const Route = createFileRoute("/dati/accoppiamenti")({
  component: PairingsPage,
});

function PairingsPage() {
  const classes = useQuery({ queryKey: ["/api/classes"], queryFn: () => api<SchoolClass[]>("/api/classes") });
  const teachers = useQuery({ queryKey: ["/api/teachers"], queryFn: () => api<Teacher[]>("/api/teachers") });

  const className = (id: unknown) =>
    classes.data?.find((c) => c.classe_id === id)?.nome ?? String(id ?? "—");
  const teacherName = (id: unknown) =>
    teachers.data?.find((t) => t.teacher_id === id)?.nome ?? (id ? String(id) : "—");

  return (
    <CrudTable<ClassPairing & Record<string, unknown>>
      title="Accoppiamenti classi"
      endpoint="/api/class-pairings"
      idKey="pairing_id"
      newTitle="Nuovo accoppiamento"
      emptyHint="Nessun accoppiamento restituito dal server."
      columns={[
        { key: "a", header: "Classe A", render: (r) => className(r.classe_a_id) },
        { key: "b", header: "Classe B", render: (r) => className(r.classe_b_id) },
        { key: "docente", header: "Docente", render: (r) => teacherName(r.docente_id) },
      ]}
      form={({ value, set }) => (
        <>
          <Select
            label="Classe A"
            value={value["classe_a_id"] ?? ""}
            onChange={(e) => set("classe_a_id", e.target.value)}
          >
            <option value="">Seleziona…</option>
            {(classes.data ?? []).map((c) => (
              <option key={c.classe_id} value={c.classe_id}>
                {c.nome}
              </option>
            ))}
          </Select>
          <Select
            label="Classe B"
            value={value["classe_b_id"] ?? ""}
            onChange={(e) => set("classe_b_id", e.target.value)}
          >
            <option value="">Seleziona…</option>
            {(classes.data ?? []).map((c) => (
              <option key={c.classe_id} value={c.classe_id}>
                {c.nome}
              </option>
            ))}
          </Select>
          <Select
            label="Docente"
            value={value["docente_id"] ?? ""}
            onChange={(e) => set("docente_id", e.target.value)}
          >
            <option value="">Nessuno</option>
            {(teachers.data ?? []).map((t) => (
              <option key={t.teacher_id} value={t.teacher_id}>
                {t.nome}
              </option>
            ))}
          </Select>
        </>
      )}
    />
  );
}
