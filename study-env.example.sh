# Source this from the repository root to use original sample materials and separate state.
# This is a shell configuration example; the app does not automatically read .env.
export STUDY_DATA_DIR="$PWD/sample_data"
export STUDY_STATE_DIR="$PWD/.study-runtime/demo-state"
export STUDY_CACHE_DIR="$PWD/.study-runtime/demo-cache"
# Optional, after explicitly downloading a compatible model:
# export STUDY_EMBEDDING_DIR="/absolute/path/to/pinned-e5-model"
