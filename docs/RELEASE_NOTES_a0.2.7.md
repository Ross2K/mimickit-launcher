# MimicKit Launcher a0.2.7 (draft - not released yet)

## New in a0.2.7

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

## Since a0.1.5

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
