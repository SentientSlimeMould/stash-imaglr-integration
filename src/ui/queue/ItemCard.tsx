// SPDX-License-Identifier: AGPL-3.0-only
// One tile on the Clips or Images tab: a single file, or a post of several shown as a stack.
import React from "react";
import { baseUrl } from "../api.ts";
import { STATUS_LABELS, STATUS_VARIANTS, type Card } from "../model.ts";
import { fmtDims } from "../lib/format.ts";

interface Props {
  card: Card;
  highlighted?: boolean;
}

export function ItemCard({ card, highlighted }: Props) {
  const { Badge } = PluginApi.libraries.Bootstrap;
  const ref = React.useRef<HTMLDivElement>(null);
  const count = card.members?.length ?? 0;

  React.useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlighted]);

  const detail = count
    ? `${count} files in one post`
    : [card.format?.toUpperCase(), fmtDims(card.width, card.height), card.animated ? "animated" : null]
        .filter(Boolean)
        .join(" · ");

  return (
    <div
      ref={ref}
      className={`imaglr-card card${count ? " imaglr-card-stack" : ""}${highlighted ? " imaglr-card-highlight" : ""}`}
    >
      <div className="imaglr-card-thumb">
        {card.thumb ? <img src={baseUrl() + card.thumb} alt="" loading="lazy" /> : null}
        {count ? <span className="imaglr-card-count">{count}</span> : null}
        <Badge variant={STATUS_VARIANTS[card.status]} className="imaglr-card-status">
          {STATUS_LABELS[card.status]}
        </Badge>
      </div>
      <div className="imaglr-card-body">
        <div className="imaglr-card-title" title={card.title}>
          {card.title}
        </div>
        <div className="imaglr-card-detail text-muted">{detail}</div>
      </div>
    </div>
  );
}
