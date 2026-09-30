// SPDX-License-Identifier: AGPL-3.0-only
// Main menu entry, mirroring Stash's own menu item markup (ui/v2.5/src/components/MainNavbar.tsx)
// so it looks native and closes the phone menu when tapped (Nav.Link eventKey + collapseOnSelect).
import React from "react";
import { imaglrIcon } from "./icon.ts";
import { ROUTE } from "./routes.ts";

export function NavItem() {
  const { Nav, Button } = PluginApi.libraries.Bootstrap;
  const { useHistory, useRouteMatch } = PluginApi.libraries.ReactRouterDOM;
  const { Icon } = PluginApi.components;
  const history = useHistory();
  const active = useRouteMatch(ROUTE) ? " active" : "";

  return (
    <Nav.Link eventKey={ROUTE} as="div" className="col-4 col-sm-3 col-md-2 col-lg-auto">
      <Button
        className={
          "minimal p-4 p-xl-2 d-flex d-xl-inline-block flex-column justify-content-between align-items-center" +
          active
        }
        onClick={() => history.push(ROUTE)}
      >
        <Icon
          icon={imaglrIcon}
          className="nav-menu-icon d-block d-xl-inline mb-2 mb-xl-0"
        />
        <span>imaglr</span>
      </Button>
    </Nav.Link>
  );
}
