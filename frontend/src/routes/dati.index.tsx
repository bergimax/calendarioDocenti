import { createFileRoute, redirect } from "@tanstack/react-router";

// Nessuna pagina di riepilogo: "Dati scuola" apre direttamente la prima sezione.
export const Route = createFileRoute("/dati/")({
  beforeLoad: () => {
    throw redirect({ to: "/dati/calendario", replace: true });
  },
});
