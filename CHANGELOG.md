# Changelog

All notable changes to MimicKit Launcher, newest first. Versions are `aX.Y.Z` (alpha). The version string lives in one
place: `VERSION` in `mkl/core.py`.

## a0.9.2

- Phone PIN: back to **4–12 digits** (as before a0.8.2Z). PINs you already saved with 4 or 5 digits work again with no re-entry. The lockout after 20 wrong PINs per hour stays.
- Preview: new **All clips** checkbox (PC: next to Clips...; phone: Preview options, above the clip list). When it's ticked, the render includes every clip of the training data (up to 64) in the chosen Clip layout, and the clip selector is greyed out. With All at once you get an automatic grid: ceil(sqrt(n)) columns, e.g. 31 clips → 6×6 with 320×240 tiles and a frame at most 1920 px wide. One after another and One long clip play all the clips in sequence. Progress shows in the log and on the phone.
- Updates (A1): the launcher checks for updates automatically on launch and every 6 hours. You can turn it off or change the interval (1–168 h) under **About > Updates**, which also has a Check now button. When there's an update, a small "Update X available" notice appears in the Settings row (click it for details) and a line appears on the phone. It never installs anything by itself. The Z build uses its stored access key and signed-release check; the public build reads the public releases. When offline it stays silent and writes one log line.

## a0.9.1

- Preview: new clip layout **One long clip (all animations)** (PC Clip layout list and phone Render). Renders every training clip back to back in one MP4: up to 64 clips, and if they add up to more than 15 min each clip is shortened to its share (at least 2 s). Uses the same separate preview process as before, so the running training is touched no more than a normal preview. The log and the phone show record/render progress (frame x/n).
- Preview: the record step now gets the chosen clips (before, it could record the first clips instead of the chosen ones).
- Phone: new **Ghost** section to switch the reference ghost (Off / Side by side / Overlay). PIN-protected like the other controls; it applies to the next preview.
- Milestones: if milestones.json can't be written, it no longer raises. The alert fires once and the flag is kept in memory (M1).
- Milestones: if the run chain can't be read, a parent run's level isn't re-fired (M2).

## a0.9.0

New: "First steps!" and "Walking well" alerts (GUI only).

- While training, the launcher watches the scores MimicKit already logs. **"First steps!"** fires once when, for 3
  checks in a row, the test episodes last at least 80 % of the full episode (it stays upright) AND the per-step match
  score (Test_Return / Test_Episode_Length) is at least 20 %. **"Walking well"** fires once at 50 %.
- Shown as a green card on the PC, a banner on the phone page, and sent to Discord / Telegram if those are set up.
- Fires once per run: the flag is kept in the output folder (milestones.json); resuming or continuing doesn't
  repeat it.
- Thresholds in **Training settings -> Milestone alerts** (match score for each level, "stays upright" share,
  checks in a row; or turn the alerts off).
- Why 20 % / 50 %: DeepMimic-style rewards are 0-1 per step, so the per-step score is how closely the clip is
  matched. Falling / flailing policies stay well under 15 %; the undead run that has started to hold itself up is at
  ~21.8 %; well-tracked clips reach 60-80 %.
- No episode length in the log: the match score alone is used (Return / full episode length). Full length = the
  run's episode_length x control_freq (env_config.yaml / engine_config.yaml in the output folder).

## a0.8.9

Dark-mode polish + review fixes (GUI only).

- Input boxes stand out: #0d0d0d fields with a #555 border and focus ring (box edges stay #333).
- Scrollbars: #6a6a6a thumb on a #1a1a1a trough.
- Disabled buttons / boxes: #5a5a5a text on #121212 - no longer the same grey as hint text.
- Drop-down lists are black (also ones opened before a theme switch); the Patches dialog is black.
- The whole-row cut of the top area never hides more than one row.
- Drop-down / number boxes shown or added later anywhere in the top area get the "wheel only when focused" rule.
- Tests: fixes042 also retries the 0.0.0.0 re-bind with a fresh port; qa088 checks the swept folder is gone;
  new qa089_test.

## a0.8.8

True-black dark mode + safer tests (GUI only).

