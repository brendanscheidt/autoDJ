# Product Vision

## Goal

Build an AutoDJ system that can import local audio files, analyze them, and
generate a full DJ-style set with musically intentional transitions instead of
simple end-to-start crossfades.

The distinguishing behavior is not "play the next song smoothly." The target is
to create transitions a human electronic music DJ would recognize:

- Phrase-aligned blends.
- Build-to-drop switches.
- Drop doubles and drop swaps.
- Loop tightening to build tension.
- EQ-aware bass swaps.
- Acapella-over-instrumental moments when stems and vocal timing allow it.

## Initial Product

The first product should be a desktop app/workbench, not a mobile app.

Desktop-first is the right starting point because the hard problem is proving
that the generated mix sounds good. The early app needs debugging surfaces that
are awkward on mobile:

- Waveform, beat grid, section, and cue visualization.
- Metadata inspection for BPM, key, sections, energy, stems, and confidence.
- Rapid auditioning of transition templates.
- Local analysis jobs that can be CPU/GPU heavy.
- Clear logging and deterministic fixtures for bad transitions.

The desktop app should still be built with a mobile-aware core. The playback
engine, data contracts, and DJ strategy interfaces should avoid assumptions that
would block future iOS/Android reuse.

## MVP Scope

The MVP imports local WAV/MP3 files and assumes they are dubstep or adjacent bass
music. A stub genre analyzer returns `dubstep` for every imported file.

The MVP should provide:

- Local audio repository for WAV/MP3 files.
- Offline analysis pipeline with cached metadata.
- Stub genre analyzer.
- Dubstep DJ strategy that generates a set-level `MixPlan`.
- Playback engine that executes deck commands and automation keyframes.
- Desktop UI for loading tracks, analyzing them, generating a plan, and playing
  or auditioning transitions.

## Explicit Non-goals

Do not implement these in the MVP:

- Spotify playback, Spotify audio analysis, or Spotify content modification.
- SoundCloud/YouTube/Apple Music integration.
- General mixed-genre DJ intelligence.
- Mobile UI.
- Real-time stem separation.
- Cloud accounts, sync, social features, or sharing.
- Full DAW-style editing.
- Production-grade genre classification.

Streaming-service repository adapters can be explored later, but only if their
technical capabilities and platform policies allow the required behavior.

## Product Assumptions

- Users provide local audio files they are allowed to process.
- Analysis can happen before playback and can take time.
- The app may create derived assets such as waveform previews, metadata JSON,
  and stem files.
- The first DJ strategy optimizes for dubstep-style arrangement conventions:
  strong drops, 8/16/32-bar phrases, build sections, breakdowns, and dramatic
  energy changes.

## Success Criteria

The first credible milestone is not a large library of supported genres. It is a
short generated dubstep set that sounds intentional.

A successful MVP can:

- Analyze 10 to 30 local tracks.
- Generate a plausible 15 to 30 minute set.
- Produce at least three distinct transition types.
- Avoid obvious vocal clashes and phrase trainwrecks.
- Expose enough metadata to debug why a transition was chosen.
- Let a developer replay the same set deterministically from the same inputs.

