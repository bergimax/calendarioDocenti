import { useState } from "react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui-kit";

// Small helpers that keep the Orario page understandable to someone who
// does not know the solver: a step guide, "?" hints and two-step confirms.

const STEPS = ["Genera", "Risolvi i problemi", "Approva", "Esporta"] as const;

/** Where the admin is in the weekly flow, as the index of STEPS. */
export function currentStep(opts: { hasSchedule: boolean; problems: number; approved: boolean }): number {
  if (!opts.hasSchedule) return 0;
  if (opts.approved) return 3;
  return opts.problems > 0 ? 1 : 2;
}

export function StepGuide({ step, hint }: { step: number; hint: string }) {
  return (
    <div className="glass rounded-2xl p-3">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        {STEPS.map((label, i) => {
          const done = i < step;
          const here = i === step;
          return (
            <li key={label} className="flex items-center gap-2">
              <span
                className={`grid size-5 place-items-center rounded-full text-[11px] font-bold ${
                  here
                    ? "bg-brand text-primary-foreground"
                    : done
                      ? "bg-edge text-foreground"
                      : "border border-edge text-muted-foreground"
                }`}
              >
                {done ? "✓" : i + 1}
              </span>
              <span className={here ? "font-semibold" : "text-muted-foreground"}>{label}</span>
              {i < STEPS.length - 1 ? <span className="text-muted-foreground">›</span> : null}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

/** A "?" that explains a term on hover/focus (native tooltip, works on keyboard focus too). */
export function Aiuto({ testo }: { testo: string }) {
  return (
    <span
      tabIndex={0}
      title={testo}
      aria-label={testo}
      className="ml-1 inline-grid size-4 cursor-help place-items-center rounded-full border border-edge text-[10px] font-bold text-muted-foreground"
    >
      ?
    </span>
  );
}

/** A button that asks "are you sure?" inline before running `onConfirm`. */
export function ConfirmButton({
  children,
  domanda,
  onConfirm,
  variant = "ghost",
  disabled,
  skipConfirm,
}: {
  children: ReactNode;
  domanda: string;
  onConfirm: () => void;
  variant?: "primary" | "solid" | "ghost" | "danger";
  disabled?: boolean;
  /** Nothing to lose (e.g. no schedule yet): run straight away. */
  skipConfirm?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (asking) {
    return (
      <span className="inline-flex flex-wrap items-center gap-2 text-xs">
        <span className="max-w-sm text-muted-foreground">{domanda}</span>
        <Button
          variant="primary"
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
        >
          Sì, procedi
        </Button>
        <Button onClick={() => setAsking(false)}>Annulla</Button>
      </span>
    );
  }
  return (
    <Button
      variant={variant}
      disabled={disabled}
      onClick={() => (skipConfirm ? onConfirm() : setAsking(true))}
    >
      {children}
    </Button>
  );
}

/** Quality in words; the number stays available for those who want it.
 * Open problems always win over the score: "Ottimo" next to 38 problems misleads. */
export function qualitaInParole(score: number | null | undefined, problemi = 0): string {
  if (score == null) return "—";
  if (problemi > 0) return "Da rivedere";
  if (score > 95) return "Ottimo";
  if (score > 80) return "Buono";
  return "Da rivedere";
}
