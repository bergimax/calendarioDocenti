/**
 * Client HTTP verso il backend FastAPI.
 * Le API non sono ancora implementate: ogni chiamata parte davvero
 * e l'interfaccia mostra lo stato di errore finché il backend non risponde.
 */

export const API_BASE_URL =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "";

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
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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
