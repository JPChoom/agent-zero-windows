# Local model server (llama.cpp)

Agent Zero can run its own [llama.cpp](https://github.com/ggml-org/llama.cpp) server (`llama-server.exe`) on your PC, so no other app (LM Studio, Ollama) has to be open. It listens on `127.0.0.1` only.

## Set it up

1. Open *Settings > Agent > Models > Configure Models* and scroll to **Local model server (llama.cpp)**.
2. Under *Advanced*, click **Check download**, then **Download and install**. This fetches the official build from github.com/ggml-org/llama.cpp (NVIDIA CUDA, Vulkan, AMD ROCm or CPU) and installs it only if its SHA-256 matches the one GitHub publishes.
3. **Model**: pick a `.gguf` file. Agent Zero lists `usr\llama-cpp\models`, LM Studio's model folder (`%USERPROFILE%\.lmstudio\models`) and any folders you add. Picking one points the Main model (and, unless you untick the box, the Utility model) at the server.
4. **Preset**: *Coding (fast)* for most work (see below).
5. Save, then **Start**, or turn on *Start with Agent Zero*.

Do not keep a model loaded in LM Studio at the same time: a large model needs the GPU memory for itself.

## Presets

| Preset | llama-server options | Use it for |
|---|---|---|
| **Coding (fast)** | `-fa on -ctk q8_0 -ctv q8_0 --jinja --cache-reuse 256`, plus `--spec-type draft-mtp --spec-draft-n-max 6` when the model has an MTP layer | Everyday agent and coding work |
| **Balanced** | the same without MTP drafting | Comparing with Coding, or models where drafting does not help |
| **Low memory** | 4-bit memory cache (`-ctk q4_0 -ctv q4_0`) | A longer context or a bigger model on a smaller GPU |
| **Custom** | what you type | Your own tuning (for example another `--spec-draft-n-max`) |

*MTP (multi-token prediction)* is a small extra layer some models ship with (for example Qwen3.8 builds; files named "noMTP" have it removed). The model uses it to guess several tokens ahead and checks them in one pass. Agent Zero reads the model file to see whether it has the layer and only turns drafting on when it does.

The server's context size follows the Main model's context length while Main uses the server.

## Measured: RTX 4090 (24 GB), Qwen3.8-27B Q4_K_M

October 2026, llama.cpp build b11849 (CUDA 12.4), context 49,152 tokens, two coding prompts (write a function with tests; rewrite a module), thinking off, temperature 0.6, second run of each reported (prompt already cached).

| Options | Write (tokens/s) | Rewrite (tokens/s) | Drafts accepted | GPU memory |
|---|---|---|---|---|
| Fast flags only (= Balanced) | 47 | 47 | - | 18.3 GB |
| + MTP, 2 tokens | 99 | 97 | 89-91% | 19.2 GB |
| + MTP, 3 tokens (llama.cpp default) | 115 | 115 | 87-88% | 19.3 GB |
| + MTP, 4 tokens | 128 | 119 | 77-85% | 19.5 GB |
| **+ MTP, 6 tokens (Coding preset)** | **129** | **136** | 69-74% | 19.8 GB |
| + n-gram drafting instead | 49 | 57 | 15-30% | 18.3 GB |
| + MTP and n-gram together | 132 | 103 | 47-64% | 19.3 GB |

Through Agent Zero, a real coding request ran at about 130 tokens/s. On the same PC the 8-task Windows workflow benchmark took 705 s with this model in LM Studio (no drafting).

These numbers are from one machine and one model. The best draft length depends on the model, GPU and kind of text: if you tune it, compare with *Balanced* on your own work using the per-turn timing line Agent Zero prints in its console and the records in `usr/perf/`.

## When it does not start

- **"Not enough free GPU memory"**: another app (often LM Studio with a model loaded) holds the GPU. Close it, choose a smaller model, lower *GPU layers* under *Advanced*, or try *Low memory*.
- **"Port 8090 is already used by another program"**: something else listens on that port. Change the port under *Advanced*; models that use the server follow it.
- The server's log is shown in the section (`usr\logs\llama-server.log`).
