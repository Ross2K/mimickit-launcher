# Contributing

Thanks for helping! This project is small and was vibe coded, so fixes of any size are welcome.

- **Bugs:** open an issue with your OS, GPU, Python version, the command shown in the "Exact command" box (Console view), and the end of the console output.
- **Pull requests:** keep them focused. The app starts from `mimickit_launcher.py`; the code lives in `mkl/` (core helpers, window, process, charts,
  dashboard, settings, status + status_model, dialogs). User-facing status and error texts are in `mkl/status_model.py`. It only needs the Python standard library (tkinter) and matplotlib.
- **Test before sending:** run the automated GUI test against the fake MimicKit tree:
  - Linux: `xvfb-run -a python tests/gui_test.py` (or just `python tests/gui_test.py` on a desktop)
  - Windows: `python tests\gui_test.py`
  - Against a real MimicKit clone: `python tests/gui_test.py C:\path\to\MimicKit`
  It should end with `RESULT: N/N checks passed`.
- Please test on Windows if you can; most users are there.
- Be kind. See "License for contributions" below.

## License for contributions

This project is source-available under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
By submitting a contribution (pull request, patch, or code in an issue), you agree that:

1. Your contribution is licensed under the same PolyForm Noncommercial License 1.0.0 terms as the project.
2. You also grant Ross2K (formerly curelessSky) a perpetual, worldwide, non-exclusive, royalty-free, irrevocable
   license to use, modify, sublicense, and relicense your contribution under any terms, including commercial
   licenses.
3. The contribution is your own work (or you have the right to submit it), and you keep your copyright in it.
