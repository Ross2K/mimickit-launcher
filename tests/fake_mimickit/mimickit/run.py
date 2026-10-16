"""Stub of MimicKit's run.py for testing the launcher: prints like MimicKit and writes a log.txt + model.pt."""

import os, subprocess, sys, time

args = sys.argv[1:]


def get(k, d=""):
    return args[args.index("--" + k) + 1] if "--" + k in args else d


print("stub run.py args:", " ".join(args), flush=True)
if get("mode", "train") == "test":
    print("test mode: would open a viewer window", flush=True)
    time.sleep(float(os.environ.get("STUB_TEST_SECS", "2")))
    sys.exit(0)
out = get("out_dir", "output/")
os.makedirs(out, exist_ok=True)
if os.environ.get(
    "STUB_REPLAY"
):  # replay a real console capture; optionally drop in a real (lagging) log.txt
    if os.environ.get("STUB_LOG"):
        import shutil

        shutil.copy(os.environ["STUB_LOG"], os.path.join(out, "log.txt"))
    crlf, noflush = os.environ.get("STUB_CRLF"), os.environ.get(
        "STUB_NOFLUSH"
    )  # Windows-like output
    for line in open(os.environ["STUB_REPLAY"], errors="replace"):
        if crlf:
            sys.stdout.buffer.write(
                line.rstrip("\n").encode() + b"\r\n"
            )  # raw CRLF bytes, never flushed
        else:
            print(line, end="", flush=not noflush)
        time.sleep(float(os.environ.get("STUB_SLEEP", "0.001")))
    time.sleep(600)
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(600)"]
)  # like a worker process
n = int(get("num_envs", "1024"))
cols = ["Iteration", "Wall_Time", "Samples", "Test_Return", "Train_Return"]
# STUB_AMP=1: an AMP task run (e.g. steering): extra discriminator / exploration rows in between, an env info key,
# returns in 0..episode length (task reward per step <= 1), one 'nan' now and then
AMP = bool(os.environ.get("STUB_AMP"))
if AMP:
    cols = ["Iteration", "Wall_Time", "Samples", "Test_Return", "Train_Return", "Disc_Loss", "Disc_Agent_Acc",
            "Disc_Demo_Acc", "Disc_Reward_Mean", "Exp_Prob"]
# STUB_LOG_EPLEN=1: like stock MimicKit, episode length goes to log.txt only (not the console table)
fcols = cols + (["Train_Episode_Length"] if os.environ.get("STUB_LOG_EPLEN") else []) + (["Tar_Speed"] if AMP else [])
ftpl = "{:<25}" * len(fcols)
with open(os.path.join(out, "log.txt"), "w") as f:
    f.write(ftpl.format(*fcols) + "\r")
    for it in range(int(os.environ.get("STUB_ITERS", "400"))):
        samples = (it + 1) * n * 32
        wall = samples / 7.5e6
        vals = [it, round(wall, 5), samples, round(3 + it * 0.01, 3), round(3.5 + it * 0.012, 3)]
        extra = [100 + it]
        if AMP:
            ret_t, ret_tr = round(60 + it * 0.2, 3), ("nan" if it % 37 == 5 else round(55 + it * 0.25, 3))
            vals = [it, round(wall, 5), samples, ret_t, ret_tr, round(0.7 - it * 1e-4, 4), 0.62, 0.58, 0.31, 0.2]
            extra = ([250 + it % 50] if os.environ.get("STUB_LOG_EPLEN") else []) + [1.8]
        f.write(ftpl.format(*map(str, (vals + extra)[: len(fcols)])) + "\r")
        f.flush()
        print(
            "-" * 42
            + "\n"
            + "".join("|%21s |%16s |\n" % (c, v) for c, v in zip(cols, vals))
            + "-" * 42,
            flush=True,
        )
        if it % 50 == 0:
            open(os.path.join(out, "model.pt"), "wb").write(b"stub")
        time.sleep(float(os.environ.get("STUB_SLEEP", "0.02")))
child.kill()
