# Math Camera

*A tiny macOS utility that makes paper-and-pencil work easy to share with an AI.*

## TL;DR

Math Camera turns a USB document camera into a **one-key screenshot tool for your desk**.

I built it because I do a lot of math with pencil and paper and physical textbooks. Taking pictures with my phone and uploading them to ChatGPT was just annoying enough to interrupt the flow.

With Math Camera:

1. A document camera stays pointed at the desk.
2. A small Python program keeps the latest frame in memory.
3. Press **Control + Option + M** from anywhere.
4. The current camera image is copied to the macOS clipboard at low resolution for quick pasting.
5. Press **Command + V** in ChatGPT.

That's it.

You can keep working on paper and, whenever you want help, capture exactly what you're looking at.

---

## Quick Start

### Requirements

- macOS
- A USB document camera or webcam
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)

I'm using an **IPEVO V4K**, but Math Camera should work with other cameras supported by macOS and AVFoundation.

### Install

Clone the repository:

```bash
git clone <repo-url>
cd math-camera
```

Install the project and its dependencies:

```bash
uv sync
```

Or install directly from GitHub with `pip`:

```bash
pip install "git+https://github.com/odewahn/math-camera.git"
```

### macOS permissions

Math Camera listens for a global keyboard shortcut, so macOS needs to allow the application running it to receive keyboard events.

Go to:

**System Settings → Privacy & Security → Accessibility**

and enable Terminal, iTerm, Warp, or whichever application you're using to run Math Camera.

macOS may also ask for **Camera** permission the first time you run it.

If Accessibility permission is missing, Math Camera prints the exact settings path and exits so you can enable it before retrying.

### Run

```bash
uv run math-camera
```

The repository also keeps `main.py` as a compatibility wrapper, so this still works too:

```bash
uv run python main.py
```

To list cameras without starting the preview:

```bash
uv run math-camera --list-cameras
```

Math Camera now opens AVFoundation camera `0` by default if it exists, or the first available AVFoundation camera otherwise.

If the wrong camera opens, switch cameras from the preview window:

- **N** for next camera
- **P** for previous camera

When the terminal has focus, use the global shortcuts **Control + Option + N**
and **Control + Option + P** instead. Plain `N` and `P` typed in the terminal
are only echoed by the shell and cannot be seen by the preview window.

You can also inspect the available camera indexes ahead of time:

```text
Available camera indexes:

[0] 1280x720
[1] 1280x720
[2] 1920x1080
```

A live preview window will appear.

### Capture

Put your notebook or book under the camera.

From **any application**, press:

**Control + Option + M** for a smaller, faster paste

or

**Control + Option + Shift + M** for a higher-detail image

The current frame is copied to the macOS clipboard.

Switch to ChatGPT and press:

**Command + V**

Then ask whatever you want:

> Where did I make a mistake?

> Don't give me the answer—give me a hint.

> What is happening in the third line of this proof?

That's the entire workflow.

---

## Why I built it

AI is surprisingly awkward when the thing you're working on isn't on your computer.

I ran into this while studying mathematics. I prefer working with pencil and paper, and much of the material I'm studying is in physical books. ChatGPT is useful for checking my work, providing hints, or discussing a proof, but getting the state of my desk into the conversation usually meant stopping, grabbing my phone, taking a picture, and uploading it.

That's enough friction to interrupt the flow of actually doing the work.

Math Camera removes most of it.

The goal isn't to continuously stream my desk to an AI. The AI only needs to see my work **when I want to talk about it**.

So the interaction becomes:

```text
work normally with pencil and paper

              ↓

          I want help

              ↓

      Control + Option + M

              ↓

     AI can see my desk
```

It's simple, explicit, and surprisingly effective.

---

## Hardware

My setup uses an **IPEVO V4K** document camera connected directly to a Mac.

The V4K is an inexpensive USB document camera intended for teaching, presentations, and document capture. It appears to macOS as a normal video device, so Math Camera doesn't require any IPEVO-specific software or SDK.

The physical setup is basically:

```text
             IPEVO V4K
                 │
                 ▼
        ┌─────────────────┐
        │                 │
        │    textbook     │
        │       or        │
        │    notebook     │
        │                 │
        └─────────────────┘
```

