// SPDX-License-Identifier: AGPL-3.0-only
// List toolbar for the Clips and Images tabs, built with the same markup and classes as Stash's own
// (ui/v2.5/src/components/List/FilteredListToolbar.tsx, ListFilter.tsx, ListViewOptions.tsx,
// FilterTags.tsx) so Stash's stylesheet makes it look and behave the same.
import React from "react";
import { filterCount, formatsIn, SORTS, ZOOM_WIDTHS, type Orientation, type QueueControlsState, type StatusFilter } from "../lib/sort.ts";
import type { Candidate } from "../lib/types.ts";
import { STATUS_LABELS } from "../model.ts";

export interface SelectionAction {
  text: string;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
}

interface Props {
  tab: "clips" | "images";
  controls: QueueControlsState;
  items: Candidate[];
  selected: number;
  selectionActions: SelectionAction[];
  onChange: (next: QueueControlsState) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onRefresh: () => void;
  onSendAll?: () => void;
}

const STATUS_FILTERS: StatusFilter[] = ["pending", "ready", "exporting", "sending", "failed"];
const ORIENTATIONS: Orientation[] = ["portrait", "landscape", "square"];

function icon(name: string) {
  const { Icon } = PluginApi.components;
  return <Icon icon={PluginApi.libraries.FontAwesomeSolid[name]} />;
}

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { Button, FormControl } = PluginApi.libraries.Bootstrap;
  const [text, setText] = React.useState(value);
  React.useEffect(() => setText(value), [value]);
  React.useEffect(() => {
    const timer = window.setTimeout(() => text !== value && onChange(text), 300);
    return () => window.clearTimeout(timer);
  }, [text]);
  return (
    <div className="clearable-input-group search-term-input">
      <FormControl className="clearable-text-field" value={text} placeholder="Search…" aria-label="Search"
        onInput={(e: React.FormEvent<HTMLInputElement>) => setText(e.currentTarget.value)}
        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Escape" && e.currentTarget.blur()} />
      {text ? (
        <Button variant="secondary" className="clearable-text-field-clear" title="Clear" onClick={() => { setText(""); onChange(""); }}>
          {icon("faTimes")}
        </Button>
      ) : null}
    </div>
  );
}

function SortBySelect({ tab, controls, onChange }: Pick<Props, "tab" | "controls" | "onChange">) {
  const { Dropdown, ButtonGroup, Button, InputGroup, OverlayTrigger, Tooltip } = PluginApi.libraries.Bootstrap;
  const options = [...SORTS[tab]].sort((a, b) => a.label.localeCompare(b.label));
  const current = options.find((o) => o.key === controls.sort);
  const asc = controls.dir === "asc";
  return (
    <Dropdown as={ButtonGroup} className="sort-by-select">
      <InputGroup.Prepend>
        <Dropdown.Toggle variant="secondary">{current?.label ?? ""}</Dropdown.Toggle>
      </InputGroup.Prepend>
      <Dropdown.Menu className="bg-secondary text-white">
        {options.map((o) => (
          <Dropdown.Item key={o.key} eventKey={o.key} className="bg-secondary text-white"
            onSelect={() => onChange({ ...controls, sort: o.key })}>
            {o.label}
          </Dropdown.Item>
        ))}
      </Dropdown.Menu>
      <OverlayTrigger overlay={<Tooltip id="imaglr-sort-direction">{asc ? "Ascending" : "Descending"}</Tooltip>}>
        <Button variant="secondary" aria-label={asc ? "Ascending" : "Descending"}
          onClick={() => onChange({ ...controls, dir: asc ? "desc" : "asc" })}>
          {icon(asc ? "faCaretUp" : "faCaretDown")}
        </Button>
      </OverlayTrigger>
    </Dropdown>
  );
}

function ViewButtons({ controls, onChange }: Pick<Props, "controls" | "onChange">) {
  const { ButtonGroup, Button, OverlayTrigger, Tooltip, Form } = PluginApi.libraries.Bootstrap;
  const modes = [
    { key: "grid" as const, label: "Grid", icon: "faThLarge" },
    { key: "list" as const, label: "List", icon: "faList" },
  ];
  return (
    <>
      <ButtonGroup>
        {modes.map((m) => (
          <OverlayTrigger key={m.key} overlay={<Tooltip id={`imaglr-view-${m.key}`}>{m.label}</Tooltip>}>
            <Button variant="secondary" active={controls.view === m.key} aria-label={m.label}
              onClick={() => onChange({ ...controls, view: m.key })}>
              {icon(m.icon)}
            </Button>
          </OverlayTrigger>
        ))}
      </ButtonGroup>
      <div className="zoom-slider-container">
        {controls.view === "grid" ? (
          <Form.Control className="zoom-slider" type="range" min={0} max={ZOOM_WIDTHS.length - 1} value={controls.zoom}
            aria-label="Card size"
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...controls, zoom: Number(e.currentTarget.value) })} />
        ) : null}
      </div>
    </>
  );
}

