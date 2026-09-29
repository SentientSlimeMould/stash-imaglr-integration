// SPDX-License-Identifier: AGPL-3.0-only
// Plugin UI entry point: runs once when Stash loads the plugin's JavaScript.
import React from "react";
import { NavItem } from "./NavItem.tsx";
import { PostPage } from "./PostPage.tsx";
import { ROUTE } from "./routes.ts";

PluginApi.register.route(ROUTE, PostPage);

PluginApi.patch.before("MainNavBar.MenuItems", (props: { children?: React.ReactNode }) => [
  {
    ...props,
    children: (
      <>
        {props.children}
        <NavItem />
      </>
    ),
  },
]);
