import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import type { Assignment, ClassPairing, SchoolClass, Teacher } from "@/lib/types";

export const Route = createFileRoute("/dati/assegnazioni")({
  component: AssignmentsPage,
});

function AssignmentsPage() {
  const teachers = useQuery({ queryKey: ["/api/teachers"], queryFn: () => api<Teacher[]>("/api/teachers") });
  const classes = useQuery({ queryKey: ["/api/classes"], queryFn: () => api<SchoolClass[]>("/api/classes") });

  const pairings = useQuery({
    queryKey: ["/api/class-pairings"],
    queryFn: () => api<ClassPairing[]>("/api/class-pairings"),
  });

  const teacherName = (id: unknown) =>
    teachers.data?.find((t) => t.teacher_id === id)?.nome ?? String(id ?? "—");
  const className = (id: unknown) =>
    classes.data?.find((c) => c.classe_id === id)?.nome ?? String(id ?? "—");

  // Una coppia è una sola riga (mostrata sulla assegnazione con id minore); il
  // backend applica modifiche ed eliminazione a entrambe le classi.
  const isSecondOfPair = (r: Assignment) =>
    Boolean(r.partner_assignment_id) && r.assignment_id > (r.partner_assignment_id ?? "");

  return (
    <CrudTable<Assignment & Record<string, unknown>>
      title="Assegnazioni e monte ore"
      endpoint="/api/assignments"
      idKey="assignment_id"
      newTitle="Nuova assegnazione"
      hideRow={isSecondOfPair}
      defaultSort="docente"
      emptyHint="Nessuna assegnazione restituita dal server."
      columns={[
        {
          key: "docente",
          header: "Docente",
          render: (r) => teacherName(r.docente_id),
          sortValue: (r) => teacherName(r.docente_id),
        },
        {
          key: "classe",
          header: "Classe",
          sortValue: (r) => className(r.classe_id),
          render: (r) =>
            r.partner_classe_id
              ? `${className(r.classe_id)} + ${className(r.partner_classe_id)}`
              : className(r.classe_id),
        },
        { key: "tipo", header: "Tipo", render: (r) => (r.partner_classe_id ? "Accoppiata" : "Singola") },
        { key: "ore_totali", header: "Ore totali", render: (r) => r.ore_totali },
        { key: "ore_fatte", header: "Ore fatte", render: (r) => r.ore_erogate ?? 0 },
        {
          key: "ore_residue",
          header: "Residuo",
          render: (r) => {
            const residuo = r.ore_totali - (r.ore_erogate ?? 0);
            return residuo < 0 ? `${residuo} (oltre il monte)` : residuo;
          },
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
          {(() => {
            const editing = Boolean(value["assignment_id"]);
            const docenteId = value["docente_id"] ?? "";
            // Accoppiamenti del docente scelto (o senza docente specifico).
            const pairs = editing
              ? []
              : (pairings.data ?? []).filter((p) => !p.docente_id || p.docente_id === docenteId);
            const selected = value["accoppiamento_id"]
              ? `pair:${value["accoppiamento_id"]}`
              : (value["classe_id"] ?? "");
            return (
              <Select
                label="Classe"
                value={selected}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v.startsWith("pair:")) {
                    set("accoppiamento_id", v.slice(5));
                    set("classe_id", "");
                  } else {
                    set("accoppiamento_id", "");
                    set("classe_id", v);
                  }
                }}
              >
                <option value="">Seleziona…</option>
                {pairs.length > 0 ? (
                  <optgroup label="Classi accoppiate">
                    {pairs.map((p) => (
                      <option key={p.pairing_id} value={`pair:${p.pairing_id}`}>
                        {className(p.classe_a_id)} + {className(p.classe_b_id)}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                <optgroup label="Classi singole">
                  {(classes.data ?? []).map((c) => (
                    <option key={c.classe_id} value={c.classe_id}>
                      {c.nome}
                    </option>
                  ))}
                </optgroup>
              </Select>
            );
          })()}
          <Field
            label="Ore totali"
            type="number"
            value={value["ore_totali"] ?? ""}
            onChange={(e) => set("ore_totali", e.target.value)}
          />
          <Field
            label="Ore fatte (si aggiornano da sole all'approvazione di una settimana)"
            type="number"
            value={value["ore_erogate"] ?? ""}
            onChange={(e) => set("ore_erogate", e.target.value)}
          />
        </>
      )}
    />
  );
}
