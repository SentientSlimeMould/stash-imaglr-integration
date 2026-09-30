// SPDX-License-Identifier: AGPL-3.0-only
// An "imaglr" section on an image's own page, under Stash's details (ImageDetailPanel is the only part
// of that page Stash lets plugins patch; the ⋯ menu isn't). Same action as the image lists' ⋯ menu:
// Add to imaglr; or, when the image is already waiting, a link to open it on the Post to imaglr page.
import React from "react";
import { runOperation } from "./api.ts";
import { ROUTE } from "./routes.ts";

interface ImageProps {
  image: { id: string; tags: { id: string; name: string }[] };
}

interface Status {
  card_id: string | null;
  queue_tag: string;
  sent_tag: string;
}

function ImaglrSection({ image }: ImageProps) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const Toast = PluginApi.hooks.useToast();
  const [status, setStatus] = React.useState<Status | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    runOperation<Status>("image_status", { image_id: image.id }).then((s) => live && setStatus(s), () => undefined);
    return () => { live = false; };
  }, [image.id]);

  async function add() {
    setBusy(true);
    try {
      const result = await runOperation<{ post_id: string | null; added: number }>("add_images", { image_ids: [image.id], as_one_post: false });
      const s = await runOperation<Status>("image_status", { image_id: image.id });
      setStatus(s);
      Toast.success(result.added ? "Added to imaglr." : "Already on the Post to imaglr page.");
    } catch (e) {
      Toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;
  const has = (name: string) => image.tags.some((t) => t.name.toLowerCase() === name.toLowerCase());
  let body: React.ReactNode;
  if (status.card_id) {
    body = <Link to={`${ROUTE}?tab=images&open=${status.card_id}`}>Waiting to be sent — open</Link>;
  } else {
    body = (
      <>
        <Button variant="secondary" size="sm" disabled={busy} onClick={add}>Add to imaglr</Button>
        {has(status.sent_tag) ? <span className="text-muted ml-2">Sent before.</span> : null}
      </>
    );
  }
  return (
    <div className="imaglr-image-section">
      <h6>imaglr</h6>
      {body}
    </div>
  );
}

export function patchImagePage() {
  PluginApi.patch.instead("ImageDetailPanel", (props: ImageProps, _context: unknown, Original: React.FC<ImageProps>) => (
    <>
      <Original {...props} />
      <ImaglrSection image={props.image} />
    </>
  ));
}
