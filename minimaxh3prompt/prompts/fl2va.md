# TASK: GO FROM A START PICTURE TO AN END PICTURE

- START = Picture 1 (first frame), END = Picture 2 (last frame). If only END = <Picture 1> is given, invent a plausible earlier start and land on <Picture 1>.
- Usually ONE shot. Do not describe two static pictures: describe the PATH between them.
- Order: start state "begins in the position and framing established by Picture 1" → 2–3 visible intermediate changes → "settles into the pose, position and composition established by Picture 2" by the end of the shot.
- Use the same names as in the input: Picture 1 / Picture 2, or <Picture 1> when only END is given.
- Camera: small and slow (static, push in, pull out, small arc). Big moves break the match with the last frame.

# EXAMPLE

Input:
REQUEST: бутон раскрывается в цветок
DURATION: 8 seconds
ASPECT: 16:9
START = Picture 1: closed red tulip bud on black background
END = Picture 2: fully open red tulip, petals wide
SHOT PLAN:
- [Shot 1] 0–8 s, starts with "[Shot 1] " (no time)
TRIGGER WORDS (each exactly once, unchanged, never in quotes):
- macro_lora → in the first sentence of Shot 1, right after the style
DIALOGUE BLOCKS: none — nobody speaks
ON-SCREEN TEXT: none — use no double quotes

Output:
integrated_multimodal_description: [Shot 1] Live-action, cinematic, macro_lora look, soft studio light, an eye-level close-up frames a closed red tulip bud in the center of the frame against a black background, beginning in the position and framing established by Picture 1. First the outer petals loosen and separate at the tips, then they curve outward one by one while the inner petals rise and open, revealing the dark center. The camera pulls out with small amplitude at slow speed from the flower. By the end of the shot the tulip is fully open with wide petals and settles into the pose, position and composition established by Picture 2.

overall_soundscape: Quiet studio room tone with faint soft rustles as the petals unfold.

non_diegetic_music: Slow sustained strings with a single harp arpeggio that rises in volume as the flower opens.
