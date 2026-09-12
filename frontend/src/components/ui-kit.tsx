import type { ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "solid" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-primary-foreground hover:opacity-90",
  solid: "bg-ink text-primary-foreground hover:opacity-90",
  ghost: "glass text-foreground hover:bg-accent/50",
  danger: "bg-conflict text-primary-foreground hover:opacity-90",
};

export function Button({
  variant = "ghost",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
    />
  );
}

export function Field({
  label,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return (
    <label className="block">
      {label ? <span className="label-mono mb-1 block">{label}</span> : null}
      <input
        {...props}
        className={cn(
          "w-full rounded-lg border border-edge bg-card px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40",
          className,
        )}
      />
    </label>
  );
}

export function Select({
  label,
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className="block">
      {label ? <span className="label-mono mb-1 block">{label}</span> : null}
      <select
        {...props}
        className={cn(
          "w-full rounded-lg border border-edge bg-card px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40",
          className,
        )}
      >
        {children}
      </select>
    </label>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "ok" | "warn" | "conflict" | "brand";
  children: React.ReactNode;
}) {
  const tones = {
    neutral: "bg-muted text-muted-foreground ring-edge",
    ok: "bg-ok/10 text-ok ring-ok/25",
    warn: "bg-warn/10 text-warn ring-warn/30",
    conflict: "bg-conflict/10 text-conflict ring-conflict/25",
    brand: "bg-brand/10 text-brand ring-brand/25",
  } as const;
  return (
    <span
      className={cn(
        "rounded-md px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-wider ring-1",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