The camera stays running while I work.

For notebooks and textbooks, I've found it useful to physically rotate the V4K camera head by 90 degrees. That produces a field of view better suited to a single page.

Math Camera rotates the resulting image back upright in software.

The current setup captures at **1280×720**, which has proven sufficient for both handwritten pencil work and fairly small textbook type.

---

## How it works

The architecture is deliberately boring:

```text
                       ┌─────────────────┐
                       │ IPEVO / webcam  │
                       └────────┬────────┘
                                │
                         AVFoundation
                                │
                                ▼
                       ┌─────────────────┐
                       │  AVFoundation  │
                       │                 │
                       │ frame delegate │
                       │ latest frame   │
                       └────────┬────────┘
                                │
                     Control + Option + M
                                │
                                ▼
                       ┌─────────────────┐
                       │ Encode one JPEG │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ macOS clipboard │
                       └────────┬────────┘
                                │
                           Command + V
                                │
                                ▼
                       ┌─────────────────┐
                       │     ChatGPT     │
                       └─────────────────┘
```

AVFoundation continuously delivers frames through a native capture session, while Math Camera **doesn't continuously save images to disk**.

Instead, it keeps the newest frame in memory:

```python
with frame_lock:
    latest_frame = frame.copy()
```

When the global keyboard shortcut is pressed, the program copies that frame, encodes it as a JPEG, and puts it on the macOS clipboard.

Math Camera keeps the frame dimensions the same and switches between two JPEG quality levels instead:

- **Low resolution** uses stronger compression for smaller files and faster pasting
- **High resolution** uses lighter compression for more detail and larger files

The JPEG exists on disk only briefly as an implementation detail and is deleted immediately afterward.

This keeps the program lightweight while making capture feel nearly instantaneous.

---

## Camera discovery

One complication with webcams is that device numbers aren't necessarily stable.

The IPEVO might be camera `0` at one point, but connecting an iPhone, another webcam, or another video device can change the ordering.

Instead of hard-coding:

```python
CAMERA_INDEX = 0
```

Math Camera uses **AVFoundation via PyObjC** to discover cameras and receive frames through a native capture session. OpenCV is used for preview processing, rotation, resizing, and JPEG encoding.

```text
Available camera indexes:

  [0]
  [1]
  [2]
  [3]
```

You select the camera you want when Math Camera starts.

This also means the program isn't actually tied to the IPEVO. Other cameras supported by macOS and AVFoundation should work as well.

---

## Portrait and landscape modes

Math Camera starts in portrait mode by default, which is what I use for books and notebooks.

The camera head is usually turned sideways, which gives a more useful field of view for a page. Math Camera starts with a 90-degree clockwise rotation so the resulting image is upright.

While the app is running, you can rotate the live frame in either direction:

- **Control + Option + .** rotates **+90 degrees**
- **Control + Option + ,** rotates **-90 degrees**

The rotation is cumulative, so pressing either shortcut four times returns to the starting orientation.

This affects both the clipboard capture and the live preview. The preview continues to scale itself based on the current rotated frame dimensions.

---

## Live preview

Math Camera displays a small OpenCV preview window while it is running.

This makes it easy to position a notebook or book underneath the camera without having to take test pictures.

The preview is scaled down while preserving the camera's aspect ratio:

```python
scale = min(
    max_preview_width / width,
    max_preview_height / height,
    1.0,
)

preview = cv2.resize(
    frame,
    None,
    fx=scale,
    fy=scale,
)
```

Only the preview is scaled down. The frame kept in memory for capture remains at the configured camera resolution.

---

## Capturing an image

There are two ways to capture the current frame.

### Global hotkey

The main interface is:

**Control + Option + M** for low resolution

and

**Control + Option + Shift + M** for high resolution

Math Camera uses `pynput` to listen for these shortcuts globally:

```python
listener = keyboard.GlobalHotKeys({
    "<ctrl>+<alt>+m": copy_low_quality_frame_to_clipboard,
    "<ctrl>+<alt>+<shift>+m": copy_high_quality_frame_to_clipboard,
    "<ctrl>+<alt>+.": rotate_clockwise,
    "<ctrl>+<alt>+,": rotate_counterclockwise,
})
```

