# Feature Brief 2: Submission Capture Mode

## Dependency

This feature should be implemented **after Feature 1: Dear PyGui GUI Modernization** is working and the existing global-hotkey capture workflow has been verified.

Submission mode should build on the GUI and shared capture-state architecture introduced by Feature 1.

Do not combine the GUI migration and submission-mode implementation into one large change.

---

## Background

`math-camera` is primarily used for fast interactive capture of handwritten math work.

The current workflow is:

```text
position work under the IPEVO
→ press global capture hotkey
→ image goes to clipboard
→ paste into ChatGPT
```

The same camera is also useful when preparing homework for submission.

Today, captured images can be pasted into Apple Notes and exported from there, but raw captures often include:

- unnecessary desk/background
- unused portions of the paper
- inconsistent framing
- uneven paper lighting
- more pixels/data than necessary

The LMS used for submission also has document-size limits.

Add a second capture mode optimized for creating **clean, tightly cropped, compact images** that can be pasted into Notes.

This is not a PDF-generation feature.

---

## Goal

Add a `SUBMISSION` capture mode that:

- lets the user select only the interesting work
- can suggest a useful ROI automatically
- allows manual ROI adjustment in the Dear PyGui preview
- lightly cleans up paper/handwriting
- downsizes images to an appropriate resolution
- produces compact PNG output
- places the processed image on the clipboard
- preserves the existing global capture hotkey workflow

The fundamental unit is an arbitrary **region of handwritten work**, not an 8.5×11 sheet.

The selected region may be:

- portrait
- landscape
- square
- wide and shallow
- tall and narrow

Do not impose a page aspect ratio.

---

## Capture Modes

Expose mode selection in Dear PyGui:

```text
[ CHAT ]   [ SUBMISSION ]
```

### CHAT

Preserve existing capture behavior as closely as possible.

Optimize for:

- speed
- fidelity
- interactive use with ChatGPT
- minimal processing

### SUBMISSION

Use the same global capture hotkey, but apply the submission capture pipeline.

Optimize for:

- tight ROI
- clean appearance
- readable pencil/ink
- compact image size
- easy paste into Apple Notes

The GUI controls the current mode.

The global hotkey always captures according to the currently selected mode.

---

## Region of Interest

In submission mode, show a rectangular ROI overlay on the Dear PyGui camera preview.

The ROI should:

- support arbitrary aspect ratio
- be movable
- be resizable
- stay within the usable camera frame
- remain active until changed
- remember its last position and size if practical

### Manual ROI Editing

The user should be able to:

- drag inside the ROI to move it
- drag corners to resize it
- optionally drag edges to resize it
- reset the ROI to a sensible default
- request automatic ROI detection

The interaction should feel lightweight enough to use repeatedly while doing homework.

---

## Automatic ROI Suggestion

Provide an `Auto ROI` action in the GUI.

The goal is **not** to detect the physical sheet of paper.

The IPEVO has a constrained field of view, and the user often wants only one problem or worked region anyway.

Instead, try to identify the bounding area containing meaningful handwritten or printed content.

A possible OpenCV approach:

```text
camera frame
    ↓
grayscale
    ↓
lighting normalization
    ↓
foreground/content mask
    ↓
remove small noise
    ↓
morphology to connect nearby content
    ↓
bounding rectangle
    ↓
add margin
    ↓
suggest ROI
```

The automatic suggestion does not need to be perfect.

It should produce a useful starting rectangle that the user can manually adjust.

### Important

Automatic ROI detection must never prevent manual selection.

If auto-detection fails or produces a poor suggestion, the user should simply adjust the ROI.

---

## Preview Behavior

Keep preview behavior simple.

Do **not** add a separate processed-preview mode initially.

The Dear PyGui window should show:

- the normal live camera image
- the active ROI
- current mode
- any useful lightweight status

Processing should happen at capture time.

This avoids additional mode/UI complexity.

---

## Submission Capture Pipeline

When the global capture hotkey is pressed while `SUBMISSION` mode is active:

```text
latest camera frame
    ↓
apply current rotation
    ↓
crop to ROI
    ↓
light image cleanup
    ↓
grayscale
    ↓
downscale
    ↓
encode as compact PNG
    ↓
write image to system clipboard
```

Then the user can immediately paste the result into Notes.

The GUI should not need focus during this operation.

---

## Image Cleanup

Use conservative document-oriented processing.

The objective is:

```text
paper → lighter and more even
writing → clearly visible
lighting variation → reduced
```

while preserving subtle mathematical notation.

A reasonable starting OpenCV pipeline:

```python
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

background = cv2.GaussianBlur(gray, (0, 0), 25)
normalized = cv2.divide(gray, background, scale=255)

clahe = cv2.createCLAHE(
    clipLimit=1.5,
    tileGridSize=(8, 8),
)

clean = clahe.apply(normalized)
```

Optional mild sharpening:

```python
blur = cv2.GaussianBlur(clean, (0, 0), 1.0)
clean = cv2.addWeighted(clean, 1.3, blur, -0.3, 0)
```

