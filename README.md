# MimicKit Launcher

A small desktop GUI (Windows and Linux) for running [MimicKit](https://github.com/xbpeng/MimicKit):
pick a config, press **Start training**, and watch the reward graph, GPU memory and log - no command line needed.

> ## 🤖 Built by a team of AI agents
> This tool was **created by one person orchestrating a team of AI agents**: a builder, a QA reviewer and a UX reviewer.
> Every change is reviewed and tested before it ships, and the owner approves every release.
> Testing so far: an automated GUI test against a fake MimicKit folder, a real MimicKit clone,
> and day-to-day use on one Windows PC with an 8 GB GTX 10-series card. Expect some rough edges.
> It comes with **no warranty of any kind** (see [LICENSE](LICENSE)).
> **Issues and contributions are very welcome** - see [CONTRIBUTING.md](CONTRIBUTING.md).
>
> This project is **not affiliated with MimicKit** or its authors.

![screenshot](docs/screenshot.png)

## Features

- **Finds your configs automatically**: scans MimicKit's `args/*.txt`, splits them into *training* configs
  (DeepMimic, AMP, ASE, ADD, ...) and *view* configs (`view_motion_*`), and fills in `num_envs`, output folder,
  motion file and engine from each file.
- **Custom args files** (your own characters) and an **Extra args** box for any extra command-line options.
- **View clip / Start training / Resume training / Watch latest model / STOP** buttons.
  - Start warns before overwriting an earlier run.
  - Resume copies the newest `model.pt` into a new `_resumeN` folder and continues from it (nothing is overwritten).
  - STOP kills the whole process tree (`taskkill /T /F` on Windows, process-group kill on Linux).
- **Runs survive the launcher closing or crashing**: MimicKit is started detached (Windows: new process group with a
  hidden console; Linux: its own session) and writes straight into the run's `console_log.txt`; the launcher tails that file.
  PID, command and start time are saved to `launcher_run.json`, so the next launcher window **reattaches** to a still-running
  training or Watch run (replays the log, keeps tailing, timers stay correct). STOP still kills the whole process tree.
  Closing the window while something runs asks whether to keep it running in the background.
- **Command echo**: shows the exact command it runs, so you can copy it into a terminal.
- **Live progress** parsed from MimicKit's console tables (`| Iteration | N |`), with `log.txt` as a fallback when watching a run the launcher did not start (MimicKit writes log.txt rarely, so it can lag): iteration, samples, training time, samples/hour,
  last `model.pt` save, plus charts of Train/Test return and speed.
- **Total training time across resumes**: "Running for (this session)" and "(total)" lines, saved every 10 s to
  `launcher_time.json` in each run folder (older runs are seeded from `log.txt` Wall_Time). Viewing/watching isn't counted.
- **Chart history across resumes**: per-iteration rows are saved to `chart_history.csv` in each run folder; on resume the
  whole chain (original + `_resumeN`) is drawn on one cumulative samples axis, earlier sessions in grey.
- Each training session also saves its console output to `console_log.txt`, so the chart history can be rebuilt later.
  Sessions run with launcher versions before a0.1.3 only have MimicKit's `log.txt` (written rarely), so they may show
  just one point.
- **GPU monitor**: polls `nvidia-smi` every 5 s (memory, utilization, temperature).
- **"Use Newton engine"** switch (on by default) - adds `--engine_config data/engines/newton_engine.yaml`,
  since Isaac Gym does not run on Windows.
- **Dark mode** by default, with a Light mode toggle. Hover tooltips on everything.
- First-run setup asks for your MimicKit folder and auto-detects a venv (`.venv` / `venv` inside or next to it);
  otherwise it uses the Python that runs the launcher.
- One file, standard library + matplotlib. Settings live in `%APPDATA%\mimickit-launcher\settings.json`
  (Windows) or `~/.config/mimickit-launcher/settings.json` (Linux).

## Requirements

- Windows 10/11 or Linux, an NVIDIA GPU with a recent driver.
- A working MimicKit install (see below).
- Python 3.9+ with **tkinter** and **matplotlib** to run the launcher. The MimicKit venv already has matplotlib;
  python.org installers include tkinter. On Linux: `sudo apt install python3-tk`.

## Install and run the launcher

**Easiest (Windows):** download/clone the repo and double-click **`MimicKit Launcher.exe`**. It is a tiny starter
(source in `tools/exe-starter/`) that finds your venv's `pythonw.exe` (from the launcher settings, a `.venv`/`venv`
next to MimicKit, the `MIMICKIT_LAUNCHER_PYTHON` variable, or `pythonw` on PATH) and runs `mimickit_launcher.py`.
If it can't find Python it shows a message saying where it looked. Keep the .exe next to the .py file.
A stand-alone PyInstaller build can be made with the GitHub Actions workflow `.github/workflows/build-exe.yml`.

Or from a terminal:
```bat
git clone https://github.com/curelessSky/mimickit-launcher.git
cd mimickit-launcher
launch.bat
```
Linux: `./launch.sh`. If `launch.bat` picks the wrong Python, run it directly with your MimicKit venv:
`C:\path\to\MimicKit\.venv\Scripts\pythonw.exe mimickit_launcher.py`
(or set the `MIMICKIT_LAUNCHER_PYTHON` environment variable to that path).

