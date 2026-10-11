# MimicKit Launcher a0.2.5 (draft - not released yet)

Vibe coded with AI, light testing. GPL-3.0-or-later.

- **Continue from run...** - start the selected config from another run's newest model.pt (e.g. continue a policy
  trained on one clip with a bigger dataset). Parent links across output folders carry total training time, session
  count and chart history (grey, dotted links between sessions); chains are followed over several hops.
- **Chronological Watch** - one character from the start of the clip, no random start or early resets (generated view
  env yaml under output/_launcher_watch/, MimicKit's data folder is untouched), `--num_envs 1`.
- **Render preview MP4** - records one clip length on the CPU in a separate background process (no GPU memory, can't
  disturb training), renders it with MuJoCo on all cores and opens `preview_<iteration>.mp4`. RAM-capped at 80% of
  free RAM with a clean abort. Preview device setting: Auto (CPU, GPU fallback) / CPU only / GPU (needs ~600 MB free VRAM).
- Since a0.1.5: training/Watch runs survive the launcher closing or crashing and are reattached on the next start.
