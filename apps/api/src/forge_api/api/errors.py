from dataclasses import dataclass


@dataclass
class ProblemError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
