"""Налаштування pytest для eval-гейта модуля 7."""


def pytest_addoption(parser):
    parser.addoption(
        "--deepeval-gate", action="store_true",
        help="додатково прогнати кілька кейсів через DeepEval "
             "(потрібні pip install deepeval і свій ключ судді)")
