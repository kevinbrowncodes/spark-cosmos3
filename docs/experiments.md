# Experiment register

Blind comparisons run against the V2V pipeline. Each has a codename so it can be
referred to without ambiguity, and a decision rule **fixed before any render**, so
results can't be rationalised after the fact.

Method for all of them: matched source clips, matched seeds, balanced left/right
assignment, key withheld until every scenario is scored. Only the named variable
differs.

| # | codename | variable | n | result | p |
|---|---|---|---|---|---|
| 001 | **QUILL** | flat prose vs Gemma JSON | 12 | **structured 10-1** | 0.012 |
| 002 | **ANCHOR** | conditioning 2 s vs 3 s | 12 | 3 s 8-2 | 0.109 |
| 003 | **REACH** | conditioning 3 s vs 4 s | 7 | 3 s 5-1 | 0.219 |
| 004 | **HUSH** | audio coupling / lip movement | 15 | *pending* | — |

---

## EXP_001 — QUILL (prompt format)

**Question:** does a structured JSON prompt beat plain prose?

12 scenarios, 480p, 189 frames, 35 steps, 2 s conditioning.

**Structured won 10 of 11 decided (p = 0.012)** — past the 10-2 threshold agreed in
advance. No side bias (5 LEFT / 6 RIGHT). Structured swept vehicle, manipulation,
rigid-body and lighting; fluids split 1-1. Of 9 CLEAR calls, structured took 8.

**Caveat that matters:** the prose arm was flat single sentences. The winning
prompts were **temporally decomposed** (slows → thins → stops → drop clings →
falls → splashes), so the active ingredient is probably sequencing, not JSON
syntax. Beat-structured prose vs JSON remains **untested**.

## EXP_002 — ANCHOR (conditioning length, short)

**Question:** does 3 s of conditioning beat 2 s?

12 scenarios, 480p, 50 steps, both arms producing exactly 240 generated frames.

**3 s won 8 of 10 decided (p = 0.109)** — short of significance, but all four CLEAR
calls went to 3 s and there was no side bias. **Adopted on balance**: being wrong
costs 8% more render time, which didn't justify another 9 GPU-hours to resolve.

MARGINAL calls rose from 2/11 in QUILL to 6/10 here — conditioning length is a
**second-order** effect next to prompt format.

## EXP_003 — REACH (conditioning length, long)

**Question:** does 4 s beat 3 s? And does a longer window repair fluids?

7 scenarios (both fluid cases deliberately kept), 480p, 50 steps, Gemma JSON held
identical across arms.

**3 s won 5 of 6 decided (p = 0.219).** The pre-agreed rule required 6-1 to justify
a full round, so **conditioning length is settled at 3 s and the line of enquiry is
closed.** More is not monotonically better — ANCHOR gained going 2 s → 3 s, REACH
lost going 3 s → 4 s. Consistent with pretraining using `T_cond = 2` (five pixel
frames) and NVIDIA's own protocol topping out at 3 s.

**Fluids failed at every window tried** — 2 s, 3 s and 4 s, at both 35 and 50 steps.
Reviewer on the 4 s winner: *"the glass shows more liquid than it should as it
pours."* Liquid volume conservation is a model limitation, not a configuration
problem.

## EXP_004 — HUSH (audio coupling / lip movement)

**Question:** why do lips move when the prompt explicitly forbids it?

Observed in production: the subject's lips move despite every clip's prompt
carrying *"mouth remains closed and motionless"* or *"no lip movement"*. The
instruction survives upsampling intact, so it is being **disobeyed, not lost**.

Two hypotheses:

1. **Audio-video coupling.** Cosmos3-Nano is the post-trained *audio-visual*
   variant — audio tokens are generated in the same diffusion subsequence as
   video. Lip motion and speech are a learned correlation, and a medium shot of a
   person facing camera sits in the talking-head distribution.
2. **Negation.** "No lip movement" names the concept; text encoders handle
   negation poorly, the same reason audio negatives were stripped from the scripts.

Design — I2V from the still (no chaining), 480p, 241 frames, 5 seeds per arm:

| arm | sound | mouth instruction |
|---|---|---|
| 1 | on | present (baseline) |
| 2 | **off** | present |
| 3 | on | **absent** |

**Outcome is binary** — does the mouth move at all — so 5 per arm suffices:
Fisher's exact gives p = 0.004 on a clean split, 0.024 on 5/5 vs 1/5. Audio must
be **stripped from all outputs before review**, or the sound-off arm identifies
itself and the blinding is worthless.

---

## Observations not yet tested

- **Hair physics.** Reported from production footage: Cosmos struggles with hair.
  Fits the fluid failure class — many small deformable elements with coupled
  dynamics. None of the twelve synthetic scenarios probed it.
- **720p costs ~3.5x 480p.** 77 min per 10-second clip against 22 min, measured at
  50 steps. Whether it earns that before Topaz Starlight upscaling is unresolved.
- **Steps 35 vs 50 never isolated.** The one round that varied it showed *more*
  catastrophic failures at 50, on a small sample.
