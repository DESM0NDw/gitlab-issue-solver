from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str
    anthropic_api_key: str
    webhook_secret: str = ""
    repos_base_path: str = "/repos"

    class Config:
        env_file = ".env"


settings = Settings()
