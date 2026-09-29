# Stash plugin facts (verified against v0.31.1)

Research for the build spec §6, done 2026-09-29. Sources were read at git tag `v0.31.1` unless stated;
`T` = `https://github.com/stashapp/stash/blob/v0.31.1/`. v0.31.1 (2026-04-13) is the latest stable release; Docker
`latest` has the same digest. `develop` (v0.31.1-168-gb6b09dd5, 2026-09-22) was diffed: the plugin core files listed
in §9 are byte-identical. Items marked UNCONFIRMED still need a runtime check on the local test Stash.

## 1. Plugin YAML

- Parsed with `yaml.v2` in **strict mode**: any unknown top-level key stops the plugin loading (`T pkg/plugin/config.go#L409-L428`).
- **Plugin ID = the `.yml` filename** without extension, case-insensitive, unique (`config.go#L442`). Stash loads
  **every `*.yml`** under the plugins tree as a plugin, so the package ships exactly one (`imaglrIntegration.yml`) and
  never creates `.yml` files at runtime.
- Fields: `name`, `description`, `url`, `version`, `interface` (`raw` default | `rpc` | `js`), `exec` ([]string),
  `errLog`, `tasks` (`name`, `description`, `execArgs`, `defaultArgs` — string values only), `hooks` (+`triggeredBy`),
  `ui` (`requires`, `csp{script-src,style-src,connect-src}`, `javascript`, `css`, `assets`), `settings`.
- No top-level `requires:` key (strict parser would reject it). Package dependencies are a comment, `# requires: <id>`,
  read by the index builder.
- `exec: [python, "{pluginDir}/imaglr_integration.py"]`: Stash resolves `python`/`python3` via its `python_path`
  setting, then PATH (`T pkg/python/exec.go#L29-L61`). `{pluginDir}` is substituted in args only. Working directory
  is Stash's cwd (`/` in Docker), not the plugin dir. `PYTHONPATH` gets the parent of the plugin folder appended.
- UI files are served concatenated at `/plugin/{id}/javascript` and `/plugin/{id}/css`; `assets` map under
  `/plugin/{id}/assets` (`T internal/api/routes_plugin.go`).
- Page CSP: `connect-src` is `data: 'self' ws: wss:` plus plugins' `ui.csp.connect-src`; `img-src data: *`;
  `child-src 'none'` (`T internal/api/server.go#L554-L624`). Our UI never calls imaglr directly, so no CSP entry is needed.
- CommunityScripts' validator additionally requires `version` to match `^\d+(\.\d+)?(\.\d+)?$` (no `-beta`).

## 2. Settings

- Types: `STRING`, `NUMBER`, `BOOLEAN` only. No list, secret, password, select or default value
  (`T pkg/plugin/setting.go`). STRING renders as a plain visible text box.
- Stored in plain text in Stash's `config.yml` under `plugins.settings.<id>`; unsaved settings are absent.
- **Not passed to the plugin.** Python must query `configuration { plugins(include: ["imaglrIntegration"]) }`.
- `configurePlugin(plugin_id, input: Map!)` replaces the whole map; undeclared keys are allowed and survive the stock
  settings UI's saves (it spreads existing values). Risk: a stale Settings page could overwrite them (inferred).
- `configuration.general.apiKey` is readable by any authenticated client, so settings are no less exposed than Stash's own key.

## 3. Operations and tasks

```graphql
runPluginTask(plugin_id: ID!, task_name: String, description: String, args_map: Map): ID!   # job id
runPluginOperation(plugin_id: ID!, args: Map): Any
```

**runPluginOperation**
- Synchronous, **outside the job queue**, runs concurrently with jobs and other operations.
- Returns the plugin's `output`. A non-null `error` fails the GraphQL call with that message.
- Ignores `execArgs`/`defaultArgs`; put a `mode` in `args`.
- **The process is killed if the HTTP request ends** (tab closed, proxy timeout). Keep operations short.
- No size or time limit in Stash's code; proxy/body limits UNCONFIRMED.

**runPluginTask**
- Queued in Stash's single job queue.
- The plugin's `output` is only logged, never returned.
- **The job ends FINISHED even when the plugin returns `error` or exits non-zero**; it FAILS only if the process
  couldn't start (`T internal/manager/task_plugin.go#L19-L46`). The real outcome must be recorded in the plugin DB.

