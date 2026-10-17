// SPDX-License-Identifier: AGPL-3.0-only
// "From imaglr" on Stash's own pages: an item saved from imaglr gets its credit as links, to the post and to its
// creator, and a Reblog button. On an image page it opens the Details tab (ImageDetailPanel); on a scene page it is
// its own "imaglr" tab (the scene page offers plugins tabs, not a place in its details). Read from the item's URLs,
// where saving put the post's and the creator's links; anything else shows nothing. Galleries have no place for it,
// so their links stay under Edit, as Stash shows them.
import React from "react";
import { imaglrCredit } from "./lib/posts.ts";
import { ReblogDialog } from "./discover/ReblogDialog.tsx";

export function ImaglrCredit({ urls }: { urls: string[] | null | undefined }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Icon } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  const [reblogging, setReblogging] = React.useState(false);
  const credit = imaglrCredit(urls);
  if (!credit) return null;
  return (
    <div className="imaglr-credit">
      <h6>From imaglr</h6>
      <div className="imaglr-credit-links">
        <a className="btn btn-secondary" href={credit.postUrl} target="_blank" rel="noopener noreferrer">
          <Icon icon={fa.faExternalLinkAlt} /> View the post
        </a>
        {credit.creatorUrl ? (
          <a className="btn btn-secondary" href={credit.creatorUrl} target="_blank" rel="noopener noreferrer">
            <Icon icon={fa.faUser} /> @{credit.creator}
          </a>
        ) : null}
        <Button variant="secondary" onClick={() => setReblogging(true)}>
          <Icon icon={fa.faRetweet} /> Reblog
        </Button>
      </div>
      {reblogging ? <ReblogDialog postId={credit.postId} creator={credit.creator} onClose={() => setReblogging(false)} /> : null}
    </div>
  );
}

type Scene = { scene?: { urls?: string[] } };
const TAB = "imaglr-panel";

/** An after-patch gets the component's arguments, then what it rendered. */
function parts<P>(args: unknown[]): [P, React.ReactNode] {
  return [args[0] as P, args[args.length - 1] as React.ReactNode];
}

export function patchCredit() {
  const { Nav, Tab } = PluginApi.libraries.Bootstrap;
  PluginApi.patch.after("ImageDetailPanel", (...args: unknown[]) => {
    const [props, rendered] = parts<{ image?: { urls?: string[] } }>(args);
    return <><ImaglrCredit urls={props.image?.urls} />{rendered}</>; // first in the Details tab, where it's seen
  });
  PluginApi.patch.after("ScenePage.Tabs", (...args: unknown[]) => {
    const [props, rendered] = parts<Scene>(args);
    if (!imaglrCredit(props.scene?.urls)) return rendered;
    return <>{rendered}<Nav.Item><Nav.Link eventKey={TAB}>imaglr</Nav.Link></Nav.Item></>;
  });
  PluginApi.patch.after("ScenePage.TabContent", (...args: unknown[]) => {
    const [props, rendered] = parts<Scene>(args);
    if (!imaglrCredit(props.scene?.urls)) return rendered;
    return <>{rendered}<Tab.Pane eventKey={TAB}><ImaglrCredit urls={props.scene?.urls} /></Tab.Pane></>;
  });
}
