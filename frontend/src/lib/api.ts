/**
 * Client HTTP verso il backend FastAPI.
 * Le API non sono ancora implementate: ogni chiamata parte davvero
 * e l'interfaccia mostra lo stato di errore finché il backend non risponde.
 */

export const API_BASE_URL =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "";

const AUTH_TOKEN_KEY = "authToken";

export function setAuthToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    else sessionStorage.removeItem(AUTH_TOKEN_KEY);
  } catch {
    /* sessionStorage non disponibile (es. modalità privata) */
  }
}

function getAuthToken(): string | null {
  try {
    return sessionStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type Options = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  const init: RequestInit = { method };
  if (signal) init.signal = signal;
  if (body instanceof FormData) {
    init.body = body;
  } else if (body != null) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const token = getAuthToken();
  if (token) {
    init.headers = { ...(init.headers as Record<string, string> | undefined), Authorization: `Bearer ${token}` };
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError("Impossibile contattare il server.", 0);
  }

  if (!res.ok) {
    let detail = `Errore ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: string; message?: string };
      detail = data.detail ?? data.message ?? detail;
    } catch {
      /* risposta non JSON */
    }
    // A 401 from the login endpoint itself just means "wrong credentials" -
    // only a 401 from every other (now session-gated) endpoint means the
    // stored session is missing/expired, in which case send the user back
    // to the login page instead of leaving every page stuck on a generic
    // "Not authenticated" error state.
    if (res.status === 401 && path !== "/api/auth/login" && typeof window !== "undefined") {
      setAuthToken(null);
      if (window.location.pathname !== "/") window.location.assign("/");
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** GET autenticato di un file binario (es. PDF): window.open non invierebbe il token Bearer. */
export async function apiBlob(path: string): Promise<Blob> {
  const token = getAuthToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new ApiError("Impossibile contattare il server.", 0);
  }
  if (!res.ok) throw new ApiError(`Errore ${res.status}`, res.status);
  return res.blob();
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 0
      ? "Server non raggiungibile. Il backend non è ancora attivo."
      : error.message;
  }
  // Some endpoints return HTTP 200 with a {"status": "error", "message": ...}
  // body (a business-rule rejection, not a transport failure) - callers that
  // detect that shape throw a plain Error with the backend's own message.
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Si è verificato un errore imprevisto.";
}
