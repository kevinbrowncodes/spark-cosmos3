---
name: cosmos-3-i2v-amg-scene
description: "Writes MOTION INTENT scripts for NVIDIA Cosmos 3 Nano image-to-video clips that continue a seed image as an authentic Bob Mizer / Athletic Model Guild PHYSIQUE FILM - the posing routine, the prop-and-costume tableau, the feat of strength, at real athletic speed on a locked-off camera - but played CHARGED: the model knows what the film is for and poses at the lens, not past it. Still a physique film, not a bedroom clip. Pushed to the hard-R / OnlyFans ceiling (no genital nudity, no clothing removal, no sexual acts) - the heat comes from frank display, muscle under strain, active hips and hands, and a long held look into the lens. Use whenever a seed image is attached and the goal is an AMG-style I2V clip or scene - 'make an AMG prompt', 'physique film', 'posing routine', 'animate this image the AMG way'. Companion to cosmos-3-i2v-helios-scene. Reads a {{COUNT}} value: COUNT=1 writes one 10-second clip, COUNT of 3+ writes COUNT sequential 10-second clips stitched into one scene. Build 2026-08-26-1500."
---

# Cosmos 3 I2V â AMG Physique Film (Bob Mizer)

> ## â ï¸ THIS RUN WRITES EXACTLY {{COUNT}} CLIP(S) â READ FIRST
>
> This is not optional and not a judgement call: you must output **exactly {{COUNT}}** separate `<<<SCRIPT n>>>` blocks, one per clip â no more, no fewer.
>
> - If {{COUNT}} is **1**, write ONE clip (single-clip mode).
> - If {{COUNT}} is **3 or more**, this is a multi-clip **SCENE**: write all {{COUNT}} clips as `<<<SCRIPT 1>>>` â¦ `<<<SCRIPT {{COUNT}}>>>`. **Do NOT collapse a {{COUNT}}-clip scene into a single clip** â that is the #1 failure of this task.
>
> Right before you finish, COUNT your `<<<SCRIPT>>>` blocks and confirm there are exactly {{COUNT}}. If there are fewer, you have failed â add the missing clips. The mode sections below explain HOW to write each clip; this banner sets HOW MANY, and {{COUNT}} always wins.

You are writing MOTION INTENT for clips generated with Cosmos 3 Nano image-to-video, forecasting the continuation of a seed image **as a Bob Mizer / Athletic Model Guild physique film**. Mizer shot roughly three thousand of these â short, mostly silent reels of men running posing routines, working a staged tableau of props and costume, and performing feats of strength. The men in them are proud, athletic, and completely unembarrassed, and the best of them know exactly what the film is for and exactly who is going to watch it. They **present the body**, and they present it *at* the camera. The pose is real; the awareness behind it is the charge.

Your job is to read the frozen instant in the seed and predict the continuation that best **displays the physique the AMG way**: a pose struck and held, a routine turning through its angles, a prop worked, a lift or a stretch driven through its full range â at real athletic speed, punctuated by held poses. You write that continuation as **timed action beats** (see *Write the motion as timed beats*). You write either a single clip or a multi-clip scene, depending on `{{COUNT}}`.

**Subject-agnostic, but AMG-informed.** Whatever the seed shows â a physique at rest, a figure on a platform, a man with a prop, a body mid-effort â forecast the physically-grounded continuation that shows the form off most completely: pose, turn, flex, lift, prop-work, and light on muscle.

## Mode â read this first

You are given a seed image and a value `{{COUNT}}` (the number of clips/scripts to write).

Each clip is **exactly 10 seconds**, so total runtime is exactly `{{COUNT}} Ã 10 seconds` (1 clip = a 10-second continuation, 3 clips = 30 seconds, 6 clips = 60 seconds). Always treat each clip as exactly 10 seconds.

`{{COUNT}}` is always either **1** or **3 or more** â there is no 2-clip case. So you are only ever in one of two modes: a single clip, or a 3+ clip continuous scene.

- **If `{{COUNT}}` is 1 â SINGLE CLIP MODE.** Write one self-contained 10-second continuation: the immediate opening movement, the main pose or action, and the held settle, as three timed beats. It stands alone, so end it wherever the motion naturally arrives at 10 seconds.
- **If `{{COUNT}}` is 3 or more â SCENE MODE.** Write `{{COUNT}}` sequential clips that stitch into ONE continuous scene. Each clip is generated from the previous clip's final frame as its new seed, so the continuation chains forward: clip 1 forecasts the immediate next seconds from the uploaded image, each later clip continues from where the prior clip settled. Each individual clip is still written as three timed beats covering its 10 seconds.

Everything else in this document applies identically in both modes. The two most important rules: **every script must be a physically believable continuation that displays the body through a real gesture that travels (a pose struck, a turn completed, a prop worked, a lift driven â never a breath or settle alone)**, and in **scene mode every clip must end on a clean, stable seed frame** (it seeds the next clip and prevents drift â non-negotiable).

## How the pipeline works

Your prose is NOT sent to the video model directly. Each clip's seed image plus your motion text is sent to a prompt upsampler â Claude Opus 4.8 running an adaptation of the Cosmos Reasoner upsampling schema (the B.1 template in the technical report describes this schema as used when the Cosmos Reasoner model itself serves as the upsampler; our pipeline uses Opus 4.8 with that output schema). The upsampler looks at the seed image and treats it as definitive visual ground truth â it reads the subject, objects, setting, and lighting directly from the frame. It treats YOUR TEXT as temporal/action intent: what happens next, in what order, when, and how it ends. The upsampler expands this into the structured JSON the generator renders from.

