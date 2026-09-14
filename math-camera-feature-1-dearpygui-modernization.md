# Feature Brief 1: Dear PyGui GUI Modernization

## Background

`math-camera` is a small OpenCV-based utility used with an IPEVO V4K document camera.

Its most important existing workflow is:

```text
stay in any application
→ press a global capture hotkey
→ math-camera captures from the camera in the background
→ the captured image is written to the system clipboard
→ paste with Cmd/Ctrl+V
```

This background capture + clipboard workflow is the application's core feature and must remain intact.

The application has accumulated preview controls and hotkeys for things such as rotation and camera interaction. As additional features are added, continuing to add more hotkeys will make the utility harder to operate.

Introduce **Dear PyGui** as a lightweight GUI layer for previewing and configuring capture behavior.

This is a major structural change and should be implemented independently from new submission-processing features.

---

## Goal

Add a small Dear PyGui control panel that provides:

- live camera preview
- camera selection where needed
- rotation/orientation controls
- current capture mode
- status information
- a foundation for future ROI controls
- a place for low-frequency configuration that would otherwise require additional hotkeys

The GUI should make the utility easier to configure without changing the core background capture workflow.

---

## Core Requirement: Preserve Background Capture

The GUI must **not** become a prerequisite for capture.

The following workflow must continue to work:

```text
Dear PyGui window is open, minimized, obscured, or unfocused
        ↓
user is working in ChatGPT / Notes / browser / another app
        ↓
user presses the existing global capture hotkey
        ↓
math-camera captures using current settings
        ↓
image is placed on the system clipboard
        ↓
user pastes normally
```

Do not require:

- GUI focus
- clicking a capture button
- switching windows
- interacting with the preview before each capture

This behavior is an acceptance criterion, not an implementation detail.

---

## Dear PyGui Responsibilities

Use Dear PyGui as the lightweight desktop UI layer.

The GUI should initially support:

- live IPEVO/OpenCV camera preview
- camera selector if the existing app supports multiple cameras
- rotation/orientation control
- display of current capture mode
- basic capture status
- room for later ROI editing controls
- room for later submission-mode controls

The GUI should remain small and utilitarian.

A conceptual layout:

```text
┌──────────────────────────────────────┐
│ Camera: [IPEVO V4K ▼]               │
│ Mode:   [ CHAT ]                     │
│ Rotation: [0°] [90°] [180°] [270°] │
│                                      │
│          live camera preview         │
│                                      │
│ Status: Ready                        │
└──────────────────────────────────────┘
```

Exact layout is not prescribed.

---

## Live Preview

Display the OpenCV camera frame inside Dear PyGui.

Prefer Dear PyGui's dynamic/raw texture support or another efficient mechanism appropriate for continuously updating image data.

The preview should:

- remain responsive
- preserve the existing camera aspect ratio
- correctly reflect rotation/orientation settings
- be suitable for future overlay drawing such as ROI rectangles

Avoid unnecessary frame conversions or copies if they noticeably impact responsiveness.

---

## Shared Capture State

Separate GUI state from capture implementation.

The GUI should update shared application settings, while the global hotkey capture path reads those settings independently.

Conceptually:

```python
@dataclass
class CaptureSettings:
    mode: str = "chat"
    rotation: int = 0
    camera_id: str | int | None = None
```

The actual structure should fit the existing codebase.

Architecture:

```text
                         ┌── Global hotkey listener
                         │
Camera / Frame Source ───┼── Capture pipeline ──→ Clipboard
        │                │
        │                └── Shared CaptureSettings
        │                             ▲
        ▼                             │
 Dear PyGui preview/settings ─────────┘
```

Changing a setting in the GUI should affect subsequent global-hotkey captures.

The capture path should not depend on whether the GUI currently has focus.

---

## Hotkey Strategy

Do not remove useful existing hotkeys unnecessarily.

However, avoid adding a new global hotkey for every new feature.

Use global hotkeys primarily for actions that benefit from being available while another application is focused.

The most important hotkey is:

```text
capture current camera image → clipboard
```

Lower-frequency controls should move into the GUI where practical, including:

- camera selection
- rotation
- mode selection
- future ROI reset / auto-fit controls
- future processing settings

This should reduce the application's global-hotkey vocabulary over time.

---

## Threading / Event Loop Considerations

Dear PyGui introduces its own event loop.

The implementation must ensure that:

- camera acquisition continues reliably
- the preview remains responsive
- global hotkeys remain active while the GUI is unfocused
- capture does not depend on the GUI event loop being foregrounded
- clipboard operations continue to work as before

Prefer a design in which camera acquisition and capture logic are not owned exclusively by GUI callbacks.

The GUI should be a consumer/controller of application state, not the sole owner of core functionality.

---

## GUI Non-Goals

Do not turn this into a large desktop application.

Do not add:

- document management
- image galleries
- PDF workflows
- file browsers
- unnecessary menus
- modal dialogs for routine operation
- elaborate theming or layout work

The GUI exists primarily to provide:

> **preview + configuration**

while preserving:

> **global hotkey + clipboard capture**

---

## Suggested Implementation Sequence

### Phase 1: Dear PyGui Spike

Prove that the existing OpenCV camera stream can be displayed smoothly in Dear PyGui.

Success criterion:

> The IPEVO preview renders correctly and remains responsive.

### Phase 2: Shared Settings

Move current preview/configuration state such as rotation and camera selection into a shared settings model controlled by the GUI.

Success criterion:

> GUI changes immediately affect the preview and subsequent captures.

### Phase 3: Preserve Global Capture

Integrate the existing global hotkey capture path with the new architecture.

Success criterion:

> While ChatGPT or another application has focus, the existing hotkey still captures and places the image on the clipboard without interacting with the GUI.

### Phase 4: Retire Redundant UI Hotkeys

Where appropriate, move low-frequency controls into Dear PyGui and simplify the hotkey set.

Do this only after the equivalent GUI controls are working reliably.

---

## Acceptance Criteria

Feature 1 is complete when:

1. `math-camera` launches with a small Dear PyGui control panel.
2. The live IPEVO preview appears correctly.
3. Rotation/orientation can be controlled from the GUI.
4. Current capture mode is visible in the GUI.
5. Existing capture behavior is preserved.
6. The GUI may be unfocused or in the background.
7. Pressing the existing global capture hotkey still captures successfully.
8. The captured image appears on the system clipboard.
9. The user can immediately paste into ChatGPT, Notes, or another application.
10. The architecture provides a clean place to add ROI controls and additional modes later.

---

## Guiding Principle

The Dear PyGui change should make `math-camera` easier to configure without weakening the feature that makes it useful:

> **Stay in the application where you are working, press one hotkey, and paste the camera capture immediately.**
