// SPDX-License-Identifier: AGPL-3.0-only
// `import React from "react"` resolves here at build time (scripts/build.mjs), so the bundle uses
// Stash's own React instance instead of shipping a second copy.
export default PluginApi.React;
