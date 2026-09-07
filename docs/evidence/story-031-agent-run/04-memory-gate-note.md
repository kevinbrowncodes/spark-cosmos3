# Memory gate observation (2026-09-07, during the first agent run)

| moment | MemAvailable (host) |
|---|---|
| before the run (engine idle since its last restart, Gemma evicted) | 33–34 GiB |
| during clip 1 (241 frames, 832×480, I2V) | 29–31 GiB |
| after clip 1, engine idle | **25 GiB** |

The engine reported `peak_memory_mb: 39914` for clip 1 and its CUDA allocator keeps
that peak cached, so the box's idle state after any first render is ~25 GiB free.
The 30 GiB gate (inherited from the pipeline's guard, which existed because a
*resident* Gemma had pushed a render into swap) would block every agent run on
this machine after the first clip. The render itself cost ~4–5 GiB incremental.

Decision: `AGENT_MIN_FREE_GIB=22` in this box's `.env` (the code default stays 30).
22 admits today's steady state and still refuses when the box is tighter than it
was during the run that just succeeded. Gemma's transient 18 GB load for the
upsample fits under 22 with margin; below that the run pauses, as designed.
