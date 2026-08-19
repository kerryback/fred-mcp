# fred-mcp

FRED MCP server for Rice Business Executive Education.

Publishes a catalog of tracked economic series and serves observations, metadata,
search, and past vintages over the Model Context Protocol (streamable HTTP).

Tools: `fred_list_catalog`, `fred_search_series`, `fred_series_info`,
`fred_get_observations`, `fred_get_vintage`.

Endpoint: https://fred.kerryback.com/mcp

Requires `FRED_API_KEY` in the environment. The key stays on the server.

`/mcp` is an OAuth 2.1 protected resource. It verifies bearer tokens issued by the
class authorization server at https://auth.kerryback.com and checks that each token's
`aud` claim names this resource. Unauthenticated requests get a 401 whose
`WWW-Authenticate` header points at `/.well-known/oauth-protected-resource`.

Environment: `FRED_API_KEY`, `JWT_SECRET` (shared with the authorization server),
`AUTH_ISSUER`, `RESOURCE_URL`. With `JWT_SECRET` unset the server runs open, which is
fine on localhost and wrong anywhere else.
