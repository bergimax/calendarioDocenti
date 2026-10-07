// Gli anni delle classi sono in numeri romani: I=1, II=2, III=3, IV=4 (V=5...).
const ROMANI: Record<string, number> = {
  I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6, VII: 7, VIII: 8, IX: 9, X: 10,
};

/** Anno di una classe dal nome ("III OP. INFORM." -> 3), 99 se non c'è. */
export function annoClasse(nome: string): number {
  const m = nome.trim().match(/^([IVX]+)\b/i);
  return (m?.[1] && ROMANI[m[1].toUpperCase()]) || 99;
}

/** Chiave di ordinamento: prima l'anno come numero, poi il resto del nome ("03 OP. INFORM."). */
export function classeSortValue(nome: string): string {
  const anno = annoClasse(nome);
  const resto = anno === 99 ? nome : nome.trim().replace(/^[IVX]+\b\s*/i, "");
  return `${String(anno).padStart(2, "0")} ${resto}`;
}

/** Copia dell'elenco ordinata per anno (I < II < III < IV) e poi per nome. */
export function sortClassiByNome<T extends { nome: string }>(classi: readonly T[] | undefined): T[] {
  return [...(classi ?? [])].sort((a, b) =>
    classeSortValue(a.nome).localeCompare(classeSortValue(b.nome), "it", { numeric: true, sensitivity: "base" }),
  );
}
