# TASK: TEXT TO VIDEO

Build the whole scene from REQUEST. Add concrete details that fit it: clothes, colors, props, weather, light. One place per clip.

# EXAMPLE

Input:
REQUEST: девушка в кафе смотрит в окно на дождь, потом улыбается
DURATION: 8 seconds
ASPECT: 16:9
SHOT PLAN:
- [Shot 1] 0–4 s, starts with "[Shot 1] " (no time)
- [Shot 2] 4–8 s, starts with "[Shot 2] At 00:04.000, the camera cuts to"
TRIGGER WORDS (each exactly once, unchanged, never in quotes):
- kodak_portra → in the first sentence of Shot 1, right after the style
- ohwx_girl → right before the main character noun, first time it appears
DIALOGUE BLOCKS: none — nobody speaks
ON-SCREEN TEXT: none — use no double quotes

Output:
integrated_multimodal_description: [Shot 1] Live-action, cinematic, kodak_portra look, soft overcast light, an eye-level medium shot frames a ohwx_girl young woman in a grey sweater on the left third of the frame in profile facing right, beside a rain-streaked café window on the right third. First she watches raindrops slide down the glass, then she wraps both hands around a white cup. The camera pushes in with small amplitude at slow speed toward her face. By the end of the shot her face fills the left half of the frame. [Shot 2] At 00:04.000, the camera cuts to a close-up of her face in the center of the frame, facing the window. First she lowers the cup, then a small smile slowly appears. The camera holds a static shot. By the end of the shot she is still smiling, her eyes on the rain.

overall_soundscape: Steady rain taps against the window under quiet café ambience. A cup clinks softly on a saucer.

non_diegetic_music: Sparse piano notes at a slow tempo that gradually fade out.
