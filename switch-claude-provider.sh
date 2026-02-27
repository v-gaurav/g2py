#!/usr/bin/env bash
# switch-claude-provider.sh
# Detects current Claude Code provider from .env and lets you switch between:
#   1. AWS Bedrock
#   2. Google Vertex AI
#   3. Ollama (local)
#   4. LiteLLM (proxy)
#   5. Anthropic API (direct)
#
# Usage: bash switch-claude-provider.sh
#   or:  source switch-claude-provider.sh

# ---------------------------------------------------------------
# Resolve .env path (script dir or $G2_ENV_FILE override)
# ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ENV_FILE="${G2_ENV_FILE:-${SCRIPT_DIR}/.env}"

# ---------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------
env_get() {
    # Read a variable from .env (returns empty string if not found)
    local key="$1"
    if [[ -f "${ENV_FILE}" ]]; then
        grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | head -1 | sed "s/^${key}=//" | sed 's/^"//;s/"$//'
    fi
}

env_set() {
    # Set a key=value in .env (creates file if needed, updates if exists)
    local key="$1" value="$2"
    touch "${ENV_FILE}"
    if grep -qE "^${key}=" "${ENV_FILE}" 2>/dev/null; then
        # Remove the old line then append the new one (avoids sed delimiter issues with special chars in values)
        local tmp="${ENV_FILE}.tmp.$$"
        grep -vE "^${key}=" "${ENV_FILE}" > "${tmp}" && mv "${tmp}" "${ENV_FILE}"
    fi
    echo "${key}=${value}" >> "${ENV_FILE}"
}

env_remove() {
    # Remove a key from .env
    local key="$1"
    if [[ -f "${ENV_FILE}" ]]; then
        local tmp="${ENV_FILE}.tmp.$$"
        grep -vE "^${key}=" "${ENV_FILE}" > "${tmp}" && mv "${tmp}" "${ENV_FILE}"
    fi
}

# ---------------------------------------------------------------
# Detect current provider from .env
# ---------------------------------------------------------------
detect_provider() {
    local use_bedrock use_vertex base_url api_key
    use_bedrock=$(env_get "CLAUDE_CODE_USE_BEDROCK")
    use_vertex=$(env_get "CLAUDE_CODE_USE_VERTEX")
    base_url=$(env_get "ANTHROPIC_BASE_URL")
    api_key=$(env_get "ANTHROPIC_API_KEY")

    if [[ "${use_bedrock}" == "1" ]]; then
        echo "bedrock"
    elif [[ "${use_vertex}" == "1" ]]; then
        echo "vertex"
    elif [[ "${base_url}" =~ localhost|127\.0\.0\.1 ]]; then
        if [[ "${api_key}" == "ollama" ]]; then
            echo "ollama"
        else
            echo "litellm"
        fi
    elif [[ -n "${api_key}" ]]; then
        echo "anthropic"
    else
        echo "none"
    fi
}

print_current_config() {
    local provider
    provider=$(detect_provider)

    echo ""
    echo "========================================="
    echo " Claude Code — Current Provider Config"
    echo " (.env: ${ENV_FILE})"
    echo "========================================="

    case "${provider}" in
        bedrock)
            local _region
            _region=$(env_get AWS_REGION)
            [[ -z "${_region}" ]] && _region=$(env_get AWS_DEFAULT_REGION)
            echo " Provider   : AWS Bedrock"
            echo " Region     : ${_region:-not set}"
            echo " Profile    : $(env_get AWS_PROFILE)"
            echo " Model      : $(env_get ANTHROPIC_MODEL)"
            echo " Haiku Model: $(env_get ANTHROPIC_DEFAULT_HAIKU_MODEL)"
            echo " Small/Fast : $(env_get ANTHROPIC_SMALL_FAST_MODEL)"
            ;;
        vertex)
            echo " Provider   : Google Vertex AI"
            echo " Project    : $(env_get CLOUD_ML_PROJECT_ID)"
            echo " Region     : $(env_get CLOUD_ML_REGION)"
            echo " Model      : $(env_get ANTHROPIC_MODEL)"
            echo " Haiku Model: $(env_get ANTHROPIC_DEFAULT_HAIKU_MODEL)"
            echo " Small/Fast : $(env_get ANTHROPIC_SMALL_FAST_MODEL)"
            ;;
        ollama)
            echo " Provider   : Ollama (local)"
            echo " Base URL   : $(env_get ANTHROPIC_BASE_URL)"
            echo " Model      : $(env_get ANTHROPIC_MODEL)"
            echo " Haiku Model: $(env_get ANTHROPIC_DEFAULT_HAIKU_MODEL)"
            echo " Small/Fast : $(env_get ANTHROPIC_SMALL_FAST_MODEL)"
            echo " API Key    : (dummy)"
            ;;
        litellm)
            echo " Provider   : LiteLLM (proxy)"
            echo " Base URL   : $(env_get ANTHROPIC_BASE_URL)"
            echo " Model      : $(env_get ANTHROPIC_MODEL)"
            echo " Haiku Model: $(env_get ANTHROPIC_DEFAULT_HAIKU_MODEL)"
            echo " Small/Fast : $(env_get ANTHROPIC_SMALL_FAST_MODEL)"
            echo " API Key    : (set)"
            ;;
        anthropic)
            echo " Provider   : Anthropic API (direct)"
            echo " API Key    : (set)"
            echo " Model      : $(env_get ANTHROPIC_MODEL)"
            echo " Haiku Model: $(env_get ANTHROPIC_DEFAULT_HAIKU_MODEL)"
            echo " Small/Fast : $(env_get ANTHROPIC_SMALL_FAST_MODEL)"
            ;;
        none)
            echo " Provider   : NOT CONFIGURED"
            ;;
    esac

    echo "========================================="
    echo ""
}

