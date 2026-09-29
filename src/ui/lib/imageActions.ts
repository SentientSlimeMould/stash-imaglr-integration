// SPDX-License-Identifier: AGPL-3.0-only
// Pure helpers for the "Add to imaglr" image-list actions (src/ui/imageListActions.tsx).

export const MAX_POST_FILES = 10;

export interface AddResult {
  added: number;
  already: number;
  post_id: string | null;
  too_many?: number;
}

/** The gallery whose Images tab we're on, from the URL (/galleries/<id>/...). */
export function galleryIdFromPath(pathname: string): string | null {
  return pathname.match(/\/galleries\/(\d+)(?:\/|$)/)?.[1] ?? null;
}

export function addedMessage(result: AddResult, asOnePost: boolean): string {
  const noun = (n: number) => `${n} image${n === 1 ? "" : "s"}`;
  if (asOnePost) return `${noun(result.added + result.already)} added to imaglr as one post.`;
  const parts = [`${noun(result.added)} added to imaglr.`];
  if (result.already) parts.push(`${noun(result.already)} already there.`);
  return parts.join(" ");
}
