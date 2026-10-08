// SPDX-License-Identifier: AGPL-3.0-only
// The plugin's menu icon, in Font Awesome's icon-definition format so Stash's Icon component renders it
// like its own menu icons (same size, colour and active state). imaglr's favicon, inverted for a one-colour
// glyph and drawn to its measured proportions: the wide ring (76-100 % of the radius) and the pupil (55 %)
// are filled, the iris band between them and the large highlight (radius 23 %, up and to the right) show
// the background. The favicon's hairline outer ring is left out: it vanished at menu size. Circles drawn
// clockwise cut holes under the nonzero fill rule.
const PATH =
  "M256 32A224 224 0 1 0 256 480A224 224 0 1 0 256 32ZM256 85.8A170.2 170.2 0 1 1 256 426.2A170.2 170.2 0 1 1 256 85.8Z" +
  "M256 132.8A123.2 123.2 0 1 0 256 379.2A123.2 123.2 0 1 0 256 132.8Z" +
  "M282.9 175.4A51.5 51.5 0 1 1 282.9 278.4A51.5 51.5 0 1 1 282.9 175.4Z";

export const imaglrIcon = {
  prefix: "imaglr",
  iconName: "imaglr",
  icon: [512, 512, [], "e001", PATH],
} as const;
