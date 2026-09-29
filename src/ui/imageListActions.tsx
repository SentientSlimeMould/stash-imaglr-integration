// SPDX-License-Identifier: AGPL-3.0-only
// "Add to imaglr" entries in the ⋯ menu of every Stash image list (Images page, a gallery's Images tab,
// performer/studio/tag image tabs). FilteredImageList takes `extraOperations`; we wrap it with an
// `instead` patch so our component can use hooks (toasts) and pass the extra entries through.
import React from "react";
import { runOperation } from "./api.ts";
import { ROUTE } from "./routes.ts";
import { addedMessage, galleryIdFromPath, MAX_POST_FILES, type AddResult } from "./lib/imageActions.ts";

interface Operation {
  text: string;
  onClick: (result: unknown, filter: unknown, selectedIds: Set<string>) => Promise<void>;
  isDisplayed?: (result: unknown, filter: unknown, selectedIds: Set<string>) => boolean;
  postRefetch?: boolean;
}

interface ListProps {
  view?: string;
  filterHook?: unknown;
  extraOperations?: Operation[];
  [key: string]: unknown;
}

function ImageListWithImaglr({ props, Original }: { props: ListProps; Original: React.FC<ListProps> }) {
  const Toast = PluginApi.hooks.useToast();
  const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
  const history = useHistory();
  const location = useLocation();
  const galleryId = props.view === "gallery_images" ? galleryIdFromPath(location.pathname) : null;

  async function add(ids: string[], asOnePost: boolean) {
    try {
      const result = await runOperation<AddResult>("add_images", { image_ids: ids, as_one_post: asOnePost });
      Toast.success(addedMessage(result, asOnePost));
      if (asOnePost && result.post_id) history.push(`${ROUTE}?open=${result.post_id}`);
    } catch (e) {
      Toast.error(e);
    }
  }

  const operations: Operation[] = [
    {
      text: "Add to imaglr",
      isDisplayed: (_r, _f, ids) => ids.size > 0,
      onClick: (_r, _f, ids) => add([...ids], false),
      postRefetch: true,
    },
    {
      text: "Add to imaglr as one post",
      isDisplayed: (_r, _f, ids) => ids.size > 0,
      onClick: async (_r, _f, ids) => {
        if (ids.size > MAX_POST_FILES) {
          Toast.error(`An imaglr post holds up to ${MAX_POST_FILES} images. You've selected ${ids.size}.`);
          return;
        }
        await add([...ids], true);
      },
      postRefetch: true,
    },
  ];

  if (galleryId) {
    operations.push({
      text: "Add gallery to imaglr as one post",
      isDisplayed: (_r, _f, ids) => ids.size === 0,
      onClick: async () => {
        try {
          const result = await runOperation<AddResult>("add_gallery", {
            gallery_id: galleryId,
          });
          if (result.too_many) {
            Toast.error(
              `This gallery has ${result.too_many} images, and a post holds up to ${MAX_POST_FILES}. ` +
                `Tick the ones you want, then choose "Add to imaglr as one post".`,
            );
            return;
          }
          Toast.success(addedMessage(result, true));
          if (result.post_id) history.push(`${ROUTE}?open=${result.post_id}`);
        } catch (e) {
          Toast.error(e);
        }
      },
      postRefetch: true,
    });
  }

  return <Original {...props} extraOperations={[...(props.extraOperations ?? []), ...operations]} />;
}

export function patchImageLists() {
  PluginApi.patch.instead("FilteredImageList", (props: ListProps, _context: unknown, Original: React.FC<ListProps>) => (
    <ImageListWithImaglr props={props} Original={Original} />
  ));
}
