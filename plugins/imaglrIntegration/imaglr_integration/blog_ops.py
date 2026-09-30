# SPDX-License-Identifier: AGPL-3.0-only
"""Operations behind the plugin's blog settings: add, check, remove, choose default action.

Only GET /user/info and GET /user/limits are used here; both are read-only on imaglr.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from . import blogs
from .context import Context, UserError
from .imaglr import ErrorClass, ImaglrError

PAUSING_CODES = ("premium_required", "account_suspended")


def check_blog(ctx: Context, blog: dict[str, Any], with_limits: bool = False) -> dict[str, Any]:
    """Refresh a blog's profile from imaglr. Returns the public view, plus limits if asked."""
    client = ctx.imaglr(blog)
    limits = None
    try:
        info = client.user_info()
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else info
        blogs.record_check(ctx.db, blog["id"], profile, None)
        if blog["paused_reason"] in PAUSING_CODES and profile.get("supporter") is not False:
            blogs.set_paused(ctx.db, blog["id"], None)
        if with_limits:
            limits = client.user_limits().get("limits")
    except ImaglrError as e:
        blogs.record_check(ctx.db, blog["id"], None, (e.code, e.detail or e.code))
        if e.code in PAUSING_CODES:
            blogs.set_paused(ctx.db, blog["id"], e.code)
    view = blogs.public(blogs.get_blog(ctx.db, blog["id"]))
    view["limits"] = limits
    return view


def op_blogs_list(ctx: Context) -> dict[str, Any]:
    return {"blogs": [blogs.public(b) for b in blogs.list_blogs(ctx.db)]}


def op_blogs_check(ctx: Context) -> dict[str, Any]:
    return {"blogs": [check_blog(ctx, b, with_limits=True) for b in blogs.list_blogs(ctx.db)]}


def op_blog_add(ctx: Context) -> dict[str, Any]:
    try:
        blog = blogs.add_blog(ctx.db, ctx.arg("api_key"), ctx.arg("default_action", required=False) or "draft")
    except blogs.BlogError as e:
        raise UserError(str(e)) from None
    view = check_blog(ctx, blog)
    if view["error_code"] and ImaglrError(view["error_code"]).klass is ErrorClass.AUTH:
        blogs.remove_blog(ctx.db, blog["id"])
        raise UserError("imaglr didn't accept that key. Check you copied all of it, then try again.")
    duplicate = next(
        (b for b in blogs.list_blogs(ctx.db) if b["id"] != blog["id"] and b["name"] and b["name"] == view["name"]),
        None,
    )
    if duplicate:
        blogs.remove_blog(ctx.db, blog["id"])
        raise UserError(f"That key is for {view['name']}, which is already added.")
    return {"blog": view}


def op_blog_remove(ctx: Context) -> dict[str, Any]:
    blogs.remove_blog(ctx.db, ctx.arg("blog_id", int))
    return op_blogs_list(ctx)


def op_blog_set_action(ctx: Context) -> dict[str, Any]:
    try:
        blogs.set_default_action(ctx.db, ctx.arg("blog_id", int), ctx.arg("action"))
    except blogs.BlogError as e:
        raise UserError(str(e)) from None
    return op_blogs_list(ctx)


def op_data_reset(ctx: Context) -> dict[str, Any]:
    """Delete everything the plugin keeps (blogs and keys, history, tag rules, working files): the whole data
    folder. Stash's plugin manager leaves that folder on uninstall, so this is the clean slate. Nothing in
    Stash or on imaglr changes."""
    busy = ctx.db.fetchone("SELECT COUNT(*) AS n FROM items WHERE status IN ('exporting', 'sending')")
    if busy and busy["n"]:
        raise UserError("Something is being sent right now. Wait for it to finish (or stop it), then try again.")
    ctx.db.close()
    ctx._db = None
    # Empty the folder rather than removing it: it may be a mount point (a Docker volume, as in dev/).
    if os.path.isdir(ctx.data_dir):
        for name in os.listdir(ctx.data_dir):
            path = os.path.join(ctx.data_dir, name)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    return {"reset": True}


OPERATIONS = {
    "blogs_list": op_blogs_list,
    "data_reset": op_data_reset,
    "blogs_check": op_blogs_check,
    "blog_add": op_blog_add,
    "blog_remove": op_blog_remove,
    "blog_set_action": op_blog_set_action,
}
