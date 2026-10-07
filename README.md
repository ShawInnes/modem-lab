# Modem Lab

A local audio modem simulator. Exchange text between two modems, listen to the call, inspect signals, and experiment with phone-line noise and delay. Includes Bell 103-style 300 bit/s FSK and experimental 1200/2400 bit/s modes.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20.19+ or 22.12+ and npm

## Setup and start

Run these commands from the repository root:

```sh
uv sync --extra dev
npm ci --prefix frontend
npm run build --prefix frontend
uv run modem-lab-web
```

Open **http://127.0.0.1:8000** in your browser.

1. Click **Start call**.
2. Send text from either terminal, or enable **Auto chat**.
3. Choose **Combined line** under **Listen** to hear the modems.
4. Adjust the line controls to see how noise and delay affect reception.

If audio is silent, click **Enable / resume audio**. Use one browser tab at a time. Press `Ctrl+C` in the terminal to stop the server.

After setup, start it again with:

```sh
uv run modem-lab-web
```

## Development

Keep the backend running with `uv run modem-lab-web`. In a second terminal, run:

```sh
npm run dev --prefix frontend
```

Open **http://127.0.0.1:5173**. The frontend development server connects to the backend on port 8000. To serve frontend changes from port 8000, rebuild with `npm run build --prefix frontend`.

## Command-line demo

The offline demo only needs Python and uv:

```sh
uv sync --extra dev
uv run modem-lab
```

It prints the decoded messages and saves audio and session data to `runs/demo/`. Open `runs/demo/combined.wav` in an audio player to listen.

For custom messages:

```sh
uv run modem-lab --caller 'Hello from A' --answerer 'Hello from B'
```

## Tests

```sh
uv run pytest -q
```

## More details

See the [specification](docs/SPEC.md), [protocol notes](docs/PROTOCOL.md), and [fidelity notes](docs/FIDELITY.md) for implementation details and limitations.
