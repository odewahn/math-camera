# Math Camera Handoff

## Current state

The capture-pipeline stabilization work is complete. The existing command-line
workflow remains available through both entry points:

```bash
uv run math-camera
uv run python main.py
```

The application still supports:

- Control + Option + M: low-quality capture
- Control + Option + Shift + M: high-quality capture
- Control + Option + `.` / `,`: rotate clockwise/counterclockwise
- Control + Option + N / P: switch cameras globally while the terminal has focus
- N / P: switch cameras when the preview window has focus

## What changed

- `src/math_camera/state.py` contains thread-safe shared settings, status, and
  raw-frame storage.
- `src/math_camera/processing.py` contains hardware-independent rotation,
  resizing, ROI validation/cropping, and JPEG encoding.
- `src/math_camera/capture.py` contains the serialized capture worker and the
  macOS clipboard adapter.
- `src/math_camera/cameras.py` contains stable camera identity and navigation
  helpers.
- `native_camera.py` selects devices by AVFoundation unique ID when available,
  normalizes delivered frames to the configured canonical size, and joins
  lifecycle threads during shutdown.
- The preview and capture paths now transform independent copies of the raw
  frame; the raw frame is not overwritten by preview rotation or scaling.
- `.DS_Store` is ignored.
- Development dependencies, CI, a `Makefile`, tests, and a regenerated
  `uv.lock` were added.

## Verification completed

All of the following passed locally:

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
python -m compileall -q src main.py
uv build
```

There are currently 10 hardware-independent tests covering image processing,
ROI validation, camera fallback/navigation, frame isolation, capture status,
worker shutdown, and JPEG capture.

## Remaining manual verification

On a real Mac, verify camera permission, Accessibility permission, camera
enumeration and switching, low/high-quality clipboard pasting, sleep/wake
recovery, sound failure handling, no-camera startup, and clean shutdown via Q,
Escape, Ctrl-C, and window close.

## Next phase

The next planned phase is Dear PyGui modernization. The GUI should consume
`SharedState`, `FrameStore`, `CaptureStatusInfo`, and the capture worker rather
than reintroducing module-level capture state. Submission mode should follow
the GUI work and preserve the current hotkey and lifecycle acceptance criteria.

Relevant planning documents in the repository:

- `prerequisite-work-plan.md`
- `math-camera-feature-1-dearpygui-modernization.md`
- `math-camera-feature-2-submission-capture-mode.md`
