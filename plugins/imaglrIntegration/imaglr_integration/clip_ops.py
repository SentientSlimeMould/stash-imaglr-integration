# SPDX-License-Identifier: AGPL-3.0-only
"""Operations for clips and pictures: saving a still from a clip, finding black borders to trim."""

from __future__ import annotations

from typing import Any

from . import items as repo
from . import jobs, services
from .context import Context, UserError


def op_still_create(ctx: Context) -> dict[str, Any]:
    """Grab the frame at `t` from a clip as a new picture item, with the clip's tags."""
    clip = repo.get_item(ctx.db, ctx.arg("item_id"))
    if clip is None or clip["kind"] != "clip":
        raise UserError("That clip no longer exists. Refresh the page.")
    t = ctx.arg("t", float)
    still = repo.create_item(ctx.db, kind="still", source_item_id=clip["id"], still_t=t, tags=clip["tags"],
                             source_title=f"{clip['source_title']} · still at {t:.1f}s", blog_id=clip["blog_id"])
    try:
        frame = jobs.grab_still(ctx, clip, t, still["id"])
    except jobs.JobFailed as e:
        repo.delete_item(ctx.db, still["id"])
        raise UserError(e.detail) from None
    still = repo.update_item(ctx.db, still["id"], source_path=frame)
    return {"item_id": still["id"], "thumb": services.prepared_url(still["id"], frame)}  # type: ignore[index]


def op_crop_detect(ctx: Context) -> dict[str, Any]:
    """Edge trims that cut the black borders off an item's picture (a clip is sampled across its range).
    Nothing is saved: the editor shows the result and the user decides."""
    item = repo.get_item(ctx.db, ctx.arg("item_id"))
    if item is None or item["kind"] == "set":
        raise UserError("That item no longer exists. Refresh the page.")
    try:
        return {"edges": jobs.detect_borders(ctx, item)}
    except jobs.JobFailed as e:
        raise UserError(e.detail) from None


OPERATIONS = {
    "still_create": op_still_create,
    "crop_detect": op_crop_detect,
}
