// SPDX-License-Identifier: AGPL-3.0-only
// The plugin's menu icon, in Font Awesome's icon-definition format so Stash's Icon component renders it
// like its own menu icons (same size, colour and active state). Path supplied by the project owner.
// The small circle is drawn the opposite way round so it cuts a hole under the nonzero fill rule.
const PATH =
  "M256 32A224 224 0 1 0 256 480A224 224 0 1 0 256 32Z" +
  "M256 96A160 160 0 1 1 256 416A160 160 0 1 1 256 96Z" +
  "M256 144A112 112 0 1 0 256 368A112 112 0 1 0 256 144Z" +
  "M310 181A34 34 0 1 1 310 249A34 34 0 1 1 310 181Z";

export const imaglrIcon = {
  prefix: "imaglr",
  iconName: "imaglr",
  icon: [512, 512, [], "e001", PATH],
} as const;
