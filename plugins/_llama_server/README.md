# llama.cpp server

Agent Zero starts, watches and stops its own local [llama.cpp](https://github.com/ggml-org/llama.cpp) server
(`llama-server.exe`), so you do not need LM Studio running. It is one more model provider; LM Studio and every other
provider keep working.

## Setup

1. Enable the plugin, then open *Settings > Agent > llama.cpp server*.
2. **Download and install**: choose a build (NVIDIA CUDA, Vulkan or CPU; automatic picks CUDA when an NVIDIA GPU is
   found), click *Check download*, then *Download and install*. The official build is fetched from
   github.com/ggml-org/llama.cpp and installed into `usr/llama-cpp/bin/` only if its SHA-256 matches the one GitHub
   publishes. You can also point *llama-server.exe* at your own copy.
3. **Model**: models are not included. Put a `.gguf` file into `usr/llama-cpp/models/` (Q4_K_M is a good balance of
   speed and quality) and pick it, or enter any path. Save.
4. **Start**. Then select the **llama.cpp** provider in *Settings > Agent > Models*; its default address is
   `http://127.0.0.1:8090/v1` (keep the port in sync).

Turn on *Start with Agent Zero* to have it start automatically.

## What it guarantees

- Listens on 127.0.0.1 only; host, port, model and alias cannot be overridden through extra arguments.
- "Running" means the process Agent Zero started is alive, `/health` is ready and the server reports the model you
  chose, not just that something answers on the port.
- Refuses to start when an NVIDIA GPU clearly lacks free memory for the model (turn the check off, or lower GPU
  layers, if you know better).
- Restarts it after a crash (a few times, with increasing delays), then stops trying and tells you.
- Stops it when Agent Zero exits. If Agent Zero was killed, the next start keeps an identical healthy server or
  replaces it, so no stray `llama-server.exe` is left running.
- Downloading is only possible from this PC, not from a remote session.

Logs: `usr/logs/llama-server.log`.
