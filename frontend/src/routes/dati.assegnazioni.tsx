import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CrudTable } from "@/components/CrudTable";
import { Field, Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import { classeSortValue, sortClassiByNome } from "@/lib/classi";
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

  // Un gruppo accoppiato (2-4 classi) è una sola riga, mostrata sulla assegnazione con id
  // minore; il backend applica modifiche ed eliminazione a tutte le classi del gruppo.
  const isSecondOfPair = (r: Assignment) =>
    (r.partner_assignment_ids ?? []).some((id) => id < r.assignment_id);

  // "IV Elettricisti + IV Estetiste + ..." in ordine di anno e nome
  const groupName = (ids: string[]) =>
    sortClassiByNome(ids.map((id) => ({ nome: className(id) })))
      .map((c) => c.nome)
      .join(" + ");

  // Gruppi di classi collegate dagli accoppiamenti del docente (o senza docente), per tipo (in coppia):
  // 3-4 classi accoppiate tra loro sono una sola scelta.
  const pairGroups = (docenteId: string) => {
    const rows = (pairings.data ?? []).filter((p) => !p.docente_id || p.docente_id === docenteId);
    const groups: { key: string; materia: string; classi: Set<string> }[] = [];
    for (const p of rows) {
      const hit = groups.filter(
        (g) => g.materia === p.materia_id && (g.classi.has(p.classe_a_id) || g.classi.has(p.classe_b_id)),
      );
      const merged = hit[0] ?? { key: p.pairing_id, materia: p.materia_id, classi: new Set<string>() };
      for (const other of hit.slice(1)) {
        other.classi.forEach((c) => merged.classi.add(c));
        groups.splice(groups.indexOf(other), 1);
      }
      merged.classi.add(p.classe_a_id).add(p.classe_b_id);
      if (!hit[0]) groups.push(merged);
    }
    return groups;
  };

  return (
    <CrudTable<Assignment & Record<string, unknown>>
      title="Assegnazioni e monte ore"
      endpoint="/api/assignments"
      idKey="assignment_id"
      newTitle="Nuova assegnazione"
      hideRow={isSecondOfPair}
      defaultSort="docente"
      thenSortBy={(r) => classeSortValue(className(r.classe_id))}
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
          sortValue: (r) => classeSortValue(className(r.classe_id)),
          render: (r) => groupName([r.classe_id, ...(r.partner_classe_ids ?? [])]),
        },
        {
          key: "tipo",
          header: "Tipo",
          render: (r) => (r.partner_classe_ids?.length ? "Accoppiata" : "Singola"),
        },
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
            const pairs = editing ? [] : pairGroups(docenteId);
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
                    {pairs.map((g) => (
                      <option key={g.key} value={`pair:${g.key}`}>
                        {groupName([...g.classi])}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                <optgroup label="Classi singole">
                  {sortClassiByNome(classes.data).map((c) => (
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
