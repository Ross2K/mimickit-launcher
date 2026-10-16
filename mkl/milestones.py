# MimicKit Launcher - "First steps!" / "Walking well" milestones (a0.9.0)
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""Milestone alerts from the metrics MimicKit already logs (log.txt / console), no extra logging needed.

Log keys used (mimickit/learning/base_agent.py writes them every output iteration, after a test pass):
  Test_Return          - mean return of the test episodes
  Test_Episode_Length  - mean length of the test episodes, in control steps (log.txt always; the console only with
                         the launcher's logging patch - the launcher reads log.txt when the console lacks it)
Max episode length = episode_length (s, env_config.yaml) x control_freq (Hz, engine_config.yaml); MimicKit copies
both yaml files into the run's output folder.

A level fires when, for N consecutive evaluations (default 3), BOTH hold:
  upright: Test_Episode_Length >= upright% (default 80) of the max length  (the agent stays up, no early termination)
  match:   per-step test score = 100 x Test_Return / Test_Episode_Length >= the level's threshold
Fallbacks: no Test_Episode_Length in the log -> match score alone, as 100 x Test_Return / max length (a lower bound
of the per-step score: it equals it when episodes run to the end); no max length known -> match score alone (the
upright check is skipped). No usable data -> nothing fires.

Defaults - why: DeepMimic-style rewards are 0..1 per step (an exp() of pose / velocity / end-effector / root
errors), so the per-step score is "how closely the clip is matched, in %". A policy that falls or flails scores
well under 15 % (and its episodes end early, which the upright check catches). The undead run, which has started
to hold itself up and move with the clip, is at ~21.8 %. 20 % is therefore "first steps": upright AND clearly
following the motion. Well-tracked DeepMimic clips reach 60-80 %; 50 % is a recognisable, steady walk that is
still improving: "walking well".
"""

import math, os, time

STATE_FILE = "milestones.json"  # per output folder: which levels already fired (resume never re-fires)
LEVELS = (
    ("first_steps", "First steps!", "first_pct"),
    ("walking_well", "Walking well", "well_pct"),
)
DEFAULTS = dict(first_pct=20.0, well_pct=50.0, upright_pct=80.0, evals=3, enabled=True)
TEXT = dict(
    first_steps="It stays upright and follows the clip: per-step match {score:.1f}% for {n} checks in a row"
                " (episodes {len_pct:.0f}% of full length).",
    walking_well="Steady and close to the clip: per-step match {score:.1f}% for {n} checks in a row"
                 " (episodes {len_pct:.0f}% of full length).",
)
TEXT_NOLEN = "Per-step match {score:.1f}% for {n} checks in a row (episode length not logged/known - match score only)."


def cfg(s):
    """Thresholds from the launcher settings (self.s['milestones']) with defaults filled in."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in ((s or {}).get("milestones") or {}).items() if k in DEFAULTS})
    return c


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def max_len(run_dir):
    """Max episode length in control steps from the run's copied yaml files, or None."""
    from mimickit_trainsettings import get

    try:
        env = open(os.path.join(run_dir, "env_config.yaml"), encoding="utf-8", errors="replace").read()
        eng = open(os.path.join(run_dir, "engine_config.yaml"), encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    el, cf = _num(get(env, ("episode_length",))), _num(get(eng, ("control_freq",)))
    return el * cf if el and cf and el > 0 and cf > 0 else None


def evals(h, mlen):
    """[(score %, length % or None)] per evaluation row with a usable score. Uses Test_Return and, if logged,
    Test_Episode_Length (see the module doc for the fallbacks)."""
    R = h.get("Test_Return") or []
    L = h.get("Test_Episode_Length") or []
    has_len = any(_num(v) for v in L)
    out = []
    for i, r in enumerate(R):
        r = _num(r)
        if r is None:
            continue
        ln = _num(L[i]) if has_len and i < len(L) else None
        if has_len:
            if not ln or ln <= 0:
                continue
            out.append((100.0 * r / ln, 100.0 * ln / mlen if mlen else None))
        elif mlen:
            out.append((100.0 * r / mlen, None))
    return out


def reached(h, mlen, c):
    """{level: info} for every level whose condition holds for the last c['evals'] evaluations."""
    n = max(1, int(c.get("evals") or 3))
    rows = evals(h, mlen)
    if len(rows) < n:
        return {}
    last = rows[-n:]
    up = c["upright_pct"]
    upright = all(lp is None or lp >= up for _, lp in last)
    if not upright:
        return {}
    score = min(s for s, _ in last)
    lens = [lp for _, lp in last if lp is not None]
    out = {}
    for key, title, ck in LEVELS:
        if score >= float(c[ck]):
            lp = min(lens) if lens else None
            text = (TEXT[key].format(score=score, n=n, len_pct=lp) if lp is not None
                    else TEXT_NOLEN.format(score=score, n=n))
            out[key] = dict(key=key, title=title, score=round(score, 1), len_pct=None if lp is None else round(lp),
                            text=text)
    return out


def load(d):
    import mimickit_util as U

    st = U.load_json_or(os.path.join(d, STATE_FILE), {}, "milestones")
    return st if isinstance(st, dict) else {}


def fired(chain):
    """Levels already fired in any folder of the run chain (original + its resumes / continues)."""
    out = {}
    for d in chain:
        out.update(load(d))
    return out


def mark(d, key, info):
    import mimickit_util as U

    st = load(d)
    st[key] = dict(info, at=time.time())
    U.save_json(os.path.join(d, STATE_FILE), st, backup=False)


def check(d, chain, h, c):
    """New levels for run folder d (marked as fired in d). Returns [info] in level order."""
    if not c.get("enabled", True):
        return []
    done = fired(chain)
    new = []
    mlen = next((m for m in (max_len(x) for x in [d] + list(reversed(chain))) if m), None)
    for key, info in reached(h, mlen, c).items():
        if key in done:
            continue
        mark(d, key, info)
        new.append(info)
    order = [k for k, _, _ in LEVELS]
    return sorted(new, key=lambda i: order.index(i["key"]))
