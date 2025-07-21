#!/usr/bin/python3

# Mostly copied from https://picamera.readthedocs.io/en/release-1.13/recipes2.html
# Run this script, then point a web browser at http:<this-ip-address>:8000
# Note: needs simplejpeg to be installed (pip3 install simplejpeg).

import io
import logging
import socketserver
from http import server
from threading import Condition

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

PAGE = """\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
<script>
function zoomIn() {
    fetch('/zoom-in', {method: 'POST'})
        .then(response => {
            if (!response.ok) alert('Zoom failed');
        });
}
function zoomOut() {
    fetch('/zoom-out', {method: 'POST'})
        .then(response => {
            if (!response.ok) alert('Zoom failed');
        });
}
</script>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<button onclick=\"zoomIn()\">Zoom In</button>
<button onclick=\"zoomOut()\">Zoom Out</button><br/>
<img src="stream.mjpg" width="1280" height="720" />
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    if frame is not None:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/zoom-in':
            increment_zoom()
            self.send_response(204)
            self.end_headers()
        elif self.path == '/zoom-out':
            decrement_zoom()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

picam2 = Picamera2()

# Global zoom variables
current_zoom = 0
zoom_steps = [(0, 0, 4656, 3496),      # Full sensor
              (582, 437, 3492, 2622),   # 25% crop
              (1164, 874, 2328, 1748),  # 50% crop
              (1746, 1311, 1164, 874)]  # 75% crop

def increment_zoom():
    global current_zoom
    current_zoom = (current_zoom + 1) % len(zoom_steps)
    crop = zoom_steps[current_zoom]
    picam2.set_controls({"ScalerCrop": crop})
    print(f"Zoom level {current_zoom}: crop {crop}")

def decrement_zoom():
    global current_zoom
    current_zoom = (current_zoom - 1) % len(zoom_steps)
    crop = zoom_steps[current_zoom]
    picam2.set_controls({"ScalerCrop": crop})
    print(f"Zoom level {current_zoom}: crop {crop}")

# Print available sensor modes
sensor_modes = picam2.sensor_modes
for i, mode in enumerate(sensor_modes):
    print(f"Mode {i}: {mode}")

# Find the full resolution mode (4656x3496)
full_res_mode = None
for mode in sensor_modes:
    if mode['size'] == (4656, 3496):
        full_res_mode = mode
        break

if full_res_mode is None:
    print("Warning: Full resolution mode not found, using mode 0")
    full_res_mode = sensor_modes[0]

print(f"Using sensor mode: {full_res_mode}")

# Configure for full sensor resolution with reasonable streaming output
config = picam2.create_video_configuration(
    main={"size": (1920, 1440), "format": 'XRGB8888'},  # 4:3 aspect ratio output
    raw=full_res_mode
)

picam2.configure(config)
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))

# Start with full sensor view (no cropping)
picam2.set_controls({"ScalerCrop": (0, 0, 4656, 3496)})

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    print("Starting server at http://localhost:8000")
    print("Press Ctrl+C to stop")
    server.serve_forever()
finally:
    picam2.stop_recording()
