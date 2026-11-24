import { supabase } from "./supabaseClient";

const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function authenticatedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  if (!data.session) throw new Error("Your session has expired. Please sign in again.");

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${data.session.access_token}`);

  return fetch(new URL(path, apiUrl), { ...init, headers });
}

export async function apiErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Use the status-based message below when the response has no JSON body.
  }
  return `Request failed (${response.status}).`;
}
