# Source this from the repository root to use original sample materials and separate state.
# This is a shell configuration example; the app does not automatically read .env.
export STUDY_DATA_DIR="$PWD/sample_data"
export STUDY_STATE_DIR="$PWD/.study-runtime/demo-state"
export STUDY_CACHE_DIR="$PWD/.study-runtime/demo-cache"
# Optional, after explicitly downloading a compatible model:
# export STUDY_EMBEDDING_DIR="/absolute/path/to/pinned-e5-model"
# Optional local administrator choices. Never point these at shared ~/.codex.
# Defaults already select the dedicated official runtime and authentication home.
# export STUDY_CODEX_BIN="$HOME/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex"
# export STUDY_CODEX_HOME="$HOME/.local/share/study-with-ai/codex-home"
