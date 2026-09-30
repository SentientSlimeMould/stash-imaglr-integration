// SPDX-License-Identifier: AGPL-3.0-only
// Paging exactly as Stash's lists do it: a page-size dropdown in the toolbar (markup from
// ui/v2.5/src/components/List/ListFilter.tsx) and, under the list, Stash's own PaginationIndex
// ("1-40 of 120") and Pagination buttons, which Stash exposes to plugins.
import React from "react";
import { PAGE_SIZES } from "../lib/sort.ts";

export function PageSizeSelect({ value, onChange }: { value: number; onChange: (size: number) => void }) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const options = PAGE_SIZES.includes(value) ? PAGE_SIZES : [...PAGE_SIZES, value].sort((a, b) => a - b);
  return (
    <div className="page-count-container">
      <Form.Control as="select" className="btn-secondary" value={String(value)} aria-label="Items per page"
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
          if (e.target.value === "custom") {
            const typed = Number(window.prompt("Items per page", String(value)));
            if (typed > 0) onChange(Math.floor(typed));
            return;
          }
          onChange(Number(e.target.value));
        }}>
        {options.map((n) => <option key={n} value={n}>{n}</option>)}
        <option value="custom">Custom…</option>
      </Form.Control>
    </div>
  );
}

interface PagerProps {
  page: number;
  perPage: number;
  total: number;
  onChange: (page: number) => void;
}

/** Index line and page buttons under a list; Stash's components when loaded, plain buttons otherwise. */
export function Pager({ page, perPage, total, onChange }: PagerProps) {
  const { Pagination, PaginationIndex } = PluginApi.components;
  const { Button, ButtonGroup } = PluginApi.libraries.Bootstrap;
  const pages = Math.max(1, Math.ceil(total / perPage));
  if (total === 0) return null;
  if (Pagination && PaginationIndex) {
    return (
      <>
        <PaginationIndex itemsPerPage={perPage} currentPage={page} totalItems={total} />
        <Pagination itemsPerPage={perPage} currentPage={page} totalItems={total} onChangePage={onChange} />
      </>
    );
  }
  const first = (page - 1) * perPage + 1;
  return (
    <>
      <div className="text-center text-muted">{first}-{Math.min(page * perPage, total)} of {total}</div>
      {pages > 1 ? (
        <ButtonGroup className="pagination">
          <Button variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>‹</Button>
          <Button variant="secondary" disabled>{page} / {pages}</Button>
          <Button variant="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>›</Button>
        </ButtonGroup>
      ) : null}
    </>
  );
}
