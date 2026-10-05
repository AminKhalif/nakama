# Integration research

Integrations must be based on an inspectable API or published configuration
contract. Model APIs are not personal-agent connectors. Running a model with a
vendor name does not demonstrate interoperability with that vendor's agent.

Hermes Agent provides MCP client support. Its official documentation and code
are available at https://github.com/NousResearch/hermes-agent. A local MCP tool
server can expose Nakama operations without changes to Hermes itself.

Muse has been used in the original bridge experiment. This repository does not
contain a verified native Muse connector implementation. Its setup must be
validated against the account's actual connector interface before claiming support.

Instinct and Dots remain integration targets. No native adapter is claimed without
an official developer contract and an end-to-end integration test.
