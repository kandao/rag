import os

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/bge-reranker-large")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "32"))
MAX_SEQUENCE_LENGTH = int(os.environ.get("MAX_SEQUENCE_LENGTH", "512"))
