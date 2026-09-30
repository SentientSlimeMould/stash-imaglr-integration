// SPDX-License-Identifier: AGPL-3.0-only
// The card grid and list view shared by the Clips, Images and Sent tabs: Stash's own GridCard with
// image-card classes and Stash's card-width maths, or a compact table.
import React from "react";
import { baseUrl } from "../api.ts";
import { cardWidth } from "../lib/sort.ts";

export interface GridItem {
  id: string;
  title: string;
  url: string; // where the card links (its editor / details)
  thumb: string | null; // relative to Stash's base URL
  preview?: string | null; // plays on hover (desktop) if set
  portrait?: boolean;
  detail: string;
  badge?: { text: string; variant: string };
  count?: number; // files in a post
}

interface Props {
  items: GridItem[];
  view: "grid" | "list";
  zoom: number;
  highlightId?: string | null;
  selected?: Set<string>;
  onToggle?: (id: string, on: boolean) => void;
}

function useContainerWidth(ref: React.RefObject<HTMLDivElement>) {
  const [width, setWidth] = React.useState(0);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** Thumbnail; plays the preview while hovered on devices with a mouse. */
export function CardImage({ item }: { item: GridItem }) {
  const [hover, setHover] = React.useState(false);
  const canHover = window.matchMedia?.("(hover: hover)").matches;
  return (
    <div className={`image-card-preview${item.portrait ? " portrait" : ""}`}
      onMouseEnter={() => canHover && item.preview && setHover(true)}
      onMouseLeave={() => setHover(false)}>
      {hover && item.preview ? (
        <video className="image-card-preview-image" src={baseUrl() + item.preview} autoPlay muted loop playsInline />
      ) : item.thumb ? (
        <img className="image-card-preview-image" src={baseUrl() + item.thumb} alt="" loading="lazy" />
      ) : null}
    </div>
  );
}

function Overlays({ item }: { item: GridItem }) {
  const { Badge } = PluginApi.libraries.Bootstrap;
  return (
    <>
      {item.count ? <span className="imaglr-card-count" title={`${item.count} files in one post`}>{item.count}</span> : null}
      {item.badge ? <Badge variant={item.badge.variant} className="imaglr-card-status">{item.badge.text}</Badge> : null}
    </>
  );
}

export function CardGrid({ items, view, zoom, highlightId, selected, onToggle }: Props) {
  const { Table, Badge } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  // Stash's GridCard and Pagination are loaded on demand; these modules bring them in.
  const loading = PluginApi.hooks.useLoadComponents([PluginApi.loadableComponents.SceneCard, PluginApi.loadableComponents.Images]);
  const GridCard = loading ? null : PluginApi.components.GridCard;
  const box = React.useRef<HTMLDivElement>(null);
  const width = useContainerWidth(box);
  const isMobile = window.matchMedia("(max-width: 576px)").matches;
  const selecting = !!selected?.size;

  if (view === "list") {
    return (
      <Table striped bordered size="sm" className="imaglr-table">
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              {onToggle ? (
                <td className="select-col">
                  <input type="checkbox" className="mousetrap" checked={selected?.has(c.id) ?? false} aria-label={`Select ${c.title}`}
                    onChange={(e) => onToggle(c.id, e.target.checked)} />
                </td>
              ) : null}
              <td className="imaglr-table-thumb"><CardImage item={c} /></td>
              <td>
                <Link to={c.url}>{c.title}</Link>
                <div className="small text-muted">{c.detail}</div>
              </td>
              <td className="imaglr-table-status">
                {c.badge ? <Badge variant={c.badge.variant}>{c.badge.text}</Badge> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  }

  const w = isMobile ? undefined : cardWidth(width, zoom);
  return (
    <div ref={box} className="row justify-content-center imaglr-cards">
      {items.map((c) =>
        GridCard ? (
          <GridCard
            key={c.id}
            className={`image-card zoom-${zoom} imaglr-grid-card${c.id === highlightId ? " imaglr-card-highlight" : ""}`}
            linkClassName="image-card-link"
            width={w}
            url={c.url}
            title={c.title}
            image={<CardImage item={c} />}
            overlays={<Overlays item={c} />}
            details={<div className="image-card__details"><span>{c.detail}</span></div>}
            selecting={selecting}
            selected={selected?.has(c.id) ?? false}
            onSelectedChanged={onToggle ? (on: boolean) => onToggle(c.id, on) : undefined}
          />
        ) : (
          <div key={c.id} className="card grid-card image-card imaglr-grid-card" style={w ? { width: w } : undefined}>
            <div className="thumbnail-section">
              <Link to={c.url} className="image-card-link"><CardImage item={c} /></Link>
              <Overlays item={c} />
            </div>
            <div className="card-section">
              <Link to={c.url}><h5 className="card-section-title">{c.title}</h5></Link>
              <div className="image-card__details"><span>{c.detail}</span></div>
            </div>
          </div>
        ),
      )}
    </div>
  );
}
