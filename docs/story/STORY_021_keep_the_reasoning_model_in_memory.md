# STORY_021 — Keep the reasoning model in memory alongside the video engine

**Epic:** none (operational / deployment)
**Related:** EPIC_001, STORY_015 (selectable reasoner), CLAUDE.md §7 (memory operations)

As an operator, I want the local reasoning model to stay loaded in memory at the
same time as the video engine, so that Hermes can call it to monitor and judge
generation results without waiting for a model load or risking an out-of-memory
kill of an in-flight render.

## Acceptance Criteria

- [ ] `gemma4:26b` stays resident indefinitely rather than unloading after an idle period
- [ ] Ollama reserves a context sized to the actual workload, not the model's full 262,144-token window
- [ ] Only one Ollama model is resident at a time, so a stray request cannot double the footprint
- [ ] Ollama is reachable from inside a container (it currently binds loopback only)
- [ ] **Measured**: steady-state footprint with both the engine and the reasoner loaded, recorded in `docs/spark-notes.md`
- [ ] **Measured**: peak memory during a **480p** render with the reasoner resident, with ≥15 GiB still available
- [ ] **Measured**: peak memory during a **720p** render with the reasoner resident, with ≥15 GiB still available
- [ ] A reasoner call issued *during* an active render completes without the render failing
- [ ] Swap usage does not grow during the above (growth means we are over budget, whatever `available` says)
- [ ] If 720p co-residency does not fit, the fallback is documented and ticketed rather than left to chance

## Technical Notes

**The weights were never the problem.** Gemma 4 26B at Q4_K_M is ~17 GiB, which
fits comfortably in a 121 GiB box already holding Cosmos. The pressure comes from
the **KV cache**: Ollama loaded the model at `n_ctx = 262144` (confirmed in
`journalctl -u ollama`), the full trained context, because `OLLAMA_CONTEXT_LENGTH`
is unset and Ollama 0.30 defaults to the model's trained window. KV cache scales
linearly with context length, and the real workload — the V2V upsampler prompt
with five conditioning stills — measured **5,756 tokens**.

Proposed service configuration:

```
OLLAMA_HOST=0.0.0.0:11434     # currently 127.0.0.1 only; containers cannot reach it
OLLAMA_CONTEXT_LENGTH=16384   # ~3x headroom over the measured 5,756-token workload
OLLAMA_KEEP_ALIVE=-1          # stay resident; this is the point of the story
OLLAMA_MAX_LOADED_MODELS=1    # a second model would blow the budget silently
```

`OLLAMA_HOST` matters because the gateway (and Hermes, if containerised) cannot
reach a loopback-bound service. Pair it with
`extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml`.

**Measure with `free -h`, nothing else.** CUDA allocations on GB10 do not appear
in process RSS or cgroup accounting — measured during this work, total process
RSS was ~9 GiB while `free` reported 62 GiB used, because Cosmos's weights live
in unified memory invisible to `ps` and `docker stats`. This is CLAUDE.md §7 and
it is the single easiest way to draw a wrong conclusion here.

**Budget as measured on 2026-07-27:**

| | GiB |
|---|---|
| Total unified memory | 121 |
| Cosmos + system, idle, reasoner unloaded | 62 |
| Available, reasoner unloaded | 59 |
| Cosmos peak during a 480p render (`peak_memory_mb` 49676) | 48.5 |
| Gemma 4 26B Q4_K_M weights | ~17 |

**720p is the case that decides this.** A 1280x720 render is 2.3x the pixel
volume of 832x480, so Cosmos's peak will rise well above the measured 48.5 GiB.
Co-residency that looks comfortable at 480p may not survive 720p. Do not sign
this story off on 480p evidence alone.

**Swap is already in use — 4.3 GiB of 15 GiB.** That is evidence the box has been
under real pressure, and it means `available` alone is not a sufficient health
signal. Watch swap growth as the primary warning sign.

**Fallback if 720p does not fit.** vLLM-Omni exposes `/v1/omni/sleep` and
`/v1/omni/wakeup` to release and restore GPU memory between jobs, but they
require `--enable-sleep-mode` at engine startup, which this deployment does not
currently pass (docs/api.md). Adding it would let Cosmos release memory while
idle, at the cost of a wake-up delay per job. That is a larger change affecting
the engine container and should become its own story rather than being smuggled
in here.

## Testing Plan

**Unit** — *not applicable.* This story changes service configuration and a
Docker network path; there is no gateway logic to unit test. Adding a test that
asserts environment variables would test the test, not the behaviour.

**Contract** (required):
- `curl http://host.docker.internal:11434/v1/models` **from inside the gateway
  container** returns 200 — proves the loopback fix works where it matters
- `ollama ps` shows `gemma4:26b` resident with a context of 16384, and still
  resident after 30 minutes idle (proves `KEEP_ALIVE=-1`)
- a chat completion with five images still succeeds at the reduced context and
  returns valid JSON — proves 16384 is genuinely enough for the real prompt

**Smoke** (required — this is a memory story, and memory is only observable under
load):
1. Record `free -h` and swap with the reasoner resident and the engine idle.
2. Run a **480p** V2V render (~8.5 min) with the reasoner resident. Sample
   `free -h` every 30 s. Record the minimum `available` and any swap growth.
3. Issue a reasoner call **during** that render. Both must complete.
4. Repeat with a **720p** render (~30 min).
5. Record all figures in `docs/spark-notes.md`.

Pre-flight per CLAUDE.md §7: confirm no generation is running before changing the
Ollama service, since restarting it while Hermes or the gateway is mid-call
would surface as an upsampler failure rather than an obvious outage.

## Estimated Complexity

**Medium.** The configuration itself is four environment variables and one
compose entry. The work is in the measurement — two renders at different
resolutions with sampling, and an honest decision if 720p does not fit.
