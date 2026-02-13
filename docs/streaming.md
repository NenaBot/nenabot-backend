# Video Streaming Guide

The orchestrator exposes two live MJPEG video streams over HTTP.
Both use the standard `multipart/x-mixed-replace` content type which is
natively supported by browsers.

## Available streams

| Stream | Endpoint | Description |
|---|---|---|
| Camera (raw) | `GET /streams/camera/feed` | Raw camera frames, no processing |
| Detection overlay | `GET /streams/detection/feed` | Frames annotated with ArUco markers and battery contour |

## Quick-start

```bash
# 1. Start the orchestrator
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Open the feed in a browser
open http://localhost:8000/streams/camera/feed
```

## Stream viewer (HTML test page)

A standalone HTML file is included at `docs/stream-viewer.html`. Open it
directly in a browser to test both feeds without writing any code.

```bash
open docs/stream-viewer.html
```

Features:
- **API URL** field (defaults to `http://localhost:8000`)
- **Start / Stop** buttons for each feed (camera + detection)
- **Snapshot** button that calls `POST /paths` and logs the detected
  battery corners to the on-screen log
- Status badges showing LIVE / OFF per stream

> The viewer works as a plain file — no build step or web server needed.
> CORS is already enabled on the orchestrator (`CORSMiddleware`).

## Testing the streams

### Browser

Open `http://localhost:8000/streams/camera/feed` directly. The browser
renders the MJPEG stream natively as a continuously updating image.

### curl

```bash
# Save 5 seconds of MJPEG to a file
curl --max-time 5 -o camera.mjpeg http://localhost:8000/streams/camera/feed

# Pipe to ffplay for live preview
curl -s http://localhost:8000/streams/detection/feed | ffplay -f mjpeg -
```

### Python (requests)

```python
import requests

with requests.get("http://localhost:8000/streams/camera/feed", stream=True) as r:
    for chunk in r.iter_content(chunk_size=4096):
        # each chunk is part of a JPEG frame boundary
        print(f"received {len(chunk)} bytes")
```

## Frontend integration

### HTML `<img>` tag (simplest)

```html
<img src="http://localhost:8000/streams/camera/feed" alt="Live camera" />
<img src="http://localhost:8000/streams/detection/feed" alt="Detection overlay" />
```

The `<img>` tag supports `multipart/x-mixed-replace` natively in all
major browsers. The image updates automatically — no JavaScript needed.

### React component

```tsx
export function CameraFeed({ stream = "camera" }: { stream?: "camera" | "detection" }) {
  const src = `${import.meta.env.VITE_API_URL}/streams/${stream}/feed`;
  return (
    <img
    src={src}
    alt={`${stream} feed`}
    style={{ width: "100%", maxWidth: 640 }}
    />
  );
}
```

### JavaScript fetch (for programmatic frame access)

```js
async function readStream(url) {
  const response = await fetch(url);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // Each chunk contains JPEG data bounded by --frame markers.
    // Parse the boundary to extract individual JPEG blobs if needed.
    console.log(`chunk: ${value.length} bytes`);
  }
}

readStream("/streams/camera/feed");
```

> **Note**: For most UIs the `<img>` tag approach is recommended. Use
> `fetch` only if you need frame-by-frame processing (e.g. rendering
> onto a Canvas or running client-side ML).

## Lifecycle — when does a stream start and stop?

The stream is entirely **on-demand**. There are no separate start/stop
API calls.

| Event | What happens |
|---|---|
| Client connects to `/streams/camera/feed` | Adapter opens `cv2.VideoCapture`, begins yielding JPEG frames |
| Client disconnects (tab closed, fetch aborted) | Starlette detects the broken connection, the async generator's `finally` block runs, `cap.release()` frees the camera |
| No clients connected | Camera is **not open**, zero CPU/memory used |

This means the camera is only active while someone is watching. Closing
the browser tab (or aborting a `curl`) is enough to release all
resources. No background thread keeps running.

## How it works internally

1. `GET /streams/{type}/feed` returns a `StreamingResponse` wrapping the
    adapter's async generator.
2. The generator opens `cv2.VideoCapture`, reads frames in a loop, and
    yields JPEG-encoded bytes with MJPEG boundary headers.
3. For the detection feed, each frame is passed through `detect_live()`
    which runs ArUco detection + contour analysis and draws overlays
    before encoding.
4. Frame rate is capped at ~30 fps (`asyncio.sleep(0.033)`).
5. JPEG quality is set to 70 to balance bandwidth and clarity.
6. When the client disconnects, the generator exits its `finally` block
    and releases the camera. No background process lingers.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Black/empty image | Camera not connected or wrong device index | Set `device_index` in `CameraVisionAdapter` constructor |
| Choppy stream | CPU-bound detection on Pi | Lower resolution in adapter (`frame_width`, `frame_height`) |
| Stream freezes | Two feeds competing for same camera device | Use one stream at a time, or use a shared capture thread |
| CORS errors in browser | Frontend on different origin | Add `CORSMiddleware` to `app.main` |
