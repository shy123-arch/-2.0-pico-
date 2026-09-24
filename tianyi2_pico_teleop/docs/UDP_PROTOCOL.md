# PICO UDP protocol

Each datagram is UTF-8 JSON with schema `tianyi2-pico/v1` and a maximum size of
32 KiB. It contains:

- random `session_id` generated when the PC streamer starts;
- monotonically increasing `sequence` within the session;
- source monotonic and Unix timestamps for diagnostics;
- left/right controller pose as `[x,y,z,qx,qy,qz,qw]`;
- optional headset pose in the same format;
- named boolean buttons;
- named floating-point triggers, grips and joystick axes.

The robot accepts only the latest strictly increasing sequence in a session. Packet
freshness uses the robot's local receive clock, so unsynchronized PC/robot clocks do
not affect the watchdog.

