# Provider contract recordings

`make test` runs one contract suite (`test_provider_contract.py`) for every approved provider
configuration and every role it serves. Each case replays a recorded HTTP exchange from
`recordings/<configuration id>.<role>.json` through the real vendor SDK and the real adapter, on a
mock transport: no network, no key. It checks that the structured output validates against the
`FieldExtraction` schema, that every `source_id` is in the input, that every quote is in its source
verbatim, and that the usage record holds the tokens, tool calls and cost the recording implies.

Adding a configuration to `app/providers/provider_configs.example.json` (or a role to an API)
without its recordings, or without a price in `price_table.example.json`, fails the suite.

## Recordings

All recordings use the same synthetic input, `recordings/_input.json`: a fictitious supplier (Acme
SA) for structuring, and a public listed company for retrieval. A recording file holds the HTTP
status and body the provider returned, `expected_usage` (what the adapter must read from it) and,
for retrieval, `expected_urls`.

The files committed first were written by hand in each provider's documented response shape
(`"origin"` says so). Replace them with real recordings before relying on them:

```sh
cd backend
# Your own configuration file, with the point checks done (enabled, verified_at set), and your own
# price table. The keys are read from the environment by name and never written anywhere.
export PROVIDER_CONFIG_FILE=/path/to/provider_configs.json PRICE_TABLE_FILE=/path/to/prices.json
GEMINI_API_KEY=... uv run python -m tests.providers.record --config gemini-flash-structuring
#   --role structuring|retrieval   only one role (default: every role the configuration serves)
```

The command makes one real call per role, keeps the last HTTP exchange, and refuses to write a
file that contains the key or an email address. Review the diff (the real response may differ from
the hand-written one, including the usage figures), then run `make test`.
