export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Set while the user is deliberately signing out, so in-flight refreshes that now get 401s don't
// send them to the sign-in page instead of the landing page.
let signingOut = false;

/** Signs the user out (this device, or every device) and lands them on the landing page. */
export async function signOut(path: "/auth/logout" | "/auth/logout-all" = "/auth/logout") {
  signingOut = true;
  await fetch(`/api${path}`, { method: "POST", credentials: "include" }).catch(() => undefined);
  // A full load: drops every cached query and in-flight request along with the old session.
  window.location.replace("/");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    ...init,
    headers: { ...(isForm || !init.body ? {} : { "content-type": "application/json" }), ...init.headers },
  });
  if (res.status === 401 && typeof window !== "undefined" && !signingOut && !path.startsWith("/auth/") && window.location.pathname !== "/") {
    // Clear the dead cookie first, or the middleware would bounce /login straight back to the app.
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => undefined);
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg ?? message;
    } catch {}
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) }),
  put: <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T,>(path: string, body?: unknown) => request<T>(path, { method: "DELETE", body: body === undefined ? undefined : JSON.stringify(body) }),
};
