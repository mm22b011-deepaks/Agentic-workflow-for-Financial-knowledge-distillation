# ADR 003: one trusted operator, local controls

Normal CLI, API and worker processes read credentials only from their environment. Only the restricted smoke script may load .env internally. It reports source, key length, sha8 and HTTP status, never a response body. A successful smoke does not prove key rotation.

The original loopback-only binding is superseded by the explicit network-access request in ADR 006. The API binds to all IPv4 interfaces on port 8767, restricts Host to loopback/workstation names and the connection’s local address, restricts Origin, rejects cross-site browser requests and requires a session cookie plus CSRF header for mutations. Workflows come from a validated server registry and cannot contain shell commands or uploaded code. One active writer per workstation prevents races over parquet artifacts. This is not multi-user or distributed hosting.

Index view is the default. Internal trace requires explicit server enablement after NDA confirmation and an explicit session-only client toggle; responses are private and non-cacheable. Static fixtures and Index exports omit trace identifiers. Local operators with filesystem access can already read private data; the service does not claim protection from hostile local processes.
