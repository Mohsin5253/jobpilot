"""Flow-style dictation engine for spoken interview answers.

Design (after Wispr Flow's published principles): treat transcription as a context problem, not just ASR; bias
the recogniser with the speaker's own words; never stream raw words to the screen; guard every model change for
precision; log per-stage latency and the Dictation Edit Rate from day one. Every model sits behind an interface so a
provider swap is one config change. Nothing here stores audio or transcript text: only timings and edit counts.
"""
