import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CrudTable } from "@/components/CrudTable";
import { Select } from "@/components/ui-kit";
import { api } from "@/lib/api";
import { classeSortValue, sortClassiByNome } from "@/lib/classi";
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
      defaultSort="docente"
      thenSortBy={(r) =>
        `${classeSortValue(className(r.classe_a_id))} ${classeSortValue(className(r.classe_b_id))}`
      }
      emptyHint="Nessun accoppiamento restituito dal server."
      columns={[
        {
          key: "docente",
          header: "Docente",
          render: (r) => teacherName(r.docente_id),
          // senza docente in fondo (crescente)
          sortValue: (r) => (r.docente_id ? teacherName(r.docente_id) : "\uffff"),
        },
        {
          key: "a",
          header: "Classe A",
          render: (r) => className(r.classe_a_id),
          sortValue: (r) => classeSortValue(className(r.classe_a_id)),
        },
        {
          key: "b",
          header: "Classe B",
          render: (r) => className(r.classe_b_id),
          sortValue: (r) => classeSortValue(className(r.classe_b_id)),
        },
      ]}
      form={({ value, set }) => {
        const editing = Boolean(value["pairing_id"]);
        const selected = new Set((value["classi_ids"] ?? "").split(",").filter(Boolean));
        const toggle = (id: string) => {
          const next = new Set(selected);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          set("classi_ids", [...next].join(","));
        };
        return (
          <>
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
            {editing ? (
              <>
                <Select
                  label="Classe A"
                  value={value["classe_a_id"] ?? ""}
                  onChange={(e) => set("classe_a_id", e.target.value)}
                >
                  <option value="">Seleziona…</option>
                  {sortClassiByNome(classes.data).map((c) => (
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
                  {sortClassiByNome(classes.data).map((c) => (
                    <option key={c.classe_id} value={c.classe_id}>
                      {c.nome}
                    </option>
                  ))}
                </Select>
              </>
            ) : (
              <fieldset className="space-y-1">
                <legend className="label-mono mb-1">
                  Classi accoppiate (2 o più: si creano tutte le coppie)
                </legend>
                <div className="max-h-56 space-y-0.5 overflow-auto rounded-lg border border-edge p-2">
                  {sortClassiByNome(classes.data).map((c) => (
                    <label key={c.classe_id} className="flex cursor-pointer items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={selected.has(c.classe_id)}
                        onChange={() => toggle(c.classe_id)}
                      />
                      {c.nome}
                    </label>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  {selected.size} classi selezionate
                  {selected.size >= 2 ? ` → ${(selected.size * (selected.size - 1)) / 2} accoppiamenti` : ""}
                </p>
              </fieldset>
            )}
          </>
        );
      }}
    />
  );
}
