# TASK: PRODUCT SHOT / AD

- The product is the main subject. Keep its shape, color, material and logo the same in every shot.
- The first second already shows the product (no empty frame).
- One concrete product action per shot: "the lid opens to 90 degrees", "the bottle rotates a quarter turn", "a highlight slides along the edge", "liquid pours into the glass".
- Framing: medium shot or close-up for the hero view, extreme close-up for material and details.
- Camera: push in, arc around, truck, static — with small amplitude at slow speed.
- Background: clean studio (seamless white, warm beige, or dark with rim light), lots of empty space around the product.
- No people or hands unless REQUEST asks for them.
- ON-SCREEN TEXT appears only in the last shot, in one line, and holds steady until the end.
- Music: describe it (product ads usually have music).

# EXAMPLE

Input:
REQUEST: реклама: беспроводные наушники в кейсе, кейс открывается
DURATION: 10 seconds
ASPECT: 16:9
SHOT PLAN:
- [Shot 1] 0–5 s, starts with "[Shot 1] " (no time)
- [Shot 2] 5–10 s, starts with "[Shot 2] At 00:05.000, the camera cuts to"
TRIGGER WORDS (each exactly once, unchanged, never in quotes):
- avr_buds → right before the noun of that object, first time it appears
- studio_lora → in the first sentence of Shot 1, right after the style
DIALOGUE BLOCKS: none — nobody speaks
ON-SCREEN TEXT (put in double quotes, exactly): "Silence, redesigned"

Output:
integrated_multimodal_description: [Shot 1] Live-action, cinematic, studio_lora look, soft top light, an eye-level medium shot frames a closed white avr_buds earbuds case in the center of the frame on a seamless white background with wide empty space around it. First a thin highlight slides along its rounded edge, then the lid opens to 90 degrees and reveals two white earbuds inside. The camera arcs around the case with small amplitude at slow speed. By the end of the shot the lid is fully open. [Shot 2] At 00:05.000, the camera cuts to an extreme close-up of one earbud in the center of the frame as it lifts a few millimeters out of the case and rotates a quarter turn, showing its matte surface. The camera pushes in with small amplitude at slow speed toward the earbud. A clean line of text reading "Silence, redesigned" appears on the right third of the frame and holds steady. By the end of the shot the earbud hangs still above the case.

overall_soundscape: A soft magnetic click as the lid opens, then a light plastic tick when the earbud lifts. Quiet studio room tone underneath.

non_diegetic_music: Minimal electronic pulse at a medium tempo with a soft bass note that swells when the text appears.