# ---------------------------------------------------------------
# Remove all provider-related keys from .env
# ---------------------------------------------------------------
remove_provider_keys() {
    # Bedrock
    env_remove CLAUDE_CODE_USE_BEDROCK
    env_remove ANTHROPIC_BEDROCK_BASE_URL
    env_remove AWS_ACCESS_KEY_ID
    env_remove AWS_SECRET_ACCESS_KEY
    env_remove AWS_SESSION_TOKEN
    env_remove AWS_PROFILE
    env_remove AWS_REGION
    env_remove AWS_DEFAULT_REGION

    # Vertex
    env_remove CLAUDE_CODE_USE_VERTEX
    env_remove CLOUD_ML_PROJECT_ID
    env_remove CLOUD_ML_REGION

    # Common
    env_remove ANTHROPIC_API_KEY
    env_remove ANTHROPIC_BASE_URL
    env_remove ANTHROPIC_MODEL
    env_remove ANTHROPIC_DEFAULT_HAIKU_MODEL
    env_remove ANTHROPIC_SMALL_FAST_MODEL
}

# ---------------------------------------------------------------
# Provider setup functions
# ---------------------------------------------------------------
setup_bedrock() {
    local region profile model haiku_model small_model
    read -rp "  AWS Region      [us-west-2]: " region
    read -rp "  AWS Profile     [default]  : " profile
    read -rp "  Model           [us.anthropic.claude-opus-4-6-v1]: " model
    read -rp "  Haiku Model     [us.anthropic.claude-haiku-4-5-20251001]: " haiku_model
    read -rp "  Small/Fast Model[us.anthropic.claude-haiku-4-5-20251001]: " small_model

    remove_provider_keys

    env_set CLAUDE_CODE_USE_BEDROCK 1
    env_set AWS_REGION "${region:-us-west-2}"
    env_set AWS_DEFAULT_REGION "${region:-us-west-2}"
    env_set AWS_PROFILE "${profile:-default}"
    env_set ANTHROPIC_MODEL "${model:-us.anthropic.claude-opus-4-6-v1}"
    env_set ANTHROPIC_DEFAULT_HAIKU_MODEL "${haiku_model:-us.anthropic.claude-haiku-4-5-20251001}"
    env_set ANTHROPIC_SMALL_FAST_MODEL "${small_model:-us.anthropic.claude-haiku-4-5-20251001}"

    echo ""
    echo "Switched to AWS Bedrock."
}

setup_vertex() {
    local project region model haiku_model small_model
    read -rp "  GCP Project ID  []: " project
    read -rp "  GCP Region      [us-central1]: " region
    read -rp "  Model           [claude-opus-4-6-v1]: " model
    read -rp "  Haiku Model     [claude-haiku-4-5-20251001]: " haiku_model
    read -rp "  Small/Fast Model[claude-haiku-4-5-20251001]: " small_model

    remove_provider_keys

    env_set CLAUDE_CODE_USE_VERTEX 1
    env_set CLOUD_ML_PROJECT_ID "${project}"
    env_set CLOUD_ML_REGION "${region:-us-central1}"
    env_set ANTHROPIC_MODEL "${model:-claude-opus-4-6-v1}"
    env_set ANTHROPIC_DEFAULT_HAIKU_MODEL "${haiku_model:-claude-haiku-4-5-20251001}"
    env_set ANTHROPIC_SMALL_FAST_MODEL "${small_model:-claude-haiku-4-5-20251001}"

    if [[ -z "${project}" ]]; then
        echo "  WARNING: GCP Project ID is empty."
    fi

    echo ""
    echo "Switched to Google Vertex AI."
}