/** Active filters as removable chips under the toolbar, like Stash's FilterTags. */
export function FilterTags({ controls, onChange }: Pick<Props, "controls" | "onChange">) {
  const { Badge, Button } = PluginApi.libraries.Bootstrap;
  const tags: { label: string; clear: Partial<QueueControlsState> }[] = [];
  if (controls.status !== "all") {
    tags.push({ label: `Status: ${STATUS_LABELS[controls.status as keyof typeof STATUS_LABELS] ?? controls.status}`, clear: { status: "all" } });
  }
  if (controls.types.length) tags.push({ label: `Type: ${controls.types.join(", ")}`, clear: { types: [] } });
  if (controls.orientation !== "any") tags.push({ label: `Orientation: ${controls.orientation}`, clear: { orientation: "any" } });
  if (!tags.length) return null;
  return (
    <div className="wrap-tags filter-tags">
      {tags.map((t) => (
        <Badge key={t.label} className="tag-item" variant="secondary">
          {t.label}
          <Button variant="secondary" aria-label={`Remove ${t.label}`} onClick={() => onChange({ ...controls, ...t.clear })}>
            {icon("faTimes")}
          </Button>
        </Badge>
      ))}
      {tags.length > 1 ? (
        <Button variant="link" className="clear-all-button"
          onClick={() => onChange({ ...controls, status: "all", types: [], orientation: "any" })}>
          Clear all
        </Button>
      ) : null}
    </div>
  );
}

function FilterDialog({ tab, controls, items, onChange, onClose }: Pick<Props, "tab" | "controls" | "items" | "onChange"> & { onClose: () => void }) {
  const { Modal, Button, Form } = PluginApi.libraries.Bootstrap;
  const [draft, setDraft] = React.useState(controls);
  const formats = formatsIn(items);
  return (
    <Modal show onHide={() => undefined} keyboard={false}>
      <Modal.Header>
        <Modal.Title>Filter {tab}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <Form.Group>
          <Form.Label>Status</Form.Label>
          <Form.Control as="select" className="text-input" value={draft.status}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setDraft({ ...draft, status: e.target.value as StatusFilter })}>
            <option value="all">Any</option>
            {STATUS_FILTERS.map((s) => <option key={s} value={s}>{STATUS_LABELS[s as keyof typeof STATUS_LABELS]}</option>)}
          </Form.Control>
        </Form.Group>
        {formats.length > 1 ? (
          <Form.Group>
            <Form.Label>Type</Form.Label>
            {formats.map((f) => (
              <Form.Check key={f} id={`imaglr-type-${f}`} type="checkbox" label={f} checked={draft.types.includes(f)}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDraft({
                  ...draft, types: e.target.checked ? [...draft.types, f] : draft.types.filter((t) => t !== f),
                })} />
            ))}
          </Form.Group>
        ) : null}
        <Form.Group>
          <Form.Label>Orientation</Form.Label>
          <Form.Control as="select" className="text-input" value={draft.orientation}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setDraft({ ...draft, orientation: e.target.value as Orientation })}>
            <option value="any">Any</option>
            {ORIENTATIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
          </Form.Control>
        </Form.Group>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={() => { onChange(draft); onClose(); }}>Apply</Button>
      </Modal.Footer>
    </Modal>
  );
}

export function Toolbar(props: Props) {
  const { ButtonToolbar, ButtonGroup, Button, Badge, Dropdown } = PluginApi.libraries.Bootstrap;
  const { controls, onChange, selected, selectionActions } = props;
  const [showFilter, setShowFilter] = React.useState(false);
  const count = filterCount(controls);
  // Like Stash, actions on the selection only appear once something is selected.
  const buttons = selected ? selectionActions.filter((a) => a.primary) : [];
  const menu = selected ? selectionActions.filter((a) => !a.primary) : [];

  return (
    <>
      <ButtonToolbar className={`filtered-list-toolbar${selected ? " has-selection" : ""}`}>
        {selected ? (
          <div className="selected-items-info">
            <Button variant="secondary" className="minimal" title="Select none" onClick={props.onSelectNone}>{icon("faTimes")}</Button>
            <span className="selected-count">{selected}</span>
            <Button variant="secondary" className="minimal" title="Select all" onClick={props.onSelectAll}>{icon("faSquareCheck")}</Button>
          </div>
        ) : (
          <>
            <SearchInput value={controls.search} onChange={(search) => onChange({ ...controls, search })} />
            <ButtonGroup>
              <Button variant="secondary" className="filter-button" title="Filter" onClick={() => setShowFilter(true)}>
                {icon("faFilter")}
                {count ? <Badge pill variant="info">{count}</Badge> : null}
              </Button>
            </ButtonGroup>
            <SortBySelect tab={props.tab} controls={controls} onChange={onChange} />
          </>
        )}
        <ButtonGroup className="list-operations">
          {props.onSendAll ? (
            <Button variant="primary" onClick={props.onSendAll}>{selected ? "Send selected" : "Send all"}</Button>
          ) : null}
          {buttons.map((a) => (
            <Button key={a.text} variant={a.danger ? "danger" : "secondary"} disabled={a.disabled} onClick={a.onClick}>{a.text}</Button>
          ))}
          <Dropdown as={ButtonGroup}>
            <Dropdown.Toggle variant="secondary" id="imaglr-more" aria-label="More">{icon("faEllipsisH")}</Dropdown.Toggle>
            <Dropdown.Menu className="bg-secondary text-white">
              <Dropdown.Item className="bg-secondary text-white" onClick={props.onSelectAll}>Select all</Dropdown.Item>
              {selected ? <Dropdown.Item className="bg-secondary text-white" onClick={props.onSelectNone}>Select none</Dropdown.Item> : null}
              {menu.map((a) => (
                <Dropdown.Item key={a.text} className="bg-secondary text-white" disabled={a.disabled} onClick={a.onClick}>{a.text}</Dropdown.Item>
              ))}
              <Dropdown.Item className="bg-secondary text-white" onClick={props.onRefresh}>Refresh</Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown>
        </ButtonGroup>
        <ViewButtons controls={controls} onChange={onChange} />
      </ButtonToolbar>
      <FilterTags controls={controls} onChange={onChange} />
      {showFilter ? (
        <FilterDialog tab={props.tab} controls={controls} items={props.items} onChange={onChange} onClose={() => setShowFilter(false)} />
      ) : null}
    </>
  );
}
