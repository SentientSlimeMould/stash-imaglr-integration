// SPDX-License-Identifier: AGPL-3.0-only
// The crop controls shared by the clip and image editors: the aspect preset and its position, and edge trims
// for black borders, with a detector that asks ffmpeg where the picture is. Same react-bootstrap pieces as
// Stash's own forms; every button is thumb-sized.
import React from "react";
import { runOperation } from "../api.ts";
import { ASPECTS, EDGE_NAMES, emptyEdges, hasEdges, MAX_EDGE_PERCENT } from "../lib/crop.ts";
import type { Aspect, Crop, CropEdges } from "../lib/types.ts";

const LABELS: Record<keyof CropEdges, string> = { top: "Top", bottom: "Bottom", left: "Left", right: "Right" };

interface Props {
  crop: Crop;
  disabled: boolean;
  itemId: string;
  onChange: (crop: Crop) => void;
}

export function CropControls({ crop, disabled, itemId, onChange }: Props) {
  const { Button, ButtonGroup, Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [detecting, setDetecting] = React.useState(false);
  const edges = crop.edges ?? emptyEdges();
  const percent = (name: keyof CropEdges) => Math.round((edges[name] ?? 0) * 100);

  function setEdge(name: keyof CropEdges, value: number) {
    const v = Math.min(MAX_EDGE_PERCENT, Math.max(0, Math.round(Number.isFinite(value) ? value : 0))) / 100;
    onChange({ ...crop, edges: { ...edges, [name]: v } });
  }

  async function detect() {
    setDetecting(true);
    try {
      const r = await runOperation<{ edges: CropEdges }>("crop_detect", { item_id: itemId });
      if (!hasEdges(r.edges)) Toast.success("No borders found.");
      onChange({ ...crop, edges: hasEdges(r.edges) ? r.edges : null });
    } catch (e) {
      Toast.error(e);
    } finally {
      setDetecting(false);
    }
  }

  return (
    <Form.Group className="mt-2">
      <Form.Label>Crop</Form.Label>
      <div>
        <ButtonGroup className="imaglr-segmented">
          {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
            <Button key={a} variant={crop.aspect === a ? "primary" : "secondary"} disabled={disabled}
              onClick={() => onChange({ ...crop, aspect: a })}>
              {a === "original" ? "Original" : a}
            </Button>
          ))}
        </ButtonGroup>
      </div>
      {crop.aspect !== "original" ? (
        <Form.Control type="range" min={0} max={1} step={0.01} value={crop.position} disabled={disabled}
          aria-label="Crop position" className="mt-2"
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...crop, position: Number(e.target.value) })} />
      ) : null}
      <div className="imaglr-edges-header">
        <span className="text-muted small">Trim edges (%)</span>
        <span className="imaglr-edges-actions">
          <Button variant="link" size="sm" className="p-0 imaglr-touch" disabled={disabled || detecting} onClick={detect}>
            {detecting ? "Looking for borders…" : "Detect borders"}
          </Button>
          {hasEdges(edges) ? (
            <Button variant="link" size="sm" className="p-0 imaglr-touch" disabled={disabled}
              onClick={() => onChange({ ...crop, edges: null })}>
              Reset
            </Button>
          ) : null}
        </span>
      </div>
      <div className="imaglr-edges">
        {EDGE_NAMES.map((name) => (
          <div key={name} className="imaglr-edge">
            <Form.Label className="imaglr-edge-label" htmlFor={`imaglr-edge-${name}`}>{LABELS[name]}</Form.Label>
            <Button variant="secondary" disabled={disabled || percent(name) <= 0} aria-label={`${LABELS[name]}: trim less`}
              onClick={() => setEdge(name, percent(name) - 1)}>−</Button>
            <Form.Control id={`imaglr-edge-${name}`} className="text-input imaglr-edge-input" type="number" inputMode="numeric"
              min={0} max={MAX_EDGE_PERCENT} step={1} value={percent(name)} disabled={disabled}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEdge(name, Number(e.target.value))} />
            <Button variant="secondary" disabled={disabled || percent(name) >= MAX_EDGE_PERCENT} aria-label={`${LABELS[name]}: trim more`}
              onClick={() => setEdge(name, percent(name) + 1)}>+</Button>
          </div>
        ))}
      </div>
    </Form.Group>
  );
}
