// SPDX-License-Identifier: AGPL-3.0-only
// Paging exactly as Stash's lists do it: a page-size dropdown in the toolbar (markup from
// ui/v2.5/src/components/List/ListFilter.tsx) and Stash's own Pagination buttons above and below the list, with
// its PaginationIndex ("1-40 of 120") above, which Stash exposes to plugins.
import React from "react";
import { PAGE_SIZES } from "../lib/sort.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";

export function PageSizeSelect({ value, onChange }: { value: number; onChange: (size: number) => void }) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const [custom, setCustom] = React.useState<string | null>(null);
  const options = PAGE_SIZES.includes(value) ? PAGE_SIZES : [...PAGE_SIZES, value].sort((a, b) => a - b);
  const typed = Math.floor(Number(custom));
  return (
    <div className="page-count-container">
      <Form.Control as="select" className="btn-secondary" value={String(value)} aria-label="Items per page"
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
          if (e.target.value === "custom") setCustom(String(value));
          else onChange(Number(e.target.value));
        }}>
        {options.map((n) => <option key={n} value={n}>{n}</option>)}
        <option value="custom">Custom…</option>
      </Form.Control>
      {custom !== null ? (
        <ConfirmDialog title="Items per page" accept="Apply" disabled={!(typed > 0)}
          onAccept={() => { onChange(typed); setCustom(null); }} onCancel={() => setCustom(null)}>
          <Form.Control type="number" min={1} className="text-input" value={custom} autoFocus aria-label="Items per page"
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setCustom(e.target.value)}
            onKeyDown={(e: React.KeyboardEvent) => { if (e.key === "Enter" && typed > 0) { onChange(typed); setCustom(null); } }} />
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

interface PagerProps {
  page: number;
  perPage: number;
  total: number;
  onChange: (page: number) => void;
}

/** Stash's own pager is in its list code, which v0.32 and later load only when one of Stash's lists is opened. */
function useStashPager(): "loading" | "stash" | "plain" {
  const { useLoadComponents } = PluginApi.hooks;
  const [lists] = React.useState(() => PluginApi.loadableComponents?.Images ? [PluginApi.loadableComponents.Images] : null);
  const loading: boolean = useLoadComponents && lists ? useLoadComponents(lists) : false; // the same call every render
  if (loading) return "loading";
  return PluginApi.components.Pagination && PluginApi.components.PaginationIndex ? "stash" : "plain";
}

/** Page buttons above and below a list, with the index line ("1-40 of 120") above, laid out as Stash's lists are
 *  (ui/v2.5/src/components/List/ItemList.tsx): Stash's components, or plain buttons if they can't be loaded. */
export function Paged({ page, perPage, total, onChange, children }: PagerProps & { children: React.ReactNode }) {
  const pager = useStashPager();
  const stash = pager === "stash";
  if (total === 0) return <>{children}</>;
  if (pager === "loading") return <><div className="pagination-index-container" />{children}</>;
  return (
    <>
      <div className="pagination-index-container">
        <PageButtons stash={stash} page={page} perPage={perPage} total={total} onChange={onChange} />
        {stash ? <PluginApi.components.PaginationIndex itemsPerPage={perPage} currentPage={page} totalItems={total} />
          : <span className="filter-container text-muted paginationIndex center-text">{(page - 1) * perPage + 1}-{Math.min(page * perPage, total)} of {total}</span>}
      </div>
      {children}
      <div className="pagination-footer-container">
        <div className="pagination-footer">
          <PageButtons stash={stash} page={page} perPage={perPage} total={total} onChange={onChange} />
        </div>
      </div>
    </>
  );
}

function PageButtons({ stash, page, perPage, total, onChange }: PagerProps & { stash: boolean }) {
  const { Button, ButtonGroup } = PluginApi.libraries.Bootstrap;
  if (stash) return <PluginApi.components.Pagination itemsPerPage={perPage} currentPage={page} totalItems={total} onChangePage={onChange} />;
  const pages = Math.max(1, Math.ceil(total / perPage));
  return pages > 1 ? (
    <ButtonGroup className="pagination">
      <Button variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>‹</Button>
      <Button variant="secondary" disabled>{page} / {pages}</Button>
      <Button variant="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>›</Button>
    </ButtonGroup>
  ) : null;
}