On first start, choose your MimicKit folder (the one containing `mimickit\run.py` and `args\`).
The launcher runs MimicKit with the venv Python it finds (you can change it in **Settings**).

## Installing MimicKit on Windows (step by step)

Done in a normal Command Prompt. Python **3.11** from python.org is recommended.

```bat
cd C:\ml
git clone https://github.com/xbpeng/MimicKit.git
cd MimicKit
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install "newton[sim]==1.0.0" "warp-lang==1.12.1"
pip install -r requirements.txt
```

Then download MimicKit's motion/asset data as described in the
[MimicKit README](https://github.com/xbpeng/MimicKit#readme) and unpack it into `MimicKit\data\`.

Quick sanity check:
```bat
python -c "import torch, warp, newton; print(torch.cuda.is_available(), torch.cuda.get_device_name(0), warp.__version__, newton.__version__)"
```
It should print `True`, your GPU name, and the versions.

Why these pins: MimicKit lists Newton **1.0.0** as tested (a plain `pip install newton` gets a newer one), and
**warp-lang must be pinned** because newer Warp releases break on older GPUs (next section) and Warp 1.18+
needs newer drivers/GPUs. `warp-lang==1.12.1` is the version known to work with Newton 1.0.0 here.
`requirements.txt` may try to change these; if so, re-run the `pip install "newton[sim]==1.0.0" "warp-lang==1.12.1"` line afterwards.

## GTX 10-series / Pascal (sm_61) fix

Two problems hit Pascal cards (GTX 1050-1080, Titan Xp, P100...):

1. **`WarpCodegenKeyError: Referencing undefined symbol: J_kj`** - Warp **1.16 and newer** check kernel code more
   strictly, and a kernel in `mujoco_warp` (the solver Newton uses) references a variable that is only defined in one
   branch. Older Warp compiles it fine. **Fix:** `pip install "warp-lang==1.12.1"`.
2. **`libmathdx ... cuFFTDx error` / `tile_matmul` / `tile_cholesky` failures** - MuJoCo-Warp's default
   `solver="newton"` with dense Jacobians uses Warp *tile* kernels built on NVIDIA MathDx (cuBLASDx/cuSolverDx),
   which do not support compute capability 6.1. **Fix:** use the conjugate-gradient solver with sparse Jacobians,
   which avoid those tile kernels. In `MimicKit\mimickit\engines\newton_engine.py`, in `_build_solver`, change

   ```python
   solver="newton",
   ```
   to
   ```python
   solver="cg", jacobian="sparse",
   ```
   One-liner from the MimicKit folder (PowerShell):
   ```powershell
   (Get-Content mimickit\engines\newton_engine.py) -replace 'solver="newton",', 'solver="cg", jacobian="sparse",' | Set-Content mimickit\engines\newton_engine.py
   ```
   CG converges a bit differently than Newton's method, but training works fine. Newer GPUs don't need this.

## VRAM tuning (`num_envs`)

`num_envs` = how many characters are simulated in parallel. More is faster per hour but uses more GPU memory
(roughly linear). Measured on an **8 GB GTX 10-series card** with the Newton engine:

| num_envs | VRAM used |
|---------:|----------:|
| 1024 | ~1.6 GB |
| 4096 | ~5.5 GB |
| 5120 | ~6.8 GB |

If you get `CUDA out of memory` or the PC becomes unresponsive, lower `num_envs` (e.g. 4096 -> 2048).
Leave ~1 GB free for Windows. Watch the GPU line in the launcher while training starts.

## Troubleshooting

| Problem | Fix |
|---|---|
| "MimicKit not found" | Settings -> MimicKit folder must contain `mimickit\run.py`. Then **Save + rescan**. |
| No configs in the lists | The `args` folder is missing or empty - re-clone MimicKit. |
| `No module named torch` / wrong packages | Settings -> Python venv must point at the venv you installed MimicKit into (folder or `python.exe`). |
| `torch.cuda.is_available()` is False / `no kernel image` | Reinstall torch: `pip uninstall -y torch` then `pip install torch --index-url https://download.pytorch.org/whl/cu126` |
| `J_kj` codegen error, `libmathdx`/`tile_matmul` error | See the Pascal section. |
| Isaac Gym import errors on Windows | Keep **Use Newton engine** on. |
| Out of memory | Lower `num_envs` (see above). |
| GPU line says `nvidia-smi not available` | Install/update the NVIDIA driver, or ignore it (only the monitor is affected). |
| Charts stay empty | They fill from the console output after the first iteration table. For runs started elsewhere they read `log.txt`, which MimicKit writes rarely. |
| Launcher doesn't open on Linux | `sudo apt install python3-tk` and `pip install matplotlib`. |
| STOP didn't stop it | Press again; on Windows check Task Manager for leftover `python.exe`. |

## Running the tests

```bash
xvfb-run -a python tests/gui_test.py                 # fake MimicKit tree in tests/fake_mimickit
xvfb-run -a python tests/gui_test.py /path/MimicKit  # real clone (only builds commands; MimicKit deps not needed)
STUB_REPLAY=console.txt STUB_LOG=log.txt xvfb-run -a python tests/replay_test.py  # replay a real console capture
STUB_CRLF=1 STUB_SLEEP=0.008 VERIFY_AT=24 STUB_REPLAY=console.txt xvfb-run -a python tests/replay_test.py  # Windows-like: CRLF, never flushed, slow
xvfb-run -a python tests/time_test.py      # total training time: start/stop/resume/kill/legacy
xvfb-run -a python tests/history_test.py   # chart history across two resumes
```

## Credits

- [MimicKit](https://github.com/xbpeng/MimicKit) by Xue Bin (Jason) Peng and contributors, Apache-2.0 license.
  This launcher only calls MimicKit's `run.py`; it contains no MimicKit code. **Unaffiliated with MimicKit.**
- [NVIDIA Warp](https://github.com/NVIDIA/warp), [Newton](https://github.com/newton-physics/newton),
  [MuJoCo Warp](https://github.com/google-deepmind/mujoco_warp).
- Built with an AI assistant (see the disclosure at the top).

## License

Copyright (c) 2026 curelessSky, licensed under GPL-3.0-or-later - see [LICENSE](LICENSE).
