from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Settings for the Bluesky Manager application, loaded from environment variables.
    """

    OPENAI_APIKEY: str = ""
    PARL_USERAGENT: str = "appg-membership"
    TAVITY_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()  # type: ignore
