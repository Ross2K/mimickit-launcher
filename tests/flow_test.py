"""a0.8.5: flow() keeps each widget's pack padding, keeps hidden widgets hidden and adopts widgets packed later.
   xvfb-run -a python tests/flow_test.py"""

import result_exit  # noqa: F401
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from tkinter import ttk
from mkl.window import flow

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


def wait(ms=900):
    r.after(ms, r.quit)
    r.mainloop()
    r.update()


r = tk.Tk()
r.geometry("300x200")
f = ttk.Frame(r)
f.pack(fill="x")
a = ttk.Button(f, text="Alpha")
a.pack(side="left", padx=(12, 2), pady=4)
b = ttk.Button(f, text="Bravo")
b.pack(side="left", padx=7)
c = ttk.Button(f, text="Charlie long button")
c.pack(side="left")
late = ttk.Button(f, text="Late")  # packed after flow()
flow(f)
wait()
pa = a.pack_info()
check("padding kept (padx=(12,2), pady=4)", str(pa["padx"]) in ("12 2", "(12, 2)") or tuple(map(int, str(pa["padx"]).split())) == (12, 2), pa["padx"])
check("pady kept", int(str(pa["pady"]).split()[0]) == 4, pa["pady"])
check("bravo padx 7", int(str(b.pack_info()["padx"]).split()[0]) == 7, b.pack_info()["padx"])
check("wrapped onto rows (all inside rows)", all(str(w.pack_info()["in"]) != str(f) for w in (a, b, c)))
b.pack_forget()
wait()
check("hidden widget stays hidden", b.winfo_manager() == "")
late.pack(side="left", padx=9)
wait()
check("late widget adopted into a row with its padding",
      late.winfo_manager() == "pack" and str(late.pack_info()["in"]) != str(f) and int(str(late.pack_info()["padx"]).split()[0]) == 9,
      late.pack_info())
b.pack(side="left", padx=7)
wait()
check("shown again: back in a row", b.winfo_manager() == "pack" and str(b.pack_info()["in"]) != str(f))
ia, ib = a.winfo_rootx(), b.winfo_rootx()
check("shown-again widget keeps its old place (after Alpha)", ib > ia or b.winfo_rooty() > a.winfo_rooty())
print("RESULT: %d/%d" % (sum(ok), len(ok)))