That means the preview doesn't need to have focus.

I can be typing in ChatGPT, press **Control + Option + M**, and the current view of the desk is placed on the clipboard.

Then:

**Command + V**

pastes it directly into the conversation.

### Preview shortcut

If the preview window has focus, pressing:

**C** for low resolution

or

**H** for high resolution

performs the same capture.

This is mostly useful for testing.

---

## Controls

| Control | Action |
| --- | --- |
| **Control + Option + M** | Low-resolution capture from anywhere |
| **Control + Option + Shift + M** | High-resolution capture from anywhere |
| **Control + Option + .** | Rotate by +90 degrees |
| **Control + Option + ,** | Rotate by -90 degrees |
| **C** | Low-resolution capture when the preview has focus |
| **H** | High-resolution capture when the preview has focus |
| **N** | Switch to the next camera |
| **P** | Switch to the previous camera |
| **Q** | Quit |
| **Esc** | Quit |

---

## Dependencies

Math Camera is intentionally small.

### OpenCV

Used for:

- camera capture
- frame rotation
- preview resizing
- JPEG encoding

### PyObjC / AVFoundation

Used for native camera sessions, frame delivery, device discovery, and sleep/wake recovery.

This lets Math Camera show `IPEVO V4K` instead of simply `Camera 0`.

### pynput

Used to listen for the global **Control + Option + M** shortcut.

### AppleScript

Used to put the captured JPEG onto the macOS clipboard.

There is no server, database, cloud service, or AI API involved.

In fact, Math Camera itself knows nothing about ChatGPT. Its entire job is to make the current state of the physical desk available on the clipboard.

---

## The actual workflow

Once Math Camera is running, I mostly forget that it's there.

I put whatever I'm working on under the camera and work normally.

When I want help:

```text
Control + Option + M
Command + V
```

Then I type the question.

For handwritten work:

> Where did I make a mistake?

> Is this factoring correct?

> Don't solve it for me. What should I notice next?

For a textbook:

> I understand the first two lines of this proof. Why is the third line justified?

> What does this notation mean?

> Explain what the author is trying to establish here.

The important part is that I don't have to explain *which* equation, paragraph, diagram, or handwritten step I'm talking about.

The image supplies that context.

---

## Why not continuously send video to an AI?

That was actually closer to the original idea.

The imagined version was an AI continuously aware of the desk: watching work develop, recognizing which textbook was open, understanding which problem was being attempted, and perhaps eventually projecting annotations back onto the desk.

That would be fun.

It would also be a considerably larger project.

The useful realization was that the AI doesn't really need to **watch me do math**.

It needs to see the current state of my work **when I want to talk about it**.

The hotkey provides a natural boundary:

```text
normal paper-and-pencil work

          ↓

     I want help

          ↓

        hotkey

          ↓

AI gets the current state of the desk
```

That gets most of the value without continuous video streaming, image processing, or AI inference.

---

## Where this could go

There are plenty of obvious extensions.

Math Camera could eventually support:

- automatic page detection and cropping
- perspective correction
- contrast enhancement for pencil writing
- configurable capture resolutions
- multiple capture regions
- separate textbook and notebook views
- remembering the current textbook page
- automatic page-change detection
- voice-triggered capture
- local vision models
- sending images directly to an AI API
- maintaining context across a study session

A more ambitious version could distinguish between **source material** and **work**:

```text
┌──────────────────┐     ┌──────────────────┐
│      SOURCE      │     │       WORK       │
│                  │     │                  │
│ textbook page    │     │ notebook page    │
│ theorem/example  │     │ current solution │
└──────────────────┘     └──────────────────┘
```

Then a question could implicitly mean:

> Here's the material I'm studying, here's what I've done so far, and here's my question.

You could go much further from there: page recognition, persistent context, local vision models, voice interaction, or even projection back onto the physical work surface.

But that's deliberately **not** what Math Camera is yet.

The useful version turned out to be a document camera, a small Python program, and one keyboard shortcut.

**The point isn't to digitize the desk. It's to make the boundary between working on paper and asking an AI about what you're doing almost disappear.**
