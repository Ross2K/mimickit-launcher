# Changelog

All notable changes to MimicKit Launcher, newest first. Versions are `aX.Y.Z` (alpha). The version string lives in one
place: `VERSION` in `mkl/core.py`.

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
