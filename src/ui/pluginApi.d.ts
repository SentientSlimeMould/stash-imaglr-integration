// SPDX-License-Identifier: AGPL-3.0-only
// The parts of Stash's window.PluginApi this plugin uses (Stash v0.31.1, ui/v2.5/src/pluginApi.tsx).
// React is Stash's own: 17 up to v0.31.x, 18 from v0.32.0. The types are React 18's, so use nothing React 18 adds
// (createRoot, useId, useTransition, …) while v0.31.x is supported: see docs/stash-plugin-facts.md §10.
// Libraries that aren't worth full typings stay `any`.

import type * as ReactTypes from "react";

type Patch = (component: string, fn: (...args: any[]) => any) => void;

declare global {
  const PluginApi: {
    React: typeof ReactTypes;
    ReactDOM: any;
    ReactDOMClient?: any; // v0.32.0 and later only; unused
    libraries: {
      Bootstrap: any;
      ReactRouterDOM: any;
      FontAwesomeSolid: Record<string, any>;
      [name: string]: any;
    };
    components: Record<string, any>;
    loadableComponents: Record<string, () => Promise<unknown>>;
    register: {
      route: (path: string, component: ReactTypes.FC) => void;
    };
    patch: { before: Patch; instead: Patch; after: Patch };
    hooks: Record<string, any>;
    utils: Record<string, any>;
    Event: EventTarget;
  };
}
