from pydantic_settings import BaseSettings


LLM_CONFIG = {
    "groq":    ("https://api.groq.com/openai/v1",  "llama-3.3-70b-versatile", "groq_api_key"),
    "openai":  ("https://api.openai.com/v1",        "gpt-4o",                      "openai_api_key"),
    "mistral": ("https://api.mistral.ai/v1",        "mistral-large-latest",        "mistral_api_key"),
}


class Settings(BaseSettings):
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str
    webhook_secret: str = ""
    repos_base_path: str = "/repos"

    llm_provider: str = "groq"
    groq_api_key: str = ""
    openai_api_key: str = ""
    mistral_api_key: str = ""

    @property
    def llm(self) -> tuple[str, str, str]:
        base_url, model, key_attr = LLM_CONFIG[self.llm_provider]
        return base_url, model, getattr(self, key_attr)

    class Config:
        env_file = ".env"


settings = Settings()
