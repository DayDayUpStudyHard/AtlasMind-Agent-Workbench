# External Regulation MCP

AtlasMind can call one allowlisted, read-only MCP tool from contract Agent runs.
The integration is disabled by default. It is intended to add external regulation
references when internal contract and policy evidence is insufficient.

## Server contract

The provider must expose a Streamable HTTP MCP endpoint authenticated with a
Bearer token. AtlasMind calls exactly the configured tool name with this shape:

```json
{
  "query": "违约金调整的司法依据",
  "jurisdiction": "CN",
  "effectiveDate": "2026-08-15",
  "limit": 5
}
```

The tool should return `sources`, `results`, `items`, or `data`. Every usable
item requires `title`, `url`, and one of `snippet`, `summary`, `content`, or
`text`. `issuer` and `effectiveDate` are optional.

Only HTTPS results whose hostname is in `REGULATION_MCP_ALLOWED_DOMAINS` are
included in Agent evidence. Returned text is marked as untrusted external
reference material and cannot replace contract clauses or internal policy
evidence.

## Configuration

Set the following production environment variables before restarting the AI
service:

```env
REGULATION_MCP_ENABLED=true
REGULATION_MCP_URL=https://provider.example.com/mcp
REGULATION_MCP_API_KEY=replace-with-provider-token
REGULATION_MCP_TOOL_NAME=search_regulations
REGULATION_MCP_ALLOWED_DOMAINS=gov.cn,court.gov.cn,samr.gov.cn
```

The deployment also supports timeouts, per-run call budget, result limit, and
in-process cache TTL. See `.env.example` for the complete list.

## Safety limits

- Only one configured MCP endpoint and one configured tool can be called.
- The tool is absent from Agent tool selection until configuration is complete.
- Each Agent run is limited to two external calls by default.
- Results are deduplicated, capped, and restricted to the domain allowlist.
- MCP calls are recorded through the existing `agent_tool_call` trace path.