These values are starting points and should be easy to tune.

### Preserve Fine Math Detail

Do not use aggressive thresholding by default.

Preserve:

- faint pencil
- minus signs
- decimal points
- superscripts
- fraction bars
- graph lines
- small digits
- lightly erased or reworked calculations

The processing should be mild enough that a separate processed preview is not required.

---

## Image Size Optimization

The LMS has document-size limits.

The submission pipeline should produce images that are as small as practical without sacrificing readability.

Prioritize size reduction in this order:

1. tight ROI
2. grayscale
3. downscaling
4. PNG optimization

### Downscale

Full IPEVO resolution is unnecessary for ordinary handwritten homework once the interesting region has been tightly cropped.

Use a configurable maximum dimension.

A reasonable starting target:

```text
long edge: 1400–1600 px
```

Example:

```python
MAX_DIM = 1600

h, w = image.shape[:2]
scale = min(1.0, MAX_DIM / max(w, h))

if scale < 1:
    image = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
```

Tune this using real homework containing small notation.

### PNG

Use PNG for the clipboard output.

PNG is acceptable for this workflow and avoids lossy artifacts around small mathematical marks.

Because the images should be:

- tightly cropped
- grayscale
- mostly white background
- reduced in resolution

PNG should compress reasonably well for this content.

If OpenCV or the clipboard layer supports useful PNG compression settings, use them where they do not add noticeable capture latency.

---

## Optional Size Feedback

If easy to provide, display approximate encoded output size in the Dear PyGui status area.

For example:

```text
SUBMISSION | ROI 1180×720 | ~140 KB
```

This is useful for tuning output size, but should not block the initial implementation.

---

## GUI Controls

Add submission controls to the Dear PyGui panel.

Conceptually:

```text
Mode: [ CHAT ] [ SUBMISSION ]

ROI:
[ Auto ROI ] [ Reset ROI ]

Preview:
+ draggable/resizable ROI overlay

Status:
SUBMISSION | ROI 1180×720
```

Avoid adding global hotkeys for these low-frequency controls.

The existing global capture hotkey remains the main capture action.

---

## State Model

Extend the shared settings introduced in Feature 1.

Conceptually:

```python
@dataclass
class CaptureSettings:
    mode: str = "chat"
    rotation: int = 0
    roi: tuple | None = None
```

Dear PyGui updates these settings.

The global hotkey capture path reads them.

Conceptually:

```text
Dear PyGui
  ├── mode
  ├── ROI
  └── rotation
       ↓
CaptureSettings
       ↓
global capture hotkey
       ↓
CHAT pipeline or SUBMISSION pipeline
       ↓
clipboard
```

---

## Non-Goals

Do not implement:

- PDF generation
- page assembly
- Notes integration
- OCR
- automatic 8.5×11 document detection
- forced portrait/landscape orientation
- document management
- image galleries
- processed live preview
- perspective correction unless testing later shows a clear need

Apple Notes remains responsible for assembling the pasted images and producing the final PDF.

---

## Suggested Implementation Sequence

### Phase 1: Mode Plumbing

Add `CHAT` and `SUBMISSION` mode state to the Dear PyGui interface and shared capture settings.

Success criterion:

> The global hotkey can choose different capture pipelines based on the current GUI-selected mode.

### Phase 2: Manual ROI

Add ROI display and manual manipulation in Dear PyGui.

Use the ROI for submission-mode captures.

Success criterion:

> I can select only the interesting work, press the global hotkey from another app, and paste the cropped result.

### Phase 3: Cleanup + Size Optimization

Add:

- grayscale conversion
- lighting normalization
- mild contrast enhancement
- downscaling
- PNG encoding

Success criterion:

> Submission captures are cleaner and substantially smaller than raw camera captures while preserving small pencil notation.

### Phase 4: Automatic ROI Suggestion

Add content-based ROI suggestion.

Success criterion:

> For common homework layouts, `Auto ROI` produces a useful starting crop that usually requires little or no adjustment.

---

## Acceptance Criteria

Feature 2 is complete when this workflow works comfortably:

```text
1. Launch math-camera.

2. Use Dear PyGui to select SUBMISSION mode.

3. Position handwritten work under the IPEVO.

4. Use Auto ROI or manually adjust the ROI around the interesting work.

5. Return to ChatGPT, Notes, or another application.

6. Press the existing global capture hotkey.

7. math-camera:
   - captures in the background
   - crops to the current ROI
   - lightly cleans the image
   - converts it to grayscale
   - downsizes it
   - encodes it as PNG
   - places it on the clipboard

8. Paste normally.

9. The pasted image:
   - contains only the relevant work
   - is easy to read
   - preserves faint mathematical notation
   - looks cleaner than the raw camera frame
   - is substantially smaller than the original capture
```

---

## Guiding Principle

Submission mode should extend the application's core interaction rather than replace it:

> **Configure visually when necessary, then capture invisibly with the same global hotkey.**

For submission:

> **select useful math → lightly clean it → make it small → clipboard → paste**