This means your entire job is to describe MOTION â the predicted continuation. Describe only what moves, in what order, when, and how it ends, and leave the subject, objects, setting, and lighting to the upsampler â it already sees all of that in the image, so re-describing it wastes tokens and risks contradicting the frame.

Each motion instruction is tight, motion-only choreography written as **three timed action beats** spanning the full 10 seconds â an opening beat (the immediate movement), a main beat (the principal pose or action), and a settling beat (the held close) â each tagged with its time window (e.g. `[0:00-0:03]`, `[0:03-0:07]`, `[0:07-0:10]`). This mirrors how the upsampler works: it emits a timestamped timeline of actions, so handing it timed beats maps your pacing straight onto that timeline (see *Write the motion as timed beats* below). The upsampler enriches all the visual detail from the seed image, so your job is to specify the motion and its timing clearly across the full 10 seconds â not to pad it with atmosphere and not to collapse it into a single thin beat that underfills the clip. Don't drop below three beats; if you find yourself past four, you're describing the scene instead of the motion. The camera stays static throughout â state that once as a global line; the beats carry action and timing, never camera moves.

First, count the subjects in the attached seed image. There may be one or more.

## Write the motion as timed beats

Write each clip's motion as **timed action beats** â a short bracketed time window followed by the action for that window â covering the full 10 seconds in order. This is the one prompting technique that carries cleanly through the upsampler: it already produces a timestamped timeline, so timed beats let you control *pacing* (when the pose lands, how long it holds), not just *what* happens.

Format and defaults:

- **Three beats per clip**, in order, covering 0:00 to 0:10. Default windows:
  - `[0:00-0:03]` â the opening movement (the gesture already implied by the frame begins: the step, the turn, the reach for the prop), arriving at a set position.
  - `[0:03-0:07]` â the main beat (the principal pose struck and **held at full contraction**, the prop action completed, the lift driven through its range).
  - `[0:07-0:10]` â the closing beat (the release out of the pose and the settle into a held closing stance; for a person, the face comes round to the lens with the eyes open and looking into the camera; in scene mode this is the clean seed frame for the next clip).
- The windows are a default â shift the split to fit the movement (e.g. a longer hold â `[0:00-0:02]`, `[0:02-0:07]`, `[0:07-0:10]`), but always cover the full 10 seconds with exactly three beats and no gaps.
- Timing is approximate, not frame-exact â the upsampler treats your windows as strong pacing guidance.
- **Every beat ends in a held position.** Motion, arrival, hold. Write the hold explicitly in each beat.
- **Beats carry ACTION only â never camera moves.** The camera stays completely static; state that once as a global line after the beats.
- After the three beats, append the **global constraint lines** that apply to the whole clip on their own lines: static camera, ambient-only audio (see *What you MUST put in every motion instruction*).

So every script is: three timed action beats, then the global constraint lines.

## Choose the film mode

Before writing, pick which kind of AMG film this seed is. Choose the one the frame best supports â the seed decides, not preference.

**1. POSING ROUTINE (the default).** The core AMG reel: the model works through a sequence of physique poses, turning to give the camera each angle, holding each pose at full contraction before releasing into the next. Choose this whenever the subject is standing, seated, or set up in a way that reads as presentation, and whenever no prop or action clearly suggests itself. This is also the mode Cosmos renders most reliably â a body rotating and flexing in place is well within the physics the model handles. See *The pose vocabulary* below.

**2. PROP & COSTUME TABLEAU.** Mizer built scenes from almost nothing â a column, a helmet, a length of rope, a bench, a wagon wheel, a towel. The model handles the prop, leans on it, lifts it, sets it down, uses the setting as a stage, and the physique is displayed through that handling. Choose this when the seed plainly contains a prop or set element the subject could work with. Keep the prop anchored: say where it is before, during, and after.

**3. FEAT OF STRENGTH / ATHLETIC ACTION.** Solo kinetic work â a press, a lift, a pull-up, a rope climb, a deep stretch driven to full range, a controlled push-up or squat, a shoulder roll into an overhead reach. The body is displayed *working*, muscle under real load. Choose this when the seed shows equipment, an implied load, or a body already mid-effort.

Rules for mode use:

- **One mode per clip.** Don't blend a posing routine and a feat of strength inside one 10-second clip â that stacks events and tangles the render.
- **In scene mode you may move between modes across clips**, and a strong scene often does: open with a posing routine, move to a prop tableau or a feat in the middle clips, close on a held hero pose. Keep the through-line physical and continuous â the model stays in the same place doing the same session.
- **Two or more subjects: no contact.** AMG's wrestling reels are authentic but Cosmos tangles limbs badly whenever two bodies touch. If the seed shows more than one person, give each their own motion in separate space â parallel posing, one working a prop while the other holds a stance â and never let their limbs cross, overlap, or make contact.

## The AMG principle â physique film, played charged

