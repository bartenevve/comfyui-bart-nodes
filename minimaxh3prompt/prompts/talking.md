# TASK: PERSON SPEAKING (talking head, UGC, interview, vlog)

- Default framing: eye-level medium close-up, speaker in the center of the frame, facing the camera.
- Camera: phone/vlog → "The camera shakes slightly."; interview → static shot or small slow push in.
- First mention of the speaker: age, gender, clothes AND voice (pitch, timbre, pace), e.g. "with a bright, fast voice".
- The speaker talks only inside <d> blocks. Between lines fill time with small silent actions (nods, a glance, a hand gesture) so the model does not invent speech.
- Two speakers: S1 and S2, each with a position (left third / right third) and their own voice.
- Voiceover (speaker not talking on screen): "says in an off-screen voiceover:" and right after </d> write "while his lips remain completely closed." (her / their).
- Music: N/A unless the request asks for it (music hides speech).

# EXAMPLE

Input:
REQUEST: блогер в машине рассказывает про автопилот
DURATION: 8 seconds
ASPECT: 9:16 (vertical: main subject in the center, medium shot or closer)
SHOT PLAN:
- [Shot 1] 0–4 s, starts with "[Shot 1] " (no time)
- [Shot 2] 4–8 s, starts with "[Shot 2] At 00:04.000, the camera cuts to"
TRIGGER WORDS (each exactly once, unchanged, never in quotes):
- avr_host → right before the main character noun, first time it appears
DIALOGUE BLOCKS (copy exactly, put a speaker description before each):
- in Shot 1: (S1) says: <d>[Russian] Я не трогаю руль уже двадцать минут.</d>
- in Shot 2: (S1) says: <d>[Russian] И это не магия.</d>
ON-SCREEN TEXT: none — use no double quotes

Output:
integrated_multimodal_description: [Shot 1] Live-action, cinematic, soft daylight, an eye-level medium close-up frames a avr_host young man in a black hoodie in the center of the frame, facing the camera from the driver's seat, his hands resting on his knees while the steering wheel turns by itself. First he glances at the wheel, then he looks back into the camera. The camera shakes slightly. The young man with a bright, fast voice (S1) says: <d>[Russian] Я не трогаю руль уже двадцать минут.</d> [Shot 2] At 00:04.000, the camera cuts to a close-up of his face in the center of the frame, facing the camera. First he raises his eyebrows, then he shrugs with a grin. The camera holds a static shot. He (S1) says: <d>[Russian] И это не магия.</d> By the end of the shot he is smiling and pointing at the empty wheel.

overall_soundscape: Soft tire noise and a low electric hum fill the cabin. A turn signal clicks twice.

non_diegetic_music: N/A
