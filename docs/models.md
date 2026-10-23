# Model configuration

GCT can describe model services in one file. This page says what that file contains and what GCT does with it. The short version is in the section "Configured is not enabled": in this version no reading step uses a configured model.

## The file

Model adapters live in a TOML file outside every workspace: `~/.config/gct/models.toml`, or the file named by the environment variable `GCT_MODELS`. On Windows the default resolves under the user profile; set `GCT_MODELS` to choose another file. Without the file there are no adapters and nothing changes: rung 1 reading needs no model.

Each adapter is a table `[adapters.NAME]`. `gct model list` shows what GCT read from the file: one line per adapter with its name, provider, model, address, local or external, paid or free, and whether the key variable is set. With no file it says so. The key itself is never printed.

## Keys

- `provider`: required, text. The only value is `openai_chat`, the chat completions interface that Ollama, NVIDIA, OpenRouter and OpenAI all offer.
- `base_url`: required, text. An http or https address. GCT posts to this address followed by `/chat/completions`.
- `model`: required, text. The model name the service expects.
- `external`: required, true or false. False means the service runs on this computer.
- `paid`: required, true or false. True means each call costs money and both prices are required.
- `api_key_env`: optional, text. The name of an environment variable that holds the key. Never the key itself.
- `price_in`: optional, a number of 0 or more. USD per million input tokens. Required when `paid` is true.
- `price_out`: optional, a number of 0 or more. USD per million output tokens. Required when `paid` is true.
- `timeout`: optional, a number of 0 or more. Seconds to wait for an answer. The default is 120.

## The local rule

An adapter with `external = false` must point at this computer: the host must be `127.0.0.1`, `localhost` or `::1`. The check is on the address text; nothing is resolved. Otherwise the file is refused and the command exits with code 4:

`FILE: adapters.NAME.base_url points at HOST, which is not this computer, but external is false.`

Next step: `Correct base_url for NAME in FILE.`

A model on another machine, even in the same network, must be declared `external = true`.

## Approvals

- An external adapter sending private data needs a transfer approval: `gct approve transfer NAME`, withdrawn with `--revoke`. The approval is bound to the address and the model name, so changing either needs a new approval.
- A paid adapter needs a spend cap: `gct approve spend AMOUNT`. A per-run allowance exists in the code and no command takes it yet.
- A local, free adapter needs neither.

These rules apply when a reading step calls an adapter. In this version none does.

## Keys and secrets

Keys are read from the environment variable named in `api_key_env` and sent as a bearer token. Keys, and anything that looks like one (`sk-` and `nvapi-` strings, `Bearer` values, the live value of every configured key variable), are replaced by `[redacted]` in error logs, the run log, failure messages, package text and text sent to a model. GCT uses no proxy from the environment and follows no redirects: a service that answers with a redirect gets a failure, so neither the key nor the content reaches a second host.

When a call fails after it was sent, the message is one of these (NAME is the adapter name):

`NAME could not be reached.`

Next step: `Check the adapter in gct model list, then run the same command again.`

## Configured is not enabled

In this version no reading step uses a configured model. Reading is rung 1 (pdfplumber) only. A configured adapter is checked for shape, listed by `gct model list`, and bound to the approval rules above. It changes nothing about what `gct read` or `gct extract` produce until a reading story (2.5 to 2.8) is built and accepted. `gct model list` says the same thing, in text after the adapter lines and in JSON as `reading_steps: []`.

## Example

This is an example of the shape; not tested against a running Ollama in this version. Replace the model name with the one `ollama list` shows on your computer.

```toml
[adapters.ollama]
provider = "openai_chat"
base_url = "http://127.0.0.1:11434/v1"
model = "<the name `ollama list` shows>"
external = false
paid = false
```

## Hardware

Not recorded. No local model has been run against GCT.
