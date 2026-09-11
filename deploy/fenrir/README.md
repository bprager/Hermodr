# Gateway Integration

Install `hermodr-global.conf` in nginx's HTTP-level include directory. Install `hermodr-location.conf` in the location-include directory and include it only inside the TLS virtual host selected for ingestion. The TLS certificate must already cover that host.

The upstream name and port are deployment-specific and must resolve only on the private network. Keep operations bound to loopback on the application host and apply service-level peer filtering so the gateway can reach ingestion but not operations.

Before reload, run `nginx -t`. Test a zero-coordinate synthetic event over TLS, a non-POST method rejection, public 404 responses for `/health/ready` and `/metrics`, and a direct gateway-to-operations connection failure. Inspect the dedicated access log to confirm it contains no authorization value, body, query string, coordinates, subject/device identifiers, or upstream diagnostic text.
