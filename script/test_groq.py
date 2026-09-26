from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

import time

from dotenv import load_dotenv


def main() -> int:
    """Test Groq API connectivity.
    
    Loads .env, builds Groq LLM, sends one minimal chat message.
    Prints Provider, Model, Status, Latency(ms). Never prints the key.
    Exits non-zero on failure.
    """
    load_dotenv()
    
    from retrieval.llm import build_llm
    from core.config import load_settings, require_llm_credentials, normalized_provider
    
    settings = load_settings()
    provider = normalized_provider(settings)
    
    if provider != "groq":
        print(f"Skipping Groq test: LLM_PROVIDER={settings.llm_provider}")
        return 0
    
    try:
        require_llm_credentials(settings)
    except RuntimeError as e:
        print(f"Configuration error: {e}")
        return 1
    
    try:
        llm = build_llm(settings=settings, temperature=0.1)
        
        start = time.time()
        response = llm.invoke("Reply with the single word: PONG")
        latency_ms = int((time.time() - start) * 1000)
        
        answer = ""
        if hasattr(response, "content"):
            answer = response.content
        else:
            answer = str(response)
        
        print(f"Provider: Groq")
        print(f"Model: {settings.groq_model}")
        print(f"Status: SUCCESS")
        print(f"Latency: {latency_ms}ms")
        print(f"Response: {answer.strip()}")
        
        if "PONG" in answer.upper():
            return 0
        else:
            print(f"Warning: Unexpected response")
            return 1
            
    except Exception as e:
        print(f"Provider: Groq")
        print(f"Model: {settings.groq_model}")
        print(f"Status: FAILED")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