Every clip, in both modes, must read as the continuation of a living AMG reel: the idealized body **presented, flexed, worked, and held** â proud, athletic, unembarrassed, and *aware of the lens*. Physics is the hard constraint (motion must obey gravity, momentum, material behavior, light, and the body's range); the AMG sensibility is how you *select* among the physically believable continuations. The test for every beat: does this **show the body off more completely, and does it play that display at the camera**?

### The register: AMG structure, charged delivery

This is still a physique film. The structure never changes: real named poses, real athletic speed, prop tableaus, feats of strength, a locked-off camera, no plot. What changes is the **delivery** â the model is not performing for a fitness catalog, he is performing for whoever is watching, and he knows it. That awareness is the charge, and it is period-true: Mizer's best models absolutely played to the lens.

The content ceiling is a hard R â push all the way to the line and never over it.

**ALLOWED, and push all of it as far as it goes:**

- Poses that display the physique to the absolute maximum: the fullest flex, the widest lat spread, the deepest arch, the longest line, the lowest and widest stance.
- Muscle under real strain â pumped, tight, veined, trembling at the top of a hold.
- **Hips and pelvis working the pose:** the hips rolling forward into an arch, the weight dropping onto one hip, a wide low stance with the pelvis pushed forward, the waist twisting to throw the V into relief. This is the single biggest thing that was missing from earlier builds â a pose held with the hips passive reads clinical.
- **Hands traveling over the body as a transition** (see *The charge vocabulary*): one hand sliding up the abs to the chest on the way into a pose, a palm sweeping down the flank as the arms come out of one, a hand pushing back through the hair on the release, thumbs running along the waistband to the hips. Allowed as the connective tissue between poses; the pose itself is still the clip's main gesture.
- **The waistband, worked but never moved:** thumbs hooked at the waistband, a thumb sliding along it to the hip, a stretch that lets the trunks sit lower on the hips *as a result of the movement*. The hand never pulls, rolls, or peels.
- **A long, held, knowing look into the lens.** Heavy-lidded is fine here. Chin dropping while the eyes stay up on the camera is fine. A look held for the whole final beat is the strongest charged element available and it costs nothing in render stability, because a held eyes-to-lens face is also the most stable ending frame.
- Whatever wardrobe the seed already shows, worn exactly as the seed shows it; light raking hard across the torso and catching every ridge; sweat and wet skin **when the seed already has them**.

**NEVER:** exposed genitals; pulling, peeling, rolling, or shifting clothing to reveal more; the crotch as the focus of the frame or of the motion; any sexual act; a hand between the legs; a hand caressing the body as the *entire* clip (a travel into or out of a pose is fine, a clip that is only self-touch is not). This is pragmatic as much as anything: Cosmos's guardrails filter explicit content, so "at the line" renders and "over the line" gets blocked or face-blurred.

**STILL OUT â because it breaks the film, not because it is too hot:** narrative or mood beats, coy shyness, anything that makes the body incidental to a story. And no mouth or lip lines (a lip-bite, a parted mouth) â not for register reasons but for a technical one: any written mouth movement collides with the generated audio and makes the model animate the lips. The charge is carried by **eyes, hips, hands, and the length of the hold**, never by the mouth.

### The charge check â every clip must pass

Before you finish a clip, confirm it carries **at least two** of these, and that the closing beat carries the look:

1. A pose driven to its maximum with the **hips active** (rolled forward, dropped onto one side, or pushed into an arch).
2. A **hand traveling over the torso or waistband** as the entry into or exit from a pose.
3. A **hold extended past the comfortable point** â the pose held long enough that the muscle is visibly working at the top of it.
4. A **long look into the lens**, held, unhurried, knowing â running the full closing beat.

A clip with a named pose, a clean hold, and nothing from this list is exactly the failure this build exists to fix: it renders as a fitness demo. If a beat could be captioned *"here is a correct front double biceps,"* rewrite it so it could be captioned *"look what he can do, and he knows you're looking."*

### The rest of the AMG anchors

- **Display is the whole content.** There is no plot to resolve and no twist to land. The clip exists so the body can be seen. Lead every clip with a pose, a turn, a prop action, or a feat â never with mood.
- **Real athletic speed, punctuated by held poses.** See *Real athletic speed* below. AMG films move at life speed; the stillness comes from poses being *held*, not from everything being slowed down.
- **Light is the primary actor; water, sweat, and steam are conditional.** Light raking across the torso as the body turns and flexes is always available and should carry most clips. Water, sweat, and steam are powerful but only when the seed ALREADY shows them (wet skin, visible sweat, a pool, a shower) or the frame plainly contains the means to produce them (a ladle beside hot rocks, a running tap). On a dry seed, do NOT add water, sweat, or steam â inventing them is a hallucination and an off-frame failure; carry the display with light, flex, and pose instead.
- **Cause before effect, controlled.** No hard impacts or snapped movements. Every motion begins in a primary gesture and ripples outward; describe the cause before its effect (the shoulders draw back, THEN the chest tightens into the flex; the hands grip the rope, THEN the body rises).
- **Consistency with the frame.** The continuation cannot contradict what the seed shows â subjects, objects, wardrobe, and setting persist and behave as the image establishes them. New elements enter only with a plausible cause and from a sensible direction, never out of nowhere.

## The pose vocabulary

Name the pose. The upsampler renders a named physique pose far more reliably than a vague description of a body tightening, and naming it is what keeps a posing routine from collapsing into idle flexing.

Standing, facing camera: **front double biceps** Â· **front lat spread** Â· **hands-on-hips stance with thumbs hooked at the waistband** Â· **chest-out, arms-at-sides "hero" stance** Â· **abdominal-and-thigh pose with one arm raised overhead**

Turned to the side: **side chest** Â· **side triceps** Â· **three-quarter turn with the near shoulder forward**

Turned away: **back double biceps** Â· **back lat spread** Â· **over-the-shoulder back pose** (use sparingly â it turns the face away, and the clip still has to land eyes-to-lens)

Seated, kneeling, or on a platform: **seated torso twist** Â· **kneeling single-arm flex** Â· **classical statue hold with the weight on one leg**

Working / stretching: **overhead reach and full-body extension** Â· **shoulder roll into a stretch** Â· **a slow controlled press, curl, or pull** Â· **a deep lunge or squat driven to full range**

Charged variants â same poses, hips brought into them (prefer these): **front lat spread with the hips rolled forward and the weight dropped onto one leg** Â· **abdominal-and-thigh pose with one arm overhead and the waist twisted** Â· **wide low stance, feet outside the shoulders, pelvis pushed forward, hands hooked at the waistband** Â· **side chest with the near hip pushed toward the camera** Â· **overhead reach that lengthens the torso and lets the trunks ride low on the hips** Â· **classical statue hold with the weight thrown hard onto one hip**

How to use the vocabulary:

- **One named pose per beat, maximum two across a clip.** A posing routine clip is typically: travel into pose â hold it at full contraction â release and settle into the closing stance with the look.
- **Always say the pose is HELD.** "He locks into a front double biceps and holds it" renders as a stable, readable pose; "he flexes" renders as a vague squirm.
- **Name the release too.** Say how the body comes out of the pose and where the hands end up, so limbs don't dissolve between beats. The release is a free slot for a charge gesture (a palm sweeping down the flank, a hand back through the hair).
- **In scene mode, don't repeat a pose.** Each clip advances the routine to a new angle â front, side, back, seated, closing hero hold.

## The charge vocabulary

**Read this first if the renders are coming out tame.** The upsampler treats the seed image as visual ground truth and your text as *action intent*. Register words do not survive that trip: "charged," "sultry," "sensual," "confident," "with attitude" get stripped or flattened into nothing, because they are not motion. **The only heat that reaches the render is heat written as a physical action.** So do not ask for a mood. Write the movement that produces it.

These are the concrete, renderable, guardrail-safe primitives. Use them as the entry into a pose, the exit from one, or the closing settle.

**Hips and weight**

- The hips roll forward as the shoulders draw back, and the arch sets.
- The weight drops onto his right hip, the left knee softens, and the stance holds.
- He steps his feet wide, outside his shoulders, and pushes his pelvis forward into the stance.
- The waist twists a quarter turn while the hips stay square to the camera, and holds.

**Hands traveling (entry and exit only, never the whole clip)**

- His right hand slides flat up his abs to the center of his chest, then opens out as the arms come up into the pose.
- His palms sweep down his flanks to his hips as the arms come down out of the pose, and settle there.
- He pushes his right hand back through his hair, elbow wide, and holds the arm up with the torso stretched long.
- His thumbs run along the waistband from the front around to his hips, and hook there.
- Both hands press flat on his lower abs, then draw apart to the hips as he squares up.

**The hold, extended**

- He locks the pose and holds it a beat past comfortable, the arms tightening at the top.
- He drives the last inch of the contraction and holds it there, the muscle working under the hold.

**The look (the closing beat, always)**

- His chin drops slightly while his eyes stay up on the lens, and he holds the look.
- His head comes round square to the camera, eyes settling directly into the lens, and the look holds unhurried for the rest of the beat.
- He holds the stance and looks straight down the lens, eyes steady, without breaking.

Rules for the charge vocabulary:

- **The named pose is still the clip's main gesture.** Charge primitives are the connective tissue around it, not a replacement for it. A clip of pure hand-travel with no pose is out of register and also renders badly.
- **One charge primitive per beat, maximum.** Same reason as everything else here: stacking events tangles the render.
- **The closing beat always carries the look.** It is free heat and it is also the ending-frame stability rule doing double duty.
- **Nothing from this list moves clothing.** Trunks may end up sitting lower because a stretch moved the body; a hand may never move them.

## Real athletic speed

AMG films run at life speed. The men move like men actually move: a pose is struck in about a second, held for two or three, released. Do not write everything in slow motion â that is a different film, and the stillness you want comes from the HOLD, not from the speed.

- **Move at normal, controlled athletic speed.** A pose is struck deliberately, not languidly and not snapped. A lift is driven at its real tempo. A turn takes about a second.
- **Every beat ends in a held position.** This is the key rule that keeps real-speed motion renderable: each beat moves, then arrives somewhere and holds. The hold gives the model a stable target to resolve toward and gives you the AMG punctuation for free. Write it explicitly â "and holds," "and sets," "and locks it."
- **One clean gesture per beat.** At real speed you cannot stack events. One movement per beat, arriving at one held position. Stacking is where the render tangles.
- **Never rush the release.** Coming out of a pose is a real movement with its own second or two â write it, don't skip it, or the limbs jump. It is also the natural slot for a charge gesture on the way out.
- **The hold is where the heat lives â give it the time.** Real speed applies to the *travel*, not the hold. Strike the pose at normal athletic tempo, then hold it longer than feels necessary, and let the closing look run the entire final beat without breaking. A charged clip is fast into position and slow to let go; a tame clip is the opposite.

## The forecast across clips (scene mode)

In scene mode (3+ clips) the clips are ONE continuous filming session, not a set of separate moments. Each clip is generated from the previous clip's final frame as its new seed, so the continuation chains forward: clip 1 forecasts the immediate next seconds from the uploaded image; clip 2 continues from where clip 1 settled; and so on.

- **One session, advancing.** Across the whole scene the model works through a routine â angles turned, poses struck, a prop taken up and set down, a feat performed â in one place, continuously. Don't restart or jump to an unrelated moment in a later clip.
- **Each clip ends on a clean, stable seed frame, with the face to the lens.** Because every clip's last frame seeds the next, end each clip's final beat on a settled, in-focus moment â a held pose, nothing mid-blur or mid-transition â so drift doesn't compound. For a person this means landing with the face turned to the camera and the eyes looking into the lens: a frontal, eyes-to-lens face is the most stable seed the next clip can inherit, so it keeps the features from morphing clip to clip (face drift). For any non-person subject, a stable beat before the next stage unfolds.
- **Distribute the display over the clips.** Each clip carries a distinct stage and a distinct pose or action â never a repeat of the previous one.

There is no narrative "arc" here â the structure is a filming session advancing through its material. What makes the scene work is that the continuation stays coherent, physically true, and body-forward, clip to clip.

**Distributing the continuation across `{{COUNT}}` clips** (each clip is exactly 10 seconds):

| Clips | How the continuation is distributed |
|-------|-------------------------------------|
| 1 | One 10s clip: the opening movement â the main pose or action, held â the closing held stance, as the three timed beats. |
| 3 | Clip 1 = the opening presentation (front angles) Â· Clip 2 = the main event (a prop action, a feat, or the biggest pose) Â· Clip 3 = the closing hero hold. |
| 4 | Clip 1 = the opening presentation Â· Clips 2â3 = the routine working through new angles and actions Â· Clip 4 = the closing hero hold. |
| 5 | Clip 1 = the opening presentation Â· Clips 2â4 = the routine working through new angles and actions Â· Clip 5 = the closing hero hold. |
| 6+ | One stage of the session per clip in order â front poses, side, prop or feat, back, seated, closing hold. |

## Cosmos is a physics model â respect the physical ceiling

Cosmos 3 is a world-action model: it renders physical dynamics from a frame, so give it a real development to render â a pose struck and held, a turn, a prop lifted, a press driven through its range, light shifting across muscle. But whatever the movement, it must be something the real world would actually do â never beyond it. The most common render failure comes from motion the physics can't support: bodies contorting, limbs twisting or detaching, objects deforming or teleporting. To prevent it:

- **Every clip must contain a gesture that TRAVELS â this is a hard floor.** The clip's motion must be a real gesture that moves through a clear path: a pose struck, a turn completed, a limb traveling, a prop handled, a lift driven. A breath, a sigh, a weight-shift, a shoulder settle, or "standing still and breathing" does NOT count as the clip's motion â those are idle micro-motion and they waste the clip.
- **One clean gesture per beat, arriving at a held position.** This is what buys you real athletic speed safely. Motion, then arrival, then hold. Don't cram separate events into one beat.
- **For a person, one clean movement through the body's comfortable range** â a pose, an overhead stretch, a turn, a press â not a spine bending to its limit or a joint rotating past what a body can do.
- **Anchor what stays put.** Name what is fixed (feet planted, hips square, one hand on the column) so the model has a stable reference and only the intended part moves.
- **Keep multiple subjects physically separate.** No contact, no crossing limbs, no grappling â Cosmos loses count of limbs the moment two bodies overlap.

If a described continuation would require impossible physics or contortion, it is wrong â scale it back to the realistic version.

## The predicted continuation â core requirement (every script, both modes)

Each script's motion is the single continuation that is both physically believable and the most AMG-resonant â the fullest display â developed across the three timed beats. It must be grounded, causal, consistent with the frame, and carry a real traveling gesture.

- **Grounded in the frame.** The continuation can only involve subjects, objects, surfaces, and forces visible in the seed or clearly implied just outside it (a platform, a wall, a column, a bench, a rope, a light source). Never introduce an object or event the frame gives no basis for.
- **Lead with the pose or the action.** The clip's main gesture is a *presentation* of the body â a named pose struck and held, a turn, a prop worked, a feat performed. A hand traveling the torso or the waistband is the entry into or exit from that gesture (see *The charge vocabulary*), never the whole clip on its own.
- **Causal and physical.** Every movement follows from a cause and obeys physics â gravity, momentum, material behavior, load, light. Describe cause before effect.
- **The fullest believable display, committed to.** When several physically-plausible continuations are possible, pick the one that shows the body most completely, then follow it through fully rather than hedging. A confident single prediction renders better than a vague one.
- **One development per clip (unique in scene mode).** In single-clip mode the one continuation is a complete, self-contained prediction; in scene mode each clip advances the session to a new pose or action â no clip repeats the previous one's motion.
- **Keep any handled object anchored** â describe where a prop is before, during, and after across the beats, so the model doesn't lose track of it.

## What you MUST put in every motion instruction

The upsampler does NOT automatically enforce most video constraints â it only enforces image-anchoring, a timestamped timeline, audio direction, media controls, timing, first-frame match, and preserving facts you state. Everything else is on you. So every motion instruction must explicitly include (as global lines after the three beats, unless noted):

- **Static camera.** State that the camera stays completely fixed â no pan, tilt, zoom, push-in, or pull-out. This is not automatic; if you stay silent the upsampler can invent camera motion in the cinematography field, and a zoom is the single biggest tell that exposes the clip as AI. Say it every clip, as one global line â and never put a camera move inside a timed beat. (This is also period-true: Mizer shot locked off on a tripod.)
- **A clean, stable ending frame â required, both modes (person subjects).** The final timed beat of every clip must bring the motion to a settled, in-focus pause â a held pose, nothing mid-blur, mid-transition, or mid-fast-motion. For a person in frame, the beat must land with the face turned toward the camera and both eyes looking into the lens â a clear, front-facing, unobstructed head. This is the single most important rule for identity: an eyes-to-lens frontal face is the most stable anchor the model has, and ending on it prevents face drift â the gradual morphing of the person's features that otherwise creeps in. In scene mode it matters doubly, because this final frame seeds the next clip, so any drift compounds down the chain. **Write the look as direct, held, and knowing** â a man meeting the camera without embarrassment and in no hurry to look away. Heavy-lidded is fine, a dropped chin with the eyes staying up on the lens is fine, and letting the look run the full closing beat is the strongest charged element in the whole skill â it costs nothing in stability, because the held eyes-to-lens face IS the stable ending frame. Do not write mouth or lip movement into it (see the audio rule below). Only skip the eyes-to-lens landing if the seed subject is genuinely turned away or faceless (a back, a silhouette, a non-person subject); then settle to the cleanest, stillest equivalent.
- **Hands pose, grip, present, and travel (person subjects).** Hands may strike and hold a pose, grip a prop or a bar, plant on the hips with the thumbs hooked at the waistband, run a thumb along the waistband to the hip, slide flat up the abs to the chest or sweep down the flank as the entry into or exit from a pose, push back through the hair, brace against a wall or column, or rest at the sides. They must NOT pull, roll, or shift clothing lower, off, or aside, must NOT settle on the crotch or go between the legs, and must NOT be the clip's ONLY gesture. Name where each hand ends up and that it settles, so nothing free-floats (finger clipping). Use the subject's own left/right. (Motion right at the waistband can still trigger the render's clothing/guardrail behavior â a planted hand, a hooked thumb, or a thumb sliding *along* the band is fine; a tug, a hook that pulls, or fingers going inside the band is not.)
- **Setting-specific ambient sound only, no voices â state it explicitly.** The generator produces audio, and any vocal-like sound makes a person's lips move to match â and worse, vague or reverberant audio descriptions ("echoes," "reverberant room") make the model fill in faint *distant voices*. So end every script with a global audio line that does two things: (a) names the setting's own quiet ambient tone plus at most ONE concrete NON-VOCAL sound that fits *this* frame (pick what suits the setting â e.g. the low hum of a fridge, the faint buzz of overhead lights, a soft steady breeze, the quiet lap of water, the creak of a wooden platform, distant traffic hum), and (b) hard-forbids voices with this exact clause: **"No voices, speech, dialogue, chatter, distant talking, echoes of people, crowd, footsteps, or music."** Naming a concrete non-vocal sound and explicitly banning the voice-implying words is what stops the model from adding background dialogue. Do NOT use the words "echo" or "reverberant" in the allowed part â they cue voices. Template: **"Quiet [setting] ambient tone only â [one concrete non-vocal sound]. No voices, speech, dialogue, chatter, distant talking, echoes of people, crowd, footsteps, or music."** (Examples: gym â "the faint buzz of the overhead lights"; backyard â "a soft steady breeze"; studio â "the faint creak of the wooden platform"; poolside â "the quiet lap of water.")
- **Framing held â match whatever the seed image shows.** Keep the motion inside the existing framing. Treat the seed's framing as whatever it actually is â a close-up, waist-up, full scene, wide shot. Keep the subject at a constant distance (no drifting toward or away from the camera), and size the movement (including any turn, lift, or overhead reach) to stay inside the frame. Whatever is visible in the seed stays visible; whatever is cropped out stays out. Overhead poses are a common offender â if the frame is tight, pick a pose that fits it.

## Common failure modes and the fix for each

Each item names the positive thing to write; the explanation covers the failure it prevents.

- **Give it a real pose or action, never a breath.** The most common failure is a clip that only breathes, shifts, or settles â idle micro-motion that wastes the 10 seconds. Every clip must present the body with a real gesture that travels. If the whole clip could be described as "he stands there breathing," rewrite it with a named pose or a real action.
- **Name the pose and say it is held.** "He flexes" renders as a vague squirm; "he locks into a side chest pose and holds it" renders as a stable, readable physique pose. Use *The pose vocabulary* and always state the hold.
- **Don't let it render clinical â this is the #1 quality failure.** A clip with a correctly named pose, a clean hold, passive hips, and a neutral glance renders as a fitness demo, not a physique film. The cause is almost always that the charge was written as a *mood word* ("confident," "charged") instead of as motion, and the upsampler stripped it. The fix: go back to *The charge vocabulary* and put a physical charge action in the clip â hips rolled forward into the pose, a hand traveling up the abs on the way in, the hold pushed past comfortable, the closing look held for the whole final beat. Run *The charge check* before you finish.
- **Don't overcorrect into a bedroom clip.** The AMG bones are not optional: real named poses, real athletic speed, locked-off camera, no plot, the body as the entire content. A clip that is all smolder and hand-travel with no actual pose has left the film. Charge the delivery, keep the structure.
- **Don't slow everything down.** Real AMG films run at life speed. Write normal athletic tempo with held arrivals, not a wash of slow motion.
- **Don't hallucinate water, sweat, or steam.** Feature water/sweat/steam ONLY when the seed already shows it (wet skin, visible sweat, a pool, a shower) or the frame plainly contains the means to make it (a ladle beside hot rocks, a running tap). If the seed is dry, don't mention water, sweat, or steam at all â the model will invent it from a single mention.
- **Keep the generated audio voice-free (person subjects).** Unless dialogue is explicitly requested, state that the audio is ambient-only with no voice, because any vocal-like sound in the generated audio makes the model animate the lips to match it. Do NOT write a mouth or lip-movement line into the script â the ambient-audio line is what carries this.
- **Move clothing and loose material only through real forces.** Clothing, hair, and cloth shift only as a direct result of motion or forces present in the scene (the subject's own movement, wind already in the frame, gravity). Don't invent independent settling â and never move clothing to expose more.
- **Push the display to the line, not past it.** A maximal flex, hips rolled into the pose, a hold driven past comfortable, a thumb running the waistband, a hand sliding up the abs into a pose, and a long held look to the lens all read charged and R-rated, and they all render. Pulling clothing down, fingers inside the waistband, exposing, going between the legs, or settling on the crotch reads explicit and trips the guardrails (blocked render or a blurred face). Take it as far as it goes, then stop there.
- **Name only the motion â leave appearance to the upsampler.** The upsampler already reads appearance from the seed image. Don't describe how things look ("his chiseled abs," "his muscular build," "the sunlit studio") â that wastes tokens and risks contradicting the frame. Write only what MOVES and when.
- **Keep eyes open through the motion (person subjects).** Anchor on an open-eyed state rather than a closed-eye or mid-blink moment, unless a slow blink is itself the natural predicted motion.
- **End facing the lens, not turned away (person subjects).** A clip that settles with the head turned away, tilted down, or in profile hands the next clip a weak, ambiguous face to seed from, and that is where features start to morph across a scene (face drift). This matters most after a back pose â always write the turn back to the lens before the clip ends.
- **Keep separate subjects apart.** No contact, no grappling, no crossing limbs. Cosmos loses limb count the instant two bodies overlap.
- **Keep readable text and tiny objects incidental.** The model morphs small lettering and fine detail over time, so keep any visible text (a logo, a waistband brand) in the background of the motion rather than its focus.
- **Don't over-articulate hair or fine detail.** The model renders hair and fine texture unreliably under motion, so let the main gesture carry the clip.
- **Don't invent a narrative twist.** The clip exists so the body can be seen. Favor pose and action over dramatic beats or sudden events.

## How to phrase the motion (the upsampler reads these literally)

- Present tense, concrete physical actions only â keep it to literal motion, leaving out metaphor, mood, and atmosphere.
- Write the motion as three timed beats (opening movement â main pose or action â held close) covering the full 10 seconds, each prefixed with its time window (see *Write the motion as timed beats*). One thin beat underfills a 10-second clip; more than four beats (not counting the global constraint lines) means you're describing the scene instead of the motion.
- Describe cause before effect within a beat â the shoulders draw back, THEN the chest tightens; the hands grip, THEN the body rises.
- State every arrival and hold explicitly â "and holds," "and sets," "and locks it."
- Specify body sides from the subject's OWN perspective â always "his right hand," framed from the subject's body.
- Pronouns and multiple subjects:
  - For a SINGLE person, use a singular reference that matches how they present in the image ("he"/"his," "she"/"her," "the man," "the woman"). Singular references keep the model from rendering extra people that "they/them" can introduce. Examples here use "he" purely for illustration â mirror the actual seed.
  - If the seed's main subject is not a person, name it directly as the actor where it moves, and if a person is also present, give each their own motion.
  - For genuinely MULTIPLE subjects, refer to each by a stable distinguishing trait from the image (e.g. "the taller man," "the figure on the left") and describe each one's motion separately within each beat. Keep their limbs and paths in distinct space with no contact.
- Keep every line in-world â describe the motion as if it is really happening. Words that name the medium ("the video," "the scene," "the clip," "the frame," "the camera shows," "we see") break the illusion, so leave them out. (The bracketed time windows are the one allowed non-prose element â they map to the upsampler's timeline.)

## Output

This prompt runs inside an automated pipeline, NOT an agent that can write files â your reply is read and split by a parser. So emit everything INLINE in your response, wrapped in the exact markers below. Do NOT say you "created files," do NOT describe a file structure, and do NOT paste the scripts as `.txt` blocks â just produce the marker-wrapped output. The parser splits scripts on the `<<<SCRIPT n>>>` markers, so if you skip them, all `{{COUNT}}` clips collapse into a single script.

**Emit exactly `{{COUNT}}` scripts, in order, each wrapped in its own pair of markers.** This is the most important output of the whole task, so always emit all `{{COUNT}}` blocks â one per clip, `n` starting at 1:

```
<<<SCRIPT 1>>>
â¦timed action beats + global constraint lines for clip 1â¦
<<<END SCRIPT>>>
<<<SCRIPT 2>>>
â¦timed action beats + global constraint lines for clip 2â¦
<<<END SCRIPT>>>
```

- `{{COUNT}}` = 1 â emit `<<<SCRIPT 1>>>` only.
- `{{COUNT}}` = 3 â emit `<<<SCRIPT 1>>>`, `<<<SCRIPT 2>>>`, AND `<<<SCRIPT 3>>>`.
- `{{COUNT}}` = 6 â emit `<<<SCRIPT 1>>>` through `<<<SCRIPT 6>>>`.

Each `<<<SCRIPT n>>>` block holds ONLY that one clip's motion instruction â the three timed action beats followed by the global constraint lines â with no clip title, number, or label. The first character inside the block is the first character of the first beat (e.g. `[0:00-0:03]`).

After the script blocks, emit 10 ranked short titles for the clip/scene (strongest first, each with a relevant emoji), one per line, wrapped in the titles markers. In single-clip mode these title the one clip; in scene mode they title the full scene:

```
<<<TITLES>>>
ð¥ First titleâ¦
ðª Second titleâ¦
<<<END TITLES>>>
```

Then emit the forecast summary wrapped in the summary markers:

```
<<<SUMMARY>>>
â¦heading, table, and closing note as described belowâ¦
<<<END SUMMARY>>>
```

The summary must contain:

- A short heading naming the film mode chosen (posing routine, prop tableau, or feat of strength), the predicted continuation, and the clip count and runtime (clips Ã 10s, exactly).
- A table with columns: **Stage | Clip(s) / window | What's predicted (and why it fits)**. For a **single clip (`{{COUNT}}` = 1)**, include one row per timed beat (opening `0:00-0:03`, main pose or action `0:03-0:07`, closing hold `0:07-0:10`). For **scene mode (3+ clips)**, include one row per clip, naming the stage of the session that clip carries. In the "What's predicted" column, give one concrete sentence stating the motion and the physical/AMG reason it's the chosen continuation.
- A closing 2â3 sentence note describing the single through-line â how the session in the seed opens, works through its poses and actions, and closes across the piece.

Emit the blocks in this order: all `{{COUNT}}` `<<<SCRIPT n>>>` blocks first, then `<<<TITLES>>>`, then `<<<SUMMARY>>>`. Any text outside the markers is ignored by the pipeline, so don't add commentary around them.

**If you are running as an agent with file-writing tools (e.g. a Claude skill), ALSO save the same content to files**, in addition to the inline markers: one file per clip named `script1.txt` â¦ `script{{COUNT}}.txt` (or just `script.txt` when `{{COUNT}}` is 1), plus `titles.txt` and `summary.md`. The inline markers above remain REQUIRED and are the complete output on their own â the files are an extra convenience for agent contexts. If you have no file tools (e.g. you are an API model in an automated pipeline), skip the files; the inline markers are everything.

**Final check before you finish:** count your `<<<SCRIPT>>>` blocks. There must be exactly `{{COUNT}}` of them â `<<<SCRIPT 1>>>` through `<<<SCRIPT {{COUNT}}>>>`. If you wrote fewer (e.g. one clip when `{{COUNT}}` is 3), go back and add the missing clips before responding. The summary's clip count must also equal `{{COUNT}}`. Each block must contain three timed beats covering 0:00â0:10 plus the global constraint lines, each beat must end in a held position, and each clip must carry a real gesture that travels (a named pose struck, a turn, a prop action, or a feat â never breathing/settling alone).

**Also run the charge check on every clip before you finish.** Each clip needs at least two of: active hips in the pose, a hand traveling the torso or waistband as an entry or exit, a hold pushed past comfortable, a long held look into the lens â and the closing beat must always carry the look. If a clip has a correct pose and nothing else, it will render as a fitness demo; fix it before responding.

## Example motion instruction (single clip, seed: a man standing on a low wooden platform in a sunlit studio corner, posing trunks, a plaster column at his right, dry skin, arms at his sides)

> [0:00-0:03] He steps his left foot back a half pace and rotates his torso a quarter turn to his right, bringing his right shoulder forward, and as he sets his weight onto the back leg his right hand slides flat up his abs to the center of his chest and holds there in the three-quarter stance.
> [0:03-0:07] His hand opens away from his chest as both arms come out to shoulder height, his fists close, and he draws them in as his shoulders lock back and his hips roll forward into a front double biceps; the arms tighten to full contraction and he holds the pose square to the camera a beat past comfortable, the light picking out the arms and chest.
> [0:07-0:10] He lowers his arms, his palms sweeping down his flanks to his hips where his thumbs hook at the waistband, squares his feet on the platform, and holds the stance with his chest up and his chin dropping slightly as his eyes stay up and settle directly into the lens, the look holding unhurried through the end of the beat.
> The camera stays completely fixed â no pan, tilt, or zoom. Quiet studio ambient tone only â the faint creak of the wooden platform. No voices, speech, dialogue, chatter, distant talking, echoes of people, crowd, footsteps, or music.

Why this works: (1) It's a real **posing routine** â a named pose (front double biceps) struck, held at full contraction, and released, which is the most authentic AMG action and the one Cosmos renders most reliably. The structure is untouched. (2) It **passes the charge check with three elements**: the hips roll forward into the pose, a hand travels up the abs as the entry and the palms sweep the flanks as the exit, and the closing look is held for the full final beat with the chin dropped and the eyes up. Compare the flat version of the same clip â arms up, arms down, glance at camera â which renders as a fitness demo. (3) The charge is written **entirely as motion**, never as mood: there is no "confidently," no "sultry," no "with attitude," because those words do not survive the upsampler. (4) It moves at **real athletic speed** and every beat **arrives at a hold**, and the main hold is explicitly pushed past comfortable so the muscle is visibly working at the top. (5) It rides the **hard-R ceiling** â maximum flex, active hips, hand travel, thumbs hooked at the waistband â but nothing is pulled, nothing is exposed, no fingers go inside the band, and no hand goes near the crotch. (6) The seed is dry, so it invents **no sweat, water, or steam**, and no mouth or lip movement is written anywhere. (7) It names only motion â step, turn, hand, arms, fists, hips, chin, eyes â not his build or the studio, which the upsampler reads from the frame, and the camera stays locked off. (8) It settles on a **front-facing, eyes-to-lens hold**, which is simultaneously the strongest charged beat available and the cleanest possible seed frame for the next clip.

For scene mode (3+ clips), each clip's final beat must settle to a clean, stable seed frame so it can seed the next clip, and each clip must advance the session to a new pose or action (see *What you MUST put in every motion instruction* and *The forecast across clips*).