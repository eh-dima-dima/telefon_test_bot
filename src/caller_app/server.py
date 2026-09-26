from .config import Settings
from .main import create_app

app = create_app(settings=Settings.from_env())
