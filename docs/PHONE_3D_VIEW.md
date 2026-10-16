# Phone Live 3D view - status (a0.7.0)

Not shipped in a0.7.0 (hidden). Planned Phase 1: replay of PC poses (poses recorded during preview renders,
exported to a fixed folder only, served behind the same 12-hour control session token), three.js bundled locally
(no CDN), orbit/zoom/pan, scrub bar, pause, speed 0.25/0.5/1x, reference ghost toggle, follow camera,
"synced N s ago" pill, PC-offline state, auto-stop after 10 minutes or when the screen turns off, and a
"New checkpoint ready" card (Switch now / Later). Pose export runs at low priority and never touches the trainer.

Phase 2 (running the policy on the phone) is gated on a parity test against the PC policy; stub only.
