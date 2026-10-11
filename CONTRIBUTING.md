# Contributing

Thanks for helping! This project is small and was vibe coded, so fixes of any size are welcome.

- **Bugs:** open an issue with your OS, GPU, Python version, the command shown in the "Exact command" box, and the end of the program output.
- **Pull requests:** keep them focused. The app is one file (`mimickit_launcher.py`) on purpose; it only needs the Python standard library (tkinter) and matplotlib.
- **Test before sending:** run the automated GUI test against the fake MimicKit tree:
  - Linux: `xvfb-run -a python tests/gui_test.py` (or just `python tests/gui_test.py` on a desktop)
  - Windows: `python tests\gui_test.py`
  - Against a real MimicKit clone: `python tests/gui_test.py C:\path\to\MimicKit`
  It should end with `RESULT: N/N checks passed`.
- Please test on Windows if you can; most users are there.
- Be kind. By contributing you agree your code is released under the GPL-3.0-or-later license.
