# Prerequisite Work Plan

This plan covers the work that should be completed before implementing the Dear PyGui interface or submission capture mode.

The goal is to stabilize the existing camera-to-clipboard workflow and establish clear interfaces that both future features can build on.

## 1. Establish a clean baseline

- Remove `.DS_Store` from the repository and add it to `.gitignore`.
- Decide whether the feature briefs belong in version control.
- Confirm the supported Python and macOS versions.
- Verify that `uv sync`, `uv run math-camera --version`, and the compatibility `main.py` entry point work from a clean checkout.

## 2. Introduce shared application state

Replace module-level mutable globals such as `latest_frame` and `rotation_quarter_turns` with an explicit state model.

The state should eventually represent at least:

```python
@dataclass
class CaptureSettings:
    rotation: int = 1
    camera_id: str | None = None
    mode: str = "chat"
```

Use clear locking or thread-safe accessors for mutable state. The future GUI and global hotkey listener must read and update the same state.

## 3. Separate responsibilities

Refactor the current application layer into distinct responsibilities:

- Camera and AVFoundation session management
- Latest-frame storage
- Frame transformation
- Clipboard encoding and writing
- Hotkey registration
- Preview/UI management

The GUI should eventually consume and control these services without owning the capture workflow.

## 4. Make frame dimensions explicit

The current `width` and `height` values are passed into the native camera object but are not used to enforce the actual frame size.

Decide whether the configured dimensions describe:

- the AVFoundation camera format;
- the normalized frame used by capture;
- or only the preview.

Then implement and document that behavior. If the requested camera format cannot be selected reliably, resize frames after capture.

## 5. Use stable camera identities

Use AVFoundation's stable device identifier as the primary camera identity, with the localized device name for display.

Camera indexes may remain as a fallback for navigation, but they should not be treated as persistent identities because device ordering can change.

## 6. Extract pure frame-processing functions

Create hardware-independent functions for:

- Applying rotation
- Resizing
- JPEG encoding
- Future ROI cropping
- Future submission processing

These functions should accept and return image arrays or encoded bytes without requiring macOS permissions, camera hardware, or clipboard access.

## 7. Make clipboard capture asynchronous and serialized

Move image encoding and clipboard operations off the global-hotkey callback thread.

Use a small worker or single-item queue so that:

- hotkey callbacks return quickly;
- captures cannot corrupt one another;
- repeated presses are serialized or intentionally coalesced;
- status and failures can be exposed to the future GUI.

## 8. Define structured capture status

Replace print-only feedback with a structured result and status model, for example:

```python
@dataclass
class CaptureResult:
    success: bool
    message: str
    byte_size: int | None = None
```

The model should support statuses such as `ready`, `capturing`, `copied`, and `error`. The console can continue displaying these statuses, while the GUI can later render them directly.

## 9. Add automated tests

Add unit tests for:

- All four rotation orientations
- Camera-index navigation
- Camera-selection fallback
- Frame copying and locking behavior
- JPEG encoding failure handling
- ROI bounds and cropping once ROI support exists
- Submission processing using fixture images

Keep camera, Accessibility, and clipboard tests as optional macOS integration tests so the core test suite can run without hardware.

## 10. Add development tooling

Add lightweight project tooling for:

- Formatting
- Linting
- Type checking where useful
- Test execution

Add a basic CI job for syntax checks, unit tests, and packaging validation. Hardware-dependent tests should be skipped outside macOS.

## 11. Harden lifecycle and shutdown behavior

Verify that:

- camera sessions always stop cleanly;
- notification observers are removed;
- hotkey listeners terminate;
- worker threads do not outlive the application;
- failed camera starts do not leak partially-created sessions;
- sleep/wake recovery cannot start duplicate sessions;
- camera switching cannot race with capture or shutdown.

## 12. Define the future feature contract

Before implementing the GUI, document the interfaces it will consume and control:

- Current frame
- Available cameras
- Selected camera
- Rotation
- Capture mode
- ROI
- Capture status
- Capture request

The GUI should act as a preview and configuration layer. It must not become a prerequisite for global capture.

## Completion criteria

This prerequisite phase is complete when:

- the existing global hotkey workflow still captures and copies images;
- camera and capture state have explicit, thread-safe ownership;
- frame-processing logic is independently testable;
- camera resolution and identity behavior are documented and implemented;
- capture status can be consumed by both console and future GUI code;
- lifecycle and shutdown behavior are covered by tests or documented integration checks;
- the project has a repeatable local and CI validation command.

Only after these criteria are met should implementation proceed to the Dear PyGui modernization, followed by submission capture mode.
