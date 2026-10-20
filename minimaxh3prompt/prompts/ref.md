# TASK: REFERENCE TO VIDEO (images, videos, audio as references)

- The program already wrote what every label means (REFERENCES). Use the labels exactly: <Subject 1>, <Picture 2>, <Video 1>, <Audio 1>. Never invent new labels.
- At the first appearance of a <Subject N> in the description: label + its look from REFERENCES + position in frame ("<Subject 1>, the young woman with long dark hair and a blue cardigan, on the left third of the frame"). Later just "<Subject 1>" or "she".
- An environment subject is where the scene happens ("on the orange sofa of <Subject 2>, the small coffee shop ...").
- Do everything in MUST.
- A speaking subject: "<Subject 1> (S1), using the voice timbre referenced from <Audio 1>, says: <d>...</d>".
- summary: the given prefix + 1–2 sentences: who does what where, using the labels.

# EXAMPLE

Input:
REQUEST: девушка сидит в кафе, поднимает глаза от книги и говорит фразу
DURATION: 8 seconds
ASPECT: 16:9
REFERENCES (use these labels exactly, with angle brackets):
- <Subject 1> is the young woman with long dark hair and a blue cardigan in <Picture 1>.
- <Subject 2> is the environment in <Picture 2>: small coffee shop with a brick wall, an orange sofa and a neon sign.
- <Audio 1> is the voice-timbre reference for <Subject 1> (S1).
SUMMARY must start with: [reference generation + audio reference]
MUST:
- When the speaker talks, write "using the voice timbre referenced from <Audio 1>".
- Every <Subject 1>, <Subject 2> must appear in the description; at its first appearance repeat its look and give its position in frame.
SHOT PLAN:
- [Shot 1] 0–4 s, starts with "[Shot 1] " (no time)
- [Shot 2] 4–8 s, starts with "[Shot 2] At 00:04.000, the camera cuts to"
TRIGGER WORDS (each exactly once in detailed_description, unchanged, never in quotes):
- film_lora → in the style sentence ("The target video is in a live-action cinematic film_lora style with ...")
DIALOGUE BLOCKS (copy exactly):
- in Shot 2: <Subject 1> (S1) says: <d>[Russian] Ты опоздал.</d>
ON-SCREEN TEXT: none — use no double quotes

Output:
summary: [reference generation + audio reference] The target video shows <Subject 1> reading on the sofa of <Subject 2>, then looking up and saying one line in the voice referenced from <Audio 1>.

detailed_description: The target video is in a live-action cinematic film_lora style with warm tungsten light. [Shot 1] An eye-level medium shot frames <Subject 1>, the young woman with long dark hair and a blue cardigan, on the left third of the frame, sitting on the orange sofa of <Subject 2>, the small coffee shop with a brick wall and a glowing neon sign on the right third. First she turns a page of a paperback book, then she lifts her eyes toward the door. The camera pushes in with small amplitude at slow speed toward her face. [Shot 2] At 00:04.000, the camera cuts to a close-up of <Subject 1> in the center of the frame, facing the camera. First she closes the book on her knees, then she tilts her head. The camera holds a static shot. <Subject 1> (S1), using the voice timbre referenced from <Audio 1>, says: <d>[Russian] Ты опоздал.</d> By the end of the shot she raises one eyebrow with a small smile.

overall_soundscape: Quiet café room tone with the soft clink of cups in the background. A book page rustles once.

non_diegetic_music: N/A
