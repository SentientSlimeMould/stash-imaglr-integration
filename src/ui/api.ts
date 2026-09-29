// SPDX-License-Identifier: AGPL-3.0-only
// GraphQL calls to Stash, including the plugin's own backend via runPluginOperation.

export const PLUGIN_ID = "imaglrIntegration";

/** Stash's base URL, which includes any reverse-proxy prefix (from <base href>). */
export function baseUrl(doc: Document = document): string {
  const href = doc.querySelector("base")?.getAttribute("href") ?? "/";
  return href.endsWith("/") ? href : href + "/";
}

export async function gql<T>(query: string, variables: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(baseUrl() + "graphql", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables }),
  });
  if (!response.ok) throw new Error(`Stash returned HTTP ${response.status}`);
  const result = await response.json();
  if (result.errors?.length) {
    throw new Error(result.errors.map((e: { message: string }) => e.message).join("; "));
  }
  return result.data as T;
}

/** Runs a fast operation in the plugin's Python backend and returns its output. */
export async function runOperation<T>(mode: string, args: Record<string, unknown> = {}): Promise<T> {
  const data = await gql<{ runPluginOperation: T }>(
    "mutation($id: ID!, $args: Map) { runPluginOperation(plugin_id: $id, args: $args) }",
    { id: PLUGIN_ID, args: { ...args, mode } },
  );
  return data.runPluginOperation;
}

export interface Ping {
  pong: boolean;
  plugin_version: string;
  python: string;
  stash_version: string;
  ffmpeg: string;
  ffprobe: string;
}
