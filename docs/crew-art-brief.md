# JobPilot crew — character art brief

> **Current set (Nov 2026):** realistic 3D CGI renders generated with Nano Banana, using Pilot as the style
> reference for everyone, ten characters including **Verifier** (magnifying glass and a verified-shield hologram).
> The files are in `frontend/public/agents/` (`{agent}-idle|working.webp/.avif` and `crew-hero.webp`). They're shown
> only through `components/agents/agent-avatar.tsx`, and `frontend/config/agents.ts` holds names, roles, tints, face
> crops, depth maps and empty-state copy. The stylized brief below is the earlier direction.
>
> **Live 3D.** Characters shown at 56px or larger render in 3D (`lib/crew3d/engine.ts`, Three.js + GSAP): each pose
> is displaced by its depth map in `public/agents/depth/{agent}-{pose}.png` (Depth Anything V2, 512px, grey = near,
> blurred and percentile-normalised), relit with the crew's key light and cobalt rim, and animated by run status.
> Smaller avatars, reduced motion, Save-Data and browsers without WebGL use the still renders.
>
> **To replace or add a character:** keep the file names, framing (head-and-shoulders, head in the upper 60%), cobalt
> rim light and graphite background; make a depth map from the new render (same 1024px framing), resize it to 512px,
> blur slightly, normalise it between the 2nd and 99.5th percentiles, and save it as a grayscale PNG next to the
> others. Then tune the `face` crop in `config/agents.ts`.

The agents are a crew of **original** stylized 3D human characters, shown inside the app. Generate every image in
one consistent style, lighting and outfit system, then drop the files into `frontend/public/agents/`. The app picks them
up automatically (`npm run crew:manifest`, which also runs before `dev` and `build`). Until a file exists, the
built-in animated avatar stands in, so the art can arrive one agent at a time.

## Style (every image)

- Animated-film style 3D (think a feature-animation studio, not photoreal). Soft subsurface skin, clean stylized
  hair, slightly enlarged eyes, friendly proportions. Avoid the uncanny valley: no pores, no photographic skin.
- **Lighting:** a soft key light from camera-left, a gentle warm rim light from behind-right, and low-contrast fill.
  Use the same setup for every character.
- **Background:** transparent, or a flat graphite `#1B1D23`. No props or scenery behind the character.
- **Crew uniform:**
  - a graphite jacket or overshirt (`#2B2E36`) over an off-white inner layer (`#F2EFE8`);
  - ONE cobalt accent (`#4C7DFF`), as collar piping, a badge or a lanyard;
  - a small JobPilot crew pin on the left chest (a rounded diamond with a four-point star).
- **Prop:** each agent adds exactly ONE signature prop (below) and nothing else.
- **Cast:** diverse but cohesive, with an India-first, young-professional feel, ages 22–35. Vary gender, skin tone,
  hair and build across the crew; keep the same art style and uniform.
- These must be original characters. Never base one on a real person or an existing film or game character.

## Framing and files

| File | Framing | Size |
|---|---|---|
| `{agent}-idle.webp` | Head-and-shoulders (chest up), slight 3/4 turn toward screen-right (where the app's content sits) | 768×768, square |
| `{agent}-working.webp` | Same framing, camera and light as idle | 768×768 |
| `{agent}-full.webp` | Full body, standing, same 3/4 turn (landing page line-up only) | 900 px tall, transparent background |

Use a WebP quality of about 82. Keep the head in the upper 60% of the frame; the app crops to a squircle from the top.

**Expressions:**
- **idle:** relaxed, friendly half-smile, looking at the viewer.
- **working:** focused, looking slightly down or to the side at their prop or a small floating screen.

Status motion (float, glow sweep, amber "waiting" pulse, prop badge) is added in code on top of the art. Don't paint it in.

## The crew

| `agent` | Role | Signature prop | Character notes (adjust freely, keep the cast diverse) |
|---|---|---|---|
| `pilot` | **Lead.** A calm, confident career coach | Sleek headset with a boom mic | Late 20s–early 30s, warm and composed. Slightly larger and more detailed than the crew: finer hair and fabric detail, a subtle cobalt light on the headset |
| `researcher` | Finds companies hiring for your profile | Tablet showing a company map | Curious and thoughtful; maybe glasses |
| `scout` | Watches job boards for live openings | Compact binoculars | Alert and energetic; short hair |
| `matcher` | Scores the fit | A softly glowing fit-score ring, hovering above the palm | Analytical, precise |
| `interviewer` | Asks about skill gaps | Notebook with question cards | Kind, attentive listener |
| `tailor` | Tailors the resume | Tape measure over the shoulders and a stylus | Detail-obsessed, stylish |
| `outreach` | Drafts emails and referral requests | Folded paper plane | Friendly, outgoing |
| `dispatch` | Sends approved messages | Courier satchel | Brisk and reliable |
| `tracker` | Tracks applications and follow-ups | Clipboard with a small kanban board | Organized and steady |

The **"Your turn"** stage isn't a character. It shows the user's own photo or initials in the same squircle frame
with a cobalt ring, so the user reads as the final member of the crew. That frame is built in code.

## Prompt template (any image model)

> Original stylized 3D character, animated feature film style, not photorealistic. **{role description}**,
> {age} year-old {character notes}, India-first young professional. Wearing a graphite overshirt jacket over an
> off-white crew-neck, cobalt blue (#4C7DFF) collar piping, small rounded-diamond crew pin on the left chest.
> Holding {signature prop}. **{idle: relaxed friendly half-smile, looking at the viewer | working: focused,
> looking slightly down at the {prop}}.** Head-and-shoulders, chest up, slight three-quarter turn to the right.
> Soft key light from the left, warm rim light, clean flat graphite background. Consistent with the rest of the crew.

To keep the cast consistent: generate Pilot first, then use that image as the style reference (or a "character
sheet" seed) for every other agent. Keep camera, light and uniform identical, and change only the face, hair,
build and prop.

## Pilot idle loop (optional)

- `pilot-idle.webm` (VP9, with alpha or on the `#1B1D23` background) **and** `pilot-idle.mp4` (H.264), 4–6 seconds,
  seamless loop, muted, 720×720, under about 1.5 MB.
- Motion: one or two blinks, a small head movement and gentle breathing. No talking, no camera move.
- `pilot-idle.webp` is the poster. The app shows the still image on reduced-motion, data-saver and slow (2G/3G)
  connections, and while Pilot is working.

## Checklist before dropping files in

- [ ] Same light, uniform colours and framing across all agents (put them side by side).
- [ ] Faces read clearly at 40 px (the pipeline size) and at 120 px (the Pilot console).
- [ ] File names are exactly as above (lowercase agent key).
- [ ] Run `npm run crew:manifest` (or restart `npm run dev`).
