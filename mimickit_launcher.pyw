# Double-click this file to start the launcher without a console window (Windows opens .pyw with pythonw.exe).
# Same as mimickit_launcher.py; the taskbar ID and icon are set before the window exists (mkl/icon.py).
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mimickit_launcher

mimickit_launcher.main()
