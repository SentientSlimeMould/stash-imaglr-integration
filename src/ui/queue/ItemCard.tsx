// SPDX-License-Identifier: AGPL-3.0-only
// Pieces of a queue card. The card itself is Stash's GridCard (see QueueTab); these supply its image,
// overlays and details using Stash's image-card classes, so sizes and hover behave like Stash's cards.
import React from "react";
import { baseUrl } from "../api.ts";
import { fmtDims } from "../lib/format.ts";
import { STATUS_LABELS, STATUS_VARIANTS, type Card } from "../model.ts";

export function cardDetail(card: Card): string {
  const count = card.members?.length ?? 0;
  if (count) return `${count} files in one post`;
  if (card.kind === "clip") {
    return [`${(card.duration ?? 0).toFixed(1)} s`, fmtDims(card.width, card.height)].filter(Boolean).join(" · ");
  }
  return [card.format?.toUpperCase(), fmtDims(card.width, card.height), card.animated ? "animated" : null]
    .filter(Boolean)
    .join(" · ");
}

/** Thumbnail; clips play Stash's marker preview while hovered on devices with a mouse. */
export function CardImage({ card }: { card: Card }) {
  const [hover, setHover] = React.useState(false);
  const canHover = window.matchMedia?.("(hover: hover)").matches;
  const portrait = (card.height ?? 0) > (card.width ?? 0);
  return (
    <div className={`image-card-preview${portrait ? " portrait" : ""}`}
      onMouseEnter={() => canHover && card.preview && setHover(true)}
      onMouseLeave={() => setHover(false)}>
      {hover && card.preview ? (
        <video className="image-card-preview-image" src={baseUrl() + card.preview} autoPlay muted loop playsInline />
      ) : card.thumb ? (
        <img className="image-card-preview-image" src={baseUrl() + card.thumb} alt="" loading="lazy" />
      ) : null}
    </div>
  );
}

export function CardOverlays({ card }: { card: Card }) {
  const { Badge } = PluginApi.libraries.Bootstrap;
  const count = card.members?.length ?? 0;
  return (
    <>
      {count ? <span className="imaglr-card-count" title={`${count} files in one post`}>{count}</span> : null}
      <Badge variant={STATUS_VARIANTS[card.status]} className="imaglr-card-status">{STATUS_LABELS[card.status]}</Badge>
    </>
  );
}

/** Used only if Stash's GridCard can't be loaded. */
export function FallbackCard({ card, url, width }: { card: Card; url: string; width?: number }) {
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  return (
    <div className="card grid-card image-card imaglr-grid-card" style={width ? { width } : undefined}>
      <div className="thumbnail-section">
        <Link to={url} className="image-card-link"><CardImage card={card} /></Link>
        <CardOverlays card={card} />
      </div>
      <div className="card-section">
        <Link to={url}><h5 className="card-section-title">{card.title}</h5></Link>
        <div className="image-card__details"><span>{cardDetail(card)}</span></div>
      </div>
    </div>
  );
}