setup_ollama() {
    local base_url model haiku_model small_model
    read -rp "  Ollama Base URL  [http://localhost:11434]: " base_url
    read -rp "  Model            [gpt-oss:20b]: " model
    read -rp "  Haiku Model      [gpt-oss:20b]: " haiku_model
    read -rp "  Small/Fast Model [gpt-oss:20b]: " small_model

    remove_provider_keys

    env_set ANTHROPIC_BASE_URL "${base_url:-http://localhost:11434}"
    env_set ANTHROPIC_API_KEY "ollama"
    env_set ANTHROPIC_MODEL "${model:-gpt-oss:20b}"
    env_set ANTHROPIC_DEFAULT_HAIKU_MODEL "${haiku_model:-gpt-oss:20b}"
    env_set ANTHROPIC_SMALL_FAST_MODEL "${small_model:-gpt-oss:20b}"

    echo ""
    echo "Switched to Ollama."
    echo "  Ensure Ollama is running:  ollama serve"
    echo "  Ensure model is pulled  :  ollama pull ${model:-gpt-oss:20b}"
}

setup_litellm() {
    local base_url api_key model haiku_model small_model
    read -rp "  LiteLLM Base URL [https://litellm-prod.engineering-ai.amwayglobal.com]: " base_url
    read -srp "  API Key          [lm-studio]: " api_key
    echo ""  # newline after silent read
    read -rp "  Model            [claude-opus]: " model
    read -rp "  Haiku Model      [claude-sonnet]: " haiku_model
    read -rp "  Small/Fast Model [claude-haiku]: " small_model

    remove_provider_keys

    env_set ANTHROPIC_BASE_URL "${base_url:-https://litellm-prod.engineering-ai.amwayglobal.com}"
    env_set ANTHROPIC_API_KEY "${api_key:-lm-studio}"
    env_set ANTHROPIC_MODEL "${model:-claude-opus}"
    env_set ANTHROPIC_DEFAULT_HAIKU_MODEL "${haiku_model:-claude-sonnet}"
    env_set ANTHROPIC_SMALL_FAST_MODEL "${small_model:-claude-haiku}"

    echo ""
    echo "Switched to LiteLLM."
}

setup_anthropic() {
    local api_key model haiku_model small_model
    read -srp "  Anthropic API Key []: " api_key
    echo ""  # newline after silent read
    read -rp "  Model             [claude-opus-4-6-v1]: " model
    read -rp "  Haiku Model       [claude-haiku-4-5-20251001]: " haiku_model
    read -rp "  Small/Fast Model  [claude-haiku-4-5-20251001]: " small_model

    if [[ -z "${api_key}" ]]; then
        echo "  WARNING: API key is empty."
    fi

    remove_provider_keys

    env_set ANTHROPIC_API_KEY "${api_key}"
    env_set ANTHROPIC_MODEL "${model:-claude-opus-4-6-v1}"
    env_set ANTHROPIC_DEFAULT_HAIKU_MODEL "${haiku_model:-claude-haiku-4-5-20251001}"
    env_set ANTHROPIC_SMALL_FAST_MODEL "${small_model:-claude-haiku-4-5-20251001}"

    echo ""
    echo "Switched to Anthropic API (direct)."
}

# ---------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------
print_current_config

echo "Select a provider to switch to:"
echo "  1) AWS Bedrock"
echo "  2) Google Vertex AI"
echo "  3) Ollama (local)"
echo "  4) LiteLLM (proxy)"
echo "  5) Anthropic API (direct)"
echo "  q) Quit (no changes)"
echo ""
read -rp "Choice [1-5/q]: " choice

case "${choice}" in
    1) setup_bedrock   ;;
    2) setup_vertex    ;;
    3) setup_ollama    ;;
    4) setup_litellm   ;;
    5) setup_anthropic ;;
    q|Q) echo "No changes made." ;;
    *) echo "Invalid choice. No changes made." ;;
esac

# Show final state
if [[ "${choice}" =~ ^[1-5]$ ]]; then
    print_current_config
fi
