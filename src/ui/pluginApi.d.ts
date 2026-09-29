// SPDX-License-Identifier: AGPL-3.0-only
// The parts of Stash's window.PluginApi this plugin uses (Stash v0.31.1, ui/v2.5/src/pluginApi.tsx).
// Libraries that aren't worth full typings stay `any`.

import type * as ReactTypes from "react";

type Patch = (component: string, fn: (...args: any[]) => any) => void;

declare global {
  const PluginApi: {
    React: typeof ReactTypes;
    ReactDOM: any;
    libraries: {
      Bootstrap: any;
      ReactRouterDOM: any;
      FontAwesomeSolid: Record<string, any>;
      [name: string]: any;
    };
    components: Record<string, any>;
    register: {
      route: (path: string, component: ReactTypes.FC) => void;
    };
    patch: { before: Patch; instead: Patch; after: Patch };
    hooks: Record<string, any>;
    utils: Record<string, any>;
    Event: EventTarget;
  };
}