- **OLED dark mode:** the dark look is now true black (#000 background, #0d0d0d panels), like the phone page; the
  charts match (black plots on #0d0d0d), on the PC and in the phone's chart picture.
- **Whole rows at the cut:** when Settings / What to run scrolls, the visible part ends after the last whole row,
  so the "▾ More settings below" strip never cuts a row in half.
- The drop-down / number box wheel rule (a0.8.7) is set up when the area appears or is re-laid out, not on every
  resize.
- Tests (Windows safety): the test helpers check whether a process runs with OpenProcess/GetExitCodeProcess on
  Windows (never os.kill, which there sends Ctrl+C and could stop a training run) and kill with taskkill there;
  leftover test folders are only removed when their test and its fake sim have ended; a fake sim left behind by a
  timed-out test ends itself; fixes042 retries with another port if the dashboard can't bind.

## a0.8.7

Two charts at 125 % + wheel and scroll polish (GUI only).

- **Charts at 125 %:** the top (Settings / What to run) keeps about 260 px and the charts get at least 312 px, so
  both charts (Return + Speed) show at 1536x864 125 % (they dropped to 199 px / one chart in a0.8.6).
- **Mouse wheel:** drop-down lists and number boxes (Training config, num_envs) change their value with the wheel only
  when you've clicked into them; otherwise the wheel scrolls the top area.
- **"▾ More settings below (scroll)"** strip, 22 px at 125 % (20-24 px), bold, clickable.
- **Chart toolbar** (Home / Save picture / Current session only / Per-step / Return-Speed) wraps onto a second row
  instead of clipping.
- No scrollbar when up to ~32 px would be hidden (was 20) - the space comes from the bottom half.
- Fixes: the wheel handler matches widgets by exact path (a widget named like the top area no longer counts);
  the top area's wheel binding is removed when the window closes (other bindings stay).
- Tests: fixes042 uses a free port and guards a missing dashboard; "GUI responsive" also needs the largest gap under
  2 s; tests remove leftover /tmp/mkl_test_* folders of test processes that have ended; new qa087_test.

## a0.8.6

Easier-to-see scrolling at the top + review fixes (GUI only).

- **More room for Settings / What to run at 125 %:** the top area keeps ~300 px (x your Windows scale) before the
  charts keep their 400 px minimum - the charts give way first now (was only 152 px of top at 1536x864 125 %).
- **Mouse wheel** scrolls the top area anywhere over it (buttons, labels, boxes); drop-down lists and number boxes
  keep their own wheel.
- **Obvious scrolling:** a brighter scrollbar in dark mode and a "▾ more (scroll)" strip at the cut (click it to
  scroll down).
- **No scrollbar for a few pixels:** when less than ~20 px would be hidden, the top area takes them from the bottom
  half instead.
- Fixes: phone cancel then "stop after save" (while armed, before the PC handled it) now ends armed - the reply
  "Already set" only comes when stop-after-save is really wanted; wrapped button rows re-check only when the window
  changes (no more 400 ms polling).
- Tests: "GUI responsive" allows ~1 s or one outlier (CPU load from parallel tests); the 125 % child test removes
  its temp MimicKit copy.

## a0.8.5

More room for the charts at 125 % + review fixes (GUI only).

- **Charts keep their room:** when the window is short, the Settings / What to run area scrolls (scrollbar on its
  right) instead of squeezing the charts; the bottom half keeps ~400 px (x your Windows scale).
- **Run buttons pinned:** Start / Resume / Stop after next save / STOP sit just under the scrolling area - always
  visible.
- **Tooltips** appear just below (or beside) the control after a short delay and never cover the buttons on its row.
- The chart caption (what Return / Samples/hour mean) moved into the chart's "?" tooltip; "Hover any control = help"
  moved to the top banner; less padding between boxes.
- Fixes: the phone queue and lock exist before the GPU thread starts; phone "stop after save" / cancel / "stop after
  save" always ends armed (newest request wins); a separate log line when a new run replaced the old one during a
  stop retry; friendlier names in logs ("clip viewer process ended"); wrapped button rows keep each button's spacing
  and pick up buttons added later.
- Tests: the replay test waits for all rows (60 s cap) instead of a fixed time; tests write runs into a temp folder,
  never into the repo.

## a0.8.4

PC layout at 125 % scaling + review fixes (GUI only).

- **Run buttons:** Start / Resume / Stop after next save / STOP have their own row - STOP is always visible. The other
  buttons and the preview options wrap onto more lines instead of running off the window.
- **Charts on short windows:** below ~360 px the per-step chart is hidden; below ~250 px one chart is shown with
  Return / Speed tabs - no more squashed strips.
- **Left column:** Status + Output scroll together when the window is short; Output always keeps ~150 px.
- **Phone confirms:** Cancel left, Yes right, same size, 16 px apart. Red only for Stop / Revert / Replace, blue for
  Start / Continue / Install / Resume. Resume and the parallel-sims change have Cancel too. Theme toggle is 44 px.
- Messages name what is running ("A preview is running. Close it first.") instead of "Something is already running"
  or raw "(preview)". "loading…" / "Rendering…".
- Fixes: the stop-after-save retry never touches a new run started while it was searching; no Tk calls from the GPU
  poll thread; the log queue exists before the first worker starts; cancelling a just-queued phone "stop after save"
  really cancels it; window size is saved after the close prompt; .bat / .ps1 stored with CRLF.

## a0.8.3

Small phone/wording polish (GUI only, no training or patch files changed).

- Phone dark mode is true black; buttons are at least 44 px tall (easier to tap).
- Phone "Parallel sims": hint "Whole number, e.g. 64" under the field; Start/Continue stay disabled until it is valid.
- Browser tab title matches the header ("MimicKit · run"); PIN label "6–12 digits"; "Working…" everywhere.
- **Phone Stop buttons fixed (Android):** holding a button opened Android's text-select/menu gesture and broke the
  hold. Now every confirm is TAP + "Yes, ..." (auto-cancels after 5 s for stops, 15 s otherwise). Stop now / Stop
  after next save sit in their own row, away from other buttons. Buttons no longer select text or open a menu.
- **Set your phone PIN again once** if the phone says "Phone PIN rules changed" (old PINs were 4-12 digits; now
  6-12 when the phone can reach the PC over the network).
- "Looks trained" only after at least 2 h of training and a plateau that held for 45 min (it fired after 30 min).
- Refusals say what is running ("A preview is running. Close it first."). A saved window position is only reused
  if the whole window fits on today's screen.
- Internal: no Tk calls from background threads, phone stop taps locked against double taps, .bat files kept CRLF.
- Z build: plainer updater messages (technical part under Details); update install is tap + confirm too.
- PC window (1080p): opens at ~85 % of the screen above the taskbar (maximized on screens up to 1600 px wide),
  remembers its size/position/maximized state, minimum 1100x720. The Status view scrolls instead of being cut off.
  Charts use the real screen DPI and shorter axis labels; charts get 3/5 of the width. Startup log line shows DPI
  awareness and Tk scaling.

## a0.8.2

Fixes from the a0.8.1 review, plus the taskbar icon.

- **Taskbar icon (Windows):** the launcher's icon now shows on the taskbar however you start it: the .exe,
  launch.bat, the new `mimickit_launcher.pyw`, or a double-clicked `mimickit_launcher.py` (its extra black console
  window, which showed Python's icon, is hidden). It sets its own taskbar ID before the window opens, uses the
  multi-size .ico, and creates a Start-menu shortcut with the same ID (Windows takes a pinned button's icon from it).
  Old pins keep Windows' cached icon: once, double-click **Fix taskbar icon.bat**, unpin the old button, start the
  launcher and pin it again.
- **Stop after next save:** the retry only stops the right training (exact output folder or the launcher's own
  process), and looks for it in the background, so the window never freezes.
- **Phone control:** a slow action no longer blocks other phones. The button shows "Working..." until the PC answers.
- **PIN:** at least 6 digits. 20 wrong PINs within an hour (from any phones) turn phone control off:
  "Phone control turned off after too many wrong PINs. Turn it back on from the PC." Old lockouts are cleaned up.
- **Patches** are also refused while the launcher's own training process is still alive. Greyed patch buttons on the
  phone say why.
- **Parallel sims field:** if it isn't a whole number it says "Whole number, e.g. 64" and won't start, instead of
  failing or using 0.
- **Phone wording:** "parallel sims" instead of num_envs, "saved progress" instead of model.pt, no _resumeN. The
  always-disabled Save checkpoint button is gone (training saves by itself).
- Dashboard address choice reads "Only this PC (phone can't connect)".
- Z build only: updates are signed (Ed25519) and checked against a key built into the launcher; the update kind is
  re-checked from the changed files (the stricter one wins); the phone install needs a 2-second hold; update errors
  are plain, with a Details toggle.

## a0.8.1

### Added
- **Presets can say which MimicKit files they need.** Until those files are there, the preset is still listed but
  greyed out with a plain hint (for example "run install_....bat once"). That applies to Start, Resume, Continue,
  Watch and View on the PC, and to the phone's Runs list. Once the files are installed it works like any other
  config.
- **Choose which clips the MP4 preview shows** (up to 4). This is for datasets with many clips.
  - PC: the *Clips...* button next to *Clip layout*. The choice is saved per training config, and a preset can set
    sensible defaults.
  - Phone: a clip list under *Preview options* that applies to that one render. The PC checks the names.

### Fixed
- Preview of AMP runs (steering etc.): the preview only forces its chosen clips onto its own reset, so MimicKit's
  AMP demo sampling keeps working.
- Console tables where the returns come before the Iteration row are now read as whole rows. This affects some AMP
  task loggers. Extra AMP rows (Disc_*, Exp_Prob) and a `nan` value are ignored safely.

## a0.8.0

### Added
- **Phone preview controls** on the existing preview card: Play/Pause, a scrub bar with time, and a closed-by-default
  *Preview options* section with clip choice (the last 12 previews), speed 0.25x / 0.5x / 1x, a Loop switch, and
  *Download MP4*. Nothing plays until you press Play. *Render new preview* shows a progress bar.
- **Desktop shortcut**: double-click *Create desktop shortcut.bat* to get a Desktop and Start-menu shortcut that starts
  the launcher without a console and with its own taskbar icon.
- **Built-in QR code** in the Phone dialog. You don't need to install anything for it.
- imgui-bundle (needed by the Newton viewer) is installed automatically the first time it's missing. It tries once
  per session and logs the result.
- **Phone: Runs and MimicKit patches** (in the Controls panel, both closed by default).
  - *Runs*: start a new training run with the same configs and presets the PC offers (num_envs, output folder,
    "overwrite" for a folder that has a run already), or *Continue from run*, picking an earlier run.
  - *MimicKit patches*: see each patch's state and apply or revert it (Z: the death patch too).
  - Each action needs the PIN session, a one-time confirmation for that action, and a 2-second hold. The PC checks
    every request again. Nothing starts while something runs, and patches are refused while training runs. Every
    refusal is logged and shown on the phone.
- Patches are now also refused on the PC while training runs (same rule as the phone).
- Extension points for personal overlays (settings widgets, phone cards and actions, run-ended hooks).

### Changed
- **Charts scroll much faster on long runs.** Only the visible part is drawn, at about one point per pixel, and the
  full redraw waits until scrolling stops. Scroll time per wheel step: 94 ms -> 0.8 ms at 20k points,
  191 ms -> 0.8 ms at 200k points.
- Phone-requested previews render without opening a player on the PC.
- The Phone dialog opens centred on the launcher.
- The taskbar shows the launcher icon from the first moment (AppUserModelID and icon are set before the window shows).
- Phone safety: a wrong-PIN lockout locks only that phone. Each confirmation works only for the action it was opened
  for. Tweaks are applied on the window's own thread. A stop that waits for a save waits at most 60 s, and it is
  logged when that limit is hit.
- a0.6.1 items: the chart "?" badge sits in the title row and is bigger. Tooltips wrap cleanly. The banner shows
  "Will stop after the next save". The y-axis labels no longer overlap. The status column wraps instead of being cut
  off. Training settings stack on narrow screens.

### Fixed
- **Stop after next save** could stay armed and never stop, and do it silently. Two causes:
  1. The "armed" state was cleared *before* the stop was attempted, so a stop that failed left training running with
     nothing on screen.
  2. Under pythonw, any error in the window's timer loop ended that loop without a trace.
  Now:
  - It detects the save from two signals (model.pt and log.txt).
  - It checks that training really ended and retries once if it didn't.
  - Any refusal or error is shown under the button and logged.
  - Window timer errors are caught, logged and shown.

## a0.7.0

### Added
- **Phone Controls panel**: a *Controls* button in the dashboard header opens one collapsible panel (closed by
  default; open/closed and each section remembered on the phone). Sections with counts: *Training* (Stop after next
  save, Stop now, Resume; *Save checkpoint* is shown disabled - MimicKit saves on its own interval),
  and *Next-resume tweaks* (num_envs, shown as pending until the next resume). The MP4 preview card stays where it was.
- **Stop now confirm box** in the dashboard style: *Keep training* is the primary button, *Stop after next save*
  beside it; stopping now needs a 2-second hold that unlocks 3 seconds after the box opens.
- The status line (phone) shows the pending / in-progress action: *Will stop after next save*, *Stopping...*,
  *Waiting for the save to finish...*.
- **Safety, all enforced on the PC**: *Allow phone control (needs a PIN)* (Settings -> Phone + notifications) is off by
  default and needs a PIN (stored only as a salted hash). The phone enters the PIN once for a 12-hour session
  (kept in the phone's storage, never in the URL or the view link); every action also needs a fresh one-time nonce
  from the confirm box. 5 wrong PINs lock sign-in for 5 minutes (time shown). Turning control off or changing the
  PIN revokes every session. Repeated taps count once; a stop during a save waits for the save; Resume is refused
  while anything is running; tweaks are type- and range-checked; every remote action and refusal is logged to the
  Console; refusals return plain-language reasons. Control off: the button reads *Controls: off* (greyed) and the
  panel says *Turned off on the PC*.

### Changed
- *What to run* cleanup (first step of the UX proposal): run buttons are state-aware (Start / Resume / Continue
  dim while something runs, STOP / Stop after next save dim when idle); shorter chart panel title.

### Fixed
- Phone *Total training* showed "-" once the total passed a day (`1 day, 2:03:04` didn't match); it now shows the
  summed time over all sessions.
- Background threads no longer touch Tk: a finished preview is handed to the GUI thread, and the MimicKit folder is
  read from a cached string off the GUI thread. The dashboard checks the token before reading a request body,
  clamps its size and times out idle connections after 10 s.
- The GPU poll thread no longer prints a 'main thread is not in main loop' traceback when the window closes.
- Plateau estimate no longer says *still improving steadily, no plateau in sight* when the last 10 hours gained
  far less than the run's average pace: it says *slowing down* or *plateaued* with the 10-hour gain.

### Not in this release (hidden, not half-working)
- Alerts list and *Stop when...* rules, Live 3D view (Phase 1 replay) and the *New checkpoint ready* card: not
  shipped; see `docs/PHONE_3D_VIEW.md` for the plan. Running the policy on the phone (Phase 2) stays gated on a
  parity test.
- *Save checkpoint* (forced save) needs a MimicKit hook; the button is disabled.

## a0.6.0

### Added
- **Stop after next save**: lets training finish its current iteration and write your saved progress (`model.pt`)
  once more, then stops. The launcher shows *Will stop after next save...*; press the button again to cancel.
- **'?' badge** in the corner of the charts: hover it for the chart help (replaces the hint that popped up whenever
  the mouse was over the charts).
- The About box shows the build (commit) a release zip was made from.

### Changed
- **Charts draw like the phone page**: one smooth line per series, no dot on every data point. Still only the
  visible time range, reduced to about one low/high pair per pixel column; hovering shows the exact nearest data point.
- Plainer wording: *your saved progress (model.pt)*, *number of practice characters (num_envs)*; error codes moved
  out of the main sentence into a grey detail line. Out of GPU memory: one button, *Lower to N and resume*.
- The error banner reads *Training stopped with an error. Your saved progress is safe; see below.* and wraps onto a
  second line instead of being cut off.

### Fixed
- The close dialog (Detach / Stop / Cancel) and every other pop-up open centred over the main window again, kept on
  its monitor; tooltips and the chart hover readout stay inside the window (flipping above / left near the edges).
- Taskbar icon on Windows: DPI awareness and AppUserModelID are set before the first window, the `.ico` uses BMP
  entries Tk can read, window icons are set independently (one failing no longer skips the other), and `launch.bat`
  always prefers `pythonw.exe`.
- Status view on long / resumed runs: *What's happening* no longer stops after *First training iteration done.* -
  it adds a line every 100 iterations (with the scores), new best test scores, and each new `model.pt` save (seen on
  disk, also when the save interval can't be read from the config). The *Episode length* card falls back to log.txt
  (stock MimicKit doesn't print it to the console), and the last-checkpoint line follows the file.
- Phone dashboard dialog: an unknown saved address falls back to *This PC only*.
- `tools/build.py` refuses to build from uncommitted changes or a stale overlay folder, and stamps the commit into
  each zip (`BUILD`).

## a0.5.1

### Added
- **Change num_envs while training**: set a new number in the num_envs box and press *Apply while training*. The
  launcher shows *Waiting for next checkpoint...*, and once the next `model.pt` is saved it stops training and resumes
  from that checkpoint with the new number (next `_resumeN` folder; time, sessions and charts carry over). Press the
  button again to cancel.
- **Own window and taskbar icon** instead of the Python logo (`assets/icon.png` + multi-size `assets/icon.ico`; on
  Windows the launcher sets its own AppUserModelID so the taskbar uses it). To change the icon, replace those two files.
- `launcher_profile.py` can add extra buttons (`ACTIONS`), with a helper that copies files into the MimicKit folder
  after backing up the originals.

## a0.5.0

### Added
- **Status panel**: a Status / Console switch above the output. Status shows the stage, iteration, progress to the next
  save, score / speed / episode-length tiles, the last checkpoint, highlighted warnings and errors, and short
  plain-language lines - all read from MimicKit's console output. The raw console (and the exact command) is one click away.
- **Health banner**: one line at the top - training normally / slowed down / no output for a while / finished /
  stopped / crashed.
- **Error cards** for known failures, each saying what happened, whether training is still safe, and offering one
  fix: GPU out of memory (*Use N envs*), CPU preview crash 0xC0000005 (*Use the GPU for previews*), no `model.pt` yet
  (*Pick a model...*), a yaml typo (*Open the file*), MimicKit folder not found (*Choose folder...*). They replace the
  pop-ups for missing models and a missing MimicKit folder.
- **"Looks trained" prompt** when the plateau estimate reaches 95% (or the target is reached): Render preview / Stop
  training / Keep training, once per run chain, optionally sent to Discord/Telegram (new checkbox in Phone +
  notifications...). The dashboard data carries a `looks_trained` flag.

### Changed
- All pop-ups are dark (themed) like the rest of the window.
- The code is split into modules (`mkl/`: core, window, process, charts, dashboard, settings, status); the longest
  methods are broken up. No behaviour change, all tests green.
- Concise labels; the settings row no longer clips the About / Phone buttons at 1280 px; the version moved into the
  banner; the exact command box moved into the Console view.

## a0.4.2

### Fixed
- Settings, run state, training time, run links, edited training settings and preview state are saved atomically (temp
  file + `os.replace`) with a `.bak` copy of the last good file, through one shared helper (`mimickit_util.py`).
- A damaged settings file is no longer silently reset: a popup asks *"Your settings file was damaged. Restore the
  backup from <date>?"* with **Restore** / **Start fresh**; the damaged file is kept as `settings.json.damaged-<time>`.
- Errors the launcher deliberately ignores are now written to `launcher_errors.log` next to the settings (repeats
  capped, secrets masked) instead of vanishing.
- Phone dashboard: *Who can open it* - **This PC only** (default for new installs) or **My phone and other devices
  (Tailscale recommended)**. Existing setups that listened on all interfaces keep doing so.
- **Show** / **Hide** buttons on the masked Discord webhook and Telegram token fields. Webhook URLs and tokens are
  masked in the error log and notification error texts and never appear on the dashboard.


### Changed (cleanup, no behaviour change)
- Code formatted with `black` (line length 100).
- One `VERSION` constant feeds the window title, the top-left label, the new **About** box and the zip names.
- This `CHANGELOG.md` replaces the separate `docs/RELEASE_NOTES_*.md` files.
- The built starter `.exe` and `__pycache__` are no longer stored in git (the `.exe` is still included in release zips).
- `tools/build.py` runs the test suite before it writes the zips.

## a0.4.0

### New
- **Training settings...**: edit the selected config's episode length, random start / share of starts at the clip
  start, early and pose termination, pose limit, clip end hold (trim or extend the held final pose), learning settings
  (discount, learning rates, action noise, steps per iteration, epochs, save interval, test episodes) and the number of
  envs. Each with a one-line hint. Save writes an edited copy in `output/_launcher_configs/` (originals backed up and
  never changed); it applies on the next Start / Resume / Continue / Watch / Preview, and a running run keeps its files.
  Greyed-out *Coming soon / needs your input* entries: start-speed randomization, start from other animations
  (handoff), steering goal for a walking policy, curriculum, terrain/pushes.
- **Clip start share** MimicKit patch (opt-in, reversible, in *MimicKit patches*): `clip_start_share` in the env yaml.
- **Close popup**: Detach / Stop / Cancel buttons, each with a one-line description, instead of Yes / No / Cancel; dark styled.
- **Smoother charts** (desktop and phone): only the visible time range is drawn, reduced to one low/high pair per pixel
  column (spikes kept). Hover (desktop) or tap (phone) shows the exact nearest data point.

## a0.3.2

### Fixes (phone dashboard charts)

- **No more snap-back when zooming in**: a pinch's second finger landing shortly after the first was taken as a
  double-tap and reset the view. Double-tap now means two quick single-finger taps without movement; deep zoom is kept
  (also through the 10 s refresh).
- **Page scrolling over charts**: a vertical swipe that starts on a chart scrolls the page (`touch-action: pan-y`, the
  direction is decided from the first movement); only a sideways drag pans and a two-finger pinch zooms the chart.

## a0.3.1

### Fixes and additions

- **Phone dialog**: the QR code appears after `pip install qrcode` without restarting (Refresh button; import caches are
  cleared). Links are labelled and ordered Tailscale -> LAN -> hostname (Tailscale CLI used when installed), the QR
  code uses the Tailscale link, and each link has a Copy button.
- **Avg reward per step** (Return / episode length, %) for train and test in Status, an optional third chart and the
  phone dashboard. **Settings -> MimicKit patches...**: an optional, reversible logging patch that shows MimicKit's
  existing episode-length values in the console (backup kept, idempotent); the GTX 10-series solver patch is in the
  same dialog. Without the patch the value comes from log.txt.
- **Preview of view (motion playback) presets**: the joint mapping warning (0.74 m) and the wrong first frame are fixed;
  the clip pose is now recorded from the motion library (the sim's joint state lags a frame in view envs).
- **CPU preview on Windows**: finer checkpoints inside build_env (each MimicKit/Newton import and constructor). If the
  GPU-hidden variant crashes on a PC while the GPU-visible CPU variant works, that is remembered for the PC and later
  previews go straight to it (a ~17 MB GPU footprint, no training impact); the log says so calmly. Preview diagnostics
  still tests both.

## a0.3.0

### New

- **Phone dashboard** (optional, off by default; Settings -> Phone + notifications...): read-only, mobile-friendly
  dark page with status, times, speed, VRAM bar, progress estimate, both charts (touch zoom), the newest preview MP4
  (HTTP range streaming) and a rate-limited *Render preview* button. Token on every request; standard library only;
  never blocks the window or affects training. Guide for Tailscale access: docs/REMOTE_ACCESS.md (no port forwarding).
- **Notifications** (optional): Discord webhook and/or Telegram bot - chart + status every N hours (default 3), new
  preview MP4s (size limits respected), *Send test*. Stored locally only; failures logged, never fatal.

### Also in a0.3.0 (from the a0.2.8 step, not released separately)

- **Preview of every training motion** (the first 4): one env per motion, each forced onto its own motion id from t=0
  (before, the preview always showed whichever motion the reset sampled). New *Clip layout*: All at once (default,
  1x2 / 2x2 grid, one camera per clip, shorter clips hold their last frame) / One after another. Each panel is labelled
  with its clip file name; the reference ghost follows each clip. Ghost default is now **Overlay**.
- **Chart navigation without modes**: left-drag pans time on both charts (always the same time range), the wheel
  zooms time only, the vertical scale stays at the full data range (manual vertical drag only when a chart has visible
  data outside it). Home / double-click = full view + follow; Save picture. The matplotlib mode toolbar is gone.
- **Light/dark charts fixed**: the legend was left in the default style (created after styling), lines now recolour
  live when the theme is switched, slightly stronger grey for earlier sessions and the dotted bridges.
- **Tooltip fix**: the progress-target tooltip could pop up several times (the frame and its children each had one).
  Now one tooltip per widget, at most one on screen, shown after a short delay, closed on leave/click.

## a0.2.7

### New

- **Reference ghost in the preview MP4** - dropdown *Reference ghost*: Side by side (default) / Overlay / Off, saved in
  the settings. The recorder logs the reference pose of the clip the policy tracks (same motion id and time, from the
  env's motion library) and draws it as a translucent orange character, with a Policy / Reference legend.
- **Staged CPU preview (fix for the Windows 0xC0000005 crash)** - Auto now tries, each in a fresh process:
  a) CPU with the GPU hidden + `PYTORCH_JIT=0` + crash tracebacks; b) on a crash, CPU with the GPU visible but unused
  (forced cpu device, stray-CUDA guard, aborted above ~300 MB of GPU memory); c) the GPU as before. The log names the
  variant that ran. CPU only = a then b.
- **Preview diagnostics** button - probes P1-P7 (versions, torch / torch.jit with the GPU hidden, Warp CPU kernel,
  MimicKit imports, build_env on the CPU, a short recording per CPU variant), each isolated with crash tracebacks and
  checkpoints; report in the log and `output/_launcher_preview/preview_diagnostics.txt`.

## a0.2.6 (since a0.1.5)

Vibe coded with AI, light testing. GPL-3.0-or-later.

- **Continue from run...** - start the selected config from another run's newest model.pt (e.g. continue a policy
  trained on one clip with a bigger dataset). Parent links across output folders carry total training time, session
  count and chart history (grey, dotted links between sessions); chains are followed over several hops.
- **Chronological Watch** - one character from the start of the clip, no random start or early resets (generated view
  env yaml under output/_launcher_watch/, MimicKit's data folder is untouched), `--num_envs 1`.
- **Render preview MP4** - records one clip length on the CPU in a separate background process (no GPU memory, can't
  disturb training), renders it with MuJoCo on all cores and opens `preview_<iteration>.mp4`. RAM-capped at 80% of
  free RAM with a clean abort. Preview device setting: Auto (CPU, GPU fallback) / CPU only / GPU (needs ~600 MB free VRAM).
- **Chart zoom and pan** - toolbar under the charts (zoom to rectangle, pan, home, save), mouse-wheel zoom at the
  cursor; your view is kept through the 10 s refreshes until Home or a double-click returns to auto-follow.
  **Current session only** limits the x axis to the running/selected session.
- **Progress estimate** in the Status panel: plateau fit on Train_Return across the run chain (% toward 95% of the
  fitted level + time left at the current speed, shown smoothed and marked rough), or a samples/score target saved per run chain.
- Earlier sessions are labelled simply "earlier sessions" in the charts.
- Preview on Windows with a CUDA GPU: the CPU recording now really stays on the CPU (CUDA hidden with
  `CUDA_VISIBLE_DEVICES=-1`, Warp default device forced to cpu, guard against stray CUDA launches), and the recorder
  initializes Warp exactly like MimicKit training (`enable_backward=False` before Newton loads) with its own kernel
  cache under output/_launcher_preview/warp_cache, so it never writes to the training cache.
- Since a0.1.5: training/Watch runs survive the launcher closing or crashing and are reattached on the next start.
