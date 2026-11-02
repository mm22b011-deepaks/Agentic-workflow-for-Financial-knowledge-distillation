# ADR 006: network access and a separate website port

Accepted 2026-11-02 by explicit user instruction to bind the website to 0.0.0.0. This supersedes the loopback-only binding in ADR 003 and the initial handover.

The workstation's systemd-managed taskd service owns port 8765 on loopback and its network interface. Restart=always makes killing its Python process ineffective as a port fix. Preserve that unrelated service; Tresata defaults to 0.0.0.0:8767. The existing --port option supports explicit alternatives.

Host checks accept localhost, the workstation hostname and the accepted connection's local IP address, allowing LAN/Tailscale access without accepting arbitrary Host headers. Same-origin, cross-site request rejection, CSRF, private responses and trace gating remain enforced.

There is no user authentication. Any reachable network client can create a session and operate jobs. Binding all IPv4 interfaces relies on a trusted network or existing access controls. No firewall, public forwarding or taskd service configuration is changed.

Focused tests cover default/explicit ports, LAN and carrier-network IPs, hostname access, forged hosts, cross-origin requests and CSRF. The previous full acceptance receipt predates this change; the network-binding receipt records its own verification.