**raw protocol**
- stdin: the whole input JSON, then closed.
- stdout: read in full and parsed as `{"error": ..., "output": ...}`. **Any stray print to stdout breaks it.**
  All logging goes to stderr.

**From the UI**
- `PluginApi.utils.StashService.mutateRunPluginTask` appears to drop args (sends `args`, document declares `$args_map`;
  still so on `develop`). Inferred from code, UNCONFIRMED at runtime.
- There is no generated helper for `runPluginOperation`.
- Use our own GraphQL call (Stash's Apollo client or `fetch` to the base-href-relative `graphql` URL). Same-origin
  cookies authenticate it.

## 4. Plugin input and authenticating back to Stash

```json
{"server_connection": {"Scheme": "http|https", "Host": "0.0.0.0", "Port": 9999,
  "SessionCookie": {"Name": "session", "Value": "..."}, "Dir": "<config dir>", "PluginDir": "<plugin dir>"},
 "args": {}}
```

- No `ApiKey` field.
- Host may be `0.0.0.0`/`::`/empty: map these to `127.0.0.1`.
- `SessionCookie` can be null.
- The cookie is a new session for the calling user. It is generated even with no credentials configured, and then ignored.
- It expires after `max_session_age` (default 3600 s) unless refreshed through a cookie jar.
- API key: `ApiKey` header or `?apikey=`. A wrong key is rejected outright. A key exists only when a username is set.

**Approach that works in every auth setup** (same as `stashapp-tools` with `force_api_key`):
1. Build the URL from Scheme/Host/Port, mapping wildcard hosts to loopback.
2. Use a cookie-jar session seeded with `SessionCookie.Value`.
3. Query `configuration { general { apiKey } }`; if non-empty, also send `ApiKey`. This survives tasks longer than the cookie's life.

## 5. Logging and progress

- stderr lines are `\x01<level>\x02<message>`. Levels `t d i w e`, plus `p` for progress as a float 0–1 (tasks only;
  dropped if the channel is busy).
- Unprefixed lines use `errLog` (default error). Log lines appear on Settings → Logs as `[Plugin / <name>]`.
- Plugins cannot set sub-tasks.
- **v0.31.1 bug:** a stderr line over 64 KB permanently breaks the log pipe (fixed on `develop`, #7171, unreleased).
  Keep every line well under 64 KB.

## 6. Job queue and cancellation

- **One job at a time**, shared with scans, generate, identify and package installs (`T pkg/job/manager.go#L15`).
  A long plugin task blocks all other Stash jobs, including updating this plugin.
- Cancel (`stopJob`) sends **SIGKILL** (TerminateProcess on Windows) with no grace period. The plugin is not told, and
  **child processes such as ffmpeg are orphaned** (inferred). Mitigations:
  - start ffmpeg in its own process group, with a watchdog that kills it when the parent dies;
  - use a cooperative cancel flag in the plugin DB, set by an operation.
- No task timeout.
- Polling: `jobQueue`, `findJob(input:{id})` and the `jobsSubscribe` subscription. `findJob` keeps only the last 10
  finished jobs and returns `null` after that. Job state is in memory and lost on restart.
- **No startup hook** exists. Hooks are only `<Object>.(Create|Update|Destroy).Post` and `Tag.Merge.Post`.

## 7. Where the plugin may write, and updates

- Packages install to `<pluginsPath>/<source local path>/<id>/`.
- Update and uninstall delete **only files listed in the package `manifest`** (the zip's contents). Uninstall then
  calls `os.Remove(dir)`, which fails silently if the directory isn't empty.
- **Runtime files the plugin creates in its own folder survive updates and uninstall.** Never ship a zip file with the
  same name as a runtime file.
- Other locations, from `configuration.general`: `generatedPath`, `cachePath` (can be empty on bare metal),
  `pluginsPath`, `configFilePath`; and `server_connection.Dir`.
- No official guidance on plugin databases. Precedent: `MosaicPoster` writes `<pluginDir>/generated/`; `timestampTrade` uses sqlite3.
- Operations, hooks and tasks run concurrently, so SQLite needs WAL mode and a busy timeout.

## 8. Runtime environment

Official image `stashapp/stash:v0.31.1` (checked from its layers):

| Item | Value |
|---|---|
| OS | Alpine 3.23.3 |
| Python | 3.12.13 at `/usr/bin/python3`, PEP 668 externally managed (plain `pip install` fails) |
| stdlib | `sqlite3` present |
| ffmpeg / ffprobe | 8.0.1 at `/usr/bin/` |
| exiftool | **absent** |
| Pillow | **absent** |
| pip packages | requests, requests_toolbelt, lxml, stashapp-tools 0.2.59, mechanicalsoup, cloudscraper, bs4 |
| Other | `vips`, `vips-tools`, `vips-heif` |

- Stash has **no dependency-install mechanism**. The community `PythonDepManager` only works for plugins installed
  from the same source, so it isn't usable from our own index.
- Bare-metal and Windows installs can't be assumed to have even `requests`.
- ffmpeg is always present, because Stash itself requires it. Resolve the binaries with
  `systemStatus { ffmpegPath ffprobePath }` (resolved paths), not `configuration.general.ffmpegPath` (may be empty).
- Windows: read stdin as bytes and decode UTF-8 (inferred).

## 9. Distribution

- **Source index** (`index.yml`): a list of `{id, name, version, date, requires, path, sha256, metadata.description}`.
  - `date` is UTC `YYYY-MM-DD HH:MM:SS`.
  - **Updates are detected by `date` only**; `version` is display text.
  - A package is identified by (id, source URL), so an install from our index only updates from our index.
  - The index is fetched with a 10 s timeout, so keep the zip small.
  - SHA-256 mismatch is a hard error. `requires` only resolves within the same index.
- **Zip:** the plugin folder's contents, with the `.yml` at the root.
- **Own index:** `stashapp/plugins-repo-template` (AGPL-3.0). Put the plugin in `plugins/<id>/`; the Pages source is
  GitHub Actions. On push to `main` touching `plugins/**`, `build_site.sh` publishes
  `https://<user>.github.io/<repo>/main/index.yml`. Version string = `<yml version>-<short hash>`; date = last commit
  touching the folder.
- **Build output:** there is no build step in CI; the zip is whatever is committed under `plugins/<id>/`. Built JS is
  committed there (readable, not minified); Node tooling lives outside the plugin folder.
- **CommunityScripts:**
  - Same layout; validator CI (AJV strict schema; `name` required; `additionalProperties: false`).
  - Keep `description` single-line and plain, because `build_site.sh` greps it raw into the index.
  - No CONTRIBUTING file.
  - The README allows LLM-assisted plugins only with open disclosure, human review, human testing, and author
    responsibility. The maintainer has declined a very large LLM-heavy plugin (PR #738) and objects to
    `package.json`/lockfiles in plugin folders.
  - `url:` conventionally points to a Discourse topic.
  - Listing: a topic in the Discourse plugins category, which needs Plugin Developers group membership.
  - Own indexes can be added to the "List of plugin sources" wiki post.
- **Licences:** stash, CommunityScripts and the template are AGPL-3.0; an MIT plugin has been accepted (StashRandomButton).
- Code of conduct: docs.stashapp.cc/code-of-conduct (Contributor Covenant 2.1).

## 10. UI plugin (`PluginApi`)

`S` = `https://github.com/stashapp/stash/blob/v0.31.1/ui/v2.5/src/`.

**Stack**
- React 17, react-bootstrap 1.6 / Bootstrap 4.6, react-router-dom 5, Apollo 3.8, react-intl 6, FontAwesome, react-select 5.
- No React 18 APIs (`createRoot`, `useId`, etc.).

**What `window.PluginApi` exposes** (`S pluginApi.tsx#L69-L189`)
- `React`, `ReactDOM`.
- `GQL`: every generated Apollo hook, e.g. `useFindSceneMarkersQuery`, `useJobsSubscribeSubscription`,
  `useRunPluginTaskMutation` (pass `args_map`), `useConfigurePluginMutation`, `useBulkImageUpdateMutation`.
  There is no `runPluginOperation` document: write our own `gql`.
- `libraries`: `ReactRouterDOM`, `Bootstrap`, `Apollo`, `Intl`, FontAwesome sets, `ReactFontAwesome`, `Mousetrap`,
  `ReactSelect`, `ReactSlick`. video.js is not exposed.
- `register.route(path, FC)`, `register.component`, `patch.before/instead/after`.
- `components` and `loadableComponents`: call `hooks.useLoadComponents` before using lazy ones.
- `hooks`: `useSpriteInfo`, `useToast`, `useLoadComponents`, …
- `utils`: `NavUtils`, `StashService.getClient()`.
- `Event`: only `stash:location` is dispatched. Also check `window.location` at startup, because the first event can
  fire before plugins load.

**Delivery**
- The JS is loaded as a **classic script** (concatenated), so the bundle must be an **IIFE with no import/export**.
- **Never bundle React**: use `PluginApi.React` (tsconfig `jsx: react`).
- Use inline source maps only.
- Plugins are skipped in Stash's troubleshooting mode.

**Routes**
- Register **`/plugins/imaglr-integration`** (plural). `/plugin/...` belongs to the server's asset routes, so a
  refresh or deep link there returns 404 (stash#5124).
- This corrects the spec's `/plugin/imaglr-outbox`.

**Where our buttons go**
- **Nav:** `before("MainNavBar.MenuItems")` using Stash's own `Nav.Link` markup, with a duplicate guard.
  `MainNavBar.UtilityItems` also exists, but on phones it appears only inside the hamburger menu.
- **Settings:** `before("SettingsToolsSection")` adds a link row. `instead("PluginSettings")` could replace the stock
  settings UI; not planned.
- **Scene page:** the toolbar and operations menu are not patchable. The supported way is a tab via
  `ScenePage.Tabs` + `ScenePage.TabContent` (props include the full `scene`) — e.g. an "imaglr" tab for marker
  creation and send.
- **Markers:** there is no marker detail page. `SceneMarkerCard.*` is patchable, for the markers wall.
- **Image page:** `ImageDetailPanel` (props `{image}`) is patchable. A toolbar button needs DOM injection on
  `stash:location`.
- **Images list bulk action:** `before("FilteredImageList")` adding to `extraOperations`
  (`{text, onClick(result, filter, selectedIds), isDisplayed}`). Only when `props.view === "images"`.

**GraphQL**
- Use Stash's Apollo client: plugin components render inside its `ApolloProvider`, sharing cache and auth.
- Outside React, use `fetch(<base href> + "graphql")`.
- WebSocket subscriptions may fail behind a proxy without Upgrade headers, so poll `findJob`/`jobQueue` as the fallback.

**CSP**
- `media-src blob: 'self'`: video only from the same origin.
- No iframes; workers only from `blob:`; `img-src data: *`.

**Media URLs**
- They are absolute (`scheme://host{prefix}/…`, or `external_host`).
- `paths.stream` and direct `sceneStreams` carry `?apikey=` when a key exists. Screenshots, previews, sprites, VTT,
  marker and image URLs don't.
- The session cookie authenticates same-origin `<img>`/`<video>` in every auth mode.
- **Rebuild every media URL as `location.origin + pathname + search`.** This avoids cross-origin or mixed-content
  breakage when `external_host` differs or a TLS proxy omits `X-Forwarded-Proto`.

**Player**
- `ScenePlayer` is loadable but single-instance (fixed element id), records play activity, and has no crop overlay
  hook. The clip editor uses a plain `<video playsinline>` on the stream URL.
- Scrub bar: build it from `hooks.useSpriteInfo(paths.vtt)`.

**Base path**
- Behind a reverse proxy, Stash sets `<base href>` from `X-Forwarded-Prefix`.
- Use router `Link`/`history` for navigation. Build API URLs from `<base href>`, never from `/`.

**Mobile**
- Bootstrap 4 breakpoints; Stash treats `max-width: 576px` as mobile and `pointer: coarse` as touch.
- On phones the navbar is **fixed to the bottom** (48.75 px, body padded), so our bottom action bars must sit above it.
- Toasts move to the bottom.
- Card grids use `div.row.justify-content-center` with fixed zoom widths, and go full width at ≤576 px.

**Theme**
- Dark only (Blueprint palette; body `#202b33`, card `#30404d`, primary `#137cbd`).
- No Stash CSS variables beyond Bootstrap's.
- Look native by using react-bootstrap, `.card`, `Button className="minimal"`, and `PluginApi.components.Icon`,
  `LoadingIndicator`, `Setting*`.

**Patterns to copy (CommunityScripts)**
- `AIOverhaul`: routes, nav, settings link, scene tab.
- `visage`: page injection.
- `CommunityScriptsUILibrary/cs-ui-lib.js`: base-path-aware GraphQL, plugin config get/set.
- `SmartResolve`: toast capture.

## 10a. Observed on the local test Stash (v0.31.1 and development build, 2026-09-29)

- Animated GIF → `VideoFile` with `format: "gif"`. Animated WebP → `ImageFile` with `format: "webp"`.
  Both must be sent as animations.
- JPEGs written by ffmpeg report `format: "mjpeg"`; JPEGs decoded from inside a zip report `"jpeg"`.
  Treat both as JPEG.
- TIFF and BMP are not scanned with Stash's default image extensions. AVIF is.
- **Byte-identical files become one image with several `visual_files`** (here a loose JPEG and a zip member).
  The plugin must pick one file deliberately (the first in `visual_files`, as Stash does) and not assume one.
- ffprobe reports 0×0 for animated WebP; Stash falls back to another decoder. Our ffprobe use must handle this.
- First-run setup can be scripted with the `setup` mutation; login can be toggled with `configureGeneral`
  (`dev/seed.py`).

## 11. Design consequences (proposed; owner to confirm where noted)

1. **Python stdlib only.** `urllib` with an explicit `User-Agent` (imaglr only rejects urllib's *default* agent),
   `sqlite3`, `json`, `subprocess`. No vendored packages, so the zip is platform-independent.
2. **No Pillow, no exiftool. All image work uses Stash's ffmpeg/ffprobe plus small pure-Python container rewriters.**
   - Lossless strip: rewrite JPEG segments (drop APPn except JFIF/ICC, COM), PNG chunks (drop tEXt/zTXt/iTXt/eXIf/tIME),
     WebP RIFF chunks (drop EXIF/XMP) and GIF extensions (drop comments/XMP, keep NETSCAPE loop).
   - Re-encode (orientation, crop, AVIF/HEIC/TIFF/BMP → JPEG/PNG, size guard): ffmpeg with `-map_metadata -1`.
   - Verify ffmpeg's handling of JPEG EXIF orientation on the local test Stash.
3. **Outcomes live in the plugin DB**, because tasks always report FINISHED. The UI shows state from a `status`
   operation, and uses `jobQueue`/`jobsSubscribe` only for progress.
4. **Operations stay fast** (they die with the HTTP request). All encoding and uploading runs as tasks.
5. **Data directory:** `<PluginDir>/data/` holds `imaglr.sqlite` (WAL) and, by default, `prepared/` (processed files awaiting upload). Nothing in the zip
   uses those names. Uninstall leaves this folder behind; the README says how to remove it.
6. **imaglr keys** (several, one per blog) don't fit STRING settings. Proposal: keep them in the plugin DB, managed
   from the plugin's own settings screen, never returned to the browser after entry (masked). This avoids
   plain-text keys in `config.yml` and in `configuration` responses. Simple options (queue tag, done tag, CRF, etc.)
   stay as Stash plugin settings. *Owner to confirm.*
7. **Cancellation:** ffmpeg runs in its own process group; a DB cancel flag is checked between steps; `recover` (on
   page open) marks jobs failed only if Stash's `jobQueue` has no running task for them.
8. **Stash auth:** as in §4 — cookie jar plus API key when one exists. Works with no auth, password auth and API keys.
9. **UI build:** TypeScript + React 17 types, esbuild → one IIFE `imaglrIntegration.js` + `.css`, React and all
   Stash libraries taken from `PluginApi`, nothing framework-sized bundled. Styling via Stash's Bootstrap classes
   first, a small plugin stylesheet second.
10. **Stash-page entry points:** nav item; "imaglr" tab on the scene page (create marker, send markers); image page
   button (DOM injection) and `ImageDetailPanel`; bulk "Add to imaglr" in the Images list; marker-wall cards.
11. **Repo layout:** `plugins/imaglrIntegration/` holds only runtime files (`imaglrIntegration.yml`, Python package,
   built `imaglrIntegration.js`/`.css`, README). Source, tests and Node tooling live outside it.
