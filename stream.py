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
function zoom() {
    fetch('/zoom', {method: 'POST'})
        .then(response => {
            if (!response.ok) alert('Zoom failed');
        });
}
</script>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<button onclick=\"zoom()\">Zoom Out</button><br/>
<img src="stream.mjpg" width="640" height="480" />
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
        if self.path == '/zoom':
            increment_zoom()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

picam2 = Picamera2()
sensor_modes = picam2.sensor_modes
selected_mode = sensor_modes[0]  # Use a lower resolution sensor mode for Pi Zero
sensor_width, sensor_height = selected_mode['size']

def increment_zoom():
    global current_crop
    # Use the selected sensor mode's size for cropping
    native_width, native_height = sensor_width, sensor_height
    x, y, w, h = current_crop
    # Increase the crop size by 10% each time, but not beyond the native size
    new_w = min(int(w * 1.1), native_width)
    new_h = min(int(h * 1.1), native_height)
    # Center the crop
    new_x = max(0, (native_width - new_w) // 2)
    new_y = max(0, (native_height - new_h) // 2)
    current_crop = (new_x, new_y, new_w, new_h)
    picam2.set_controls({"ScalerCrop": current_crop})

for mode in sensor_modes:
    print("Mode", mode)
print(f"Selected sensor mode size: {sensor_width}x{sensor_height}")

# Much smaller output resolution for Pi Zero's limited memory
output_resolution = (640, 480)  # Reduced significantly for Pi Zero
config = picam2.create_video_configuration(
    main={"size": output_resolution, "format": 'XRGB8888'},
    raw=selected_mode
)

picam2.configure(config)
output = StreamingOutput()
current_crop = (0, 0, sensor_width, sensor_height)
picam2.start_recording(JpegEncoder(), FileOutput(output))
picam2.set_controls({"ScalerCrop": current_crop})

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    picam2.stop_recording()