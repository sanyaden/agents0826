"""Налаштування pytest для eval-гейта модуля 7."""


def pytest_addoption(parser):
    parser.addoption(
        "--deepeval-gate", action="store_true",
        help="додатково прогнати кілька кейсів через DeepEval "
             "(потрібні pip install deepeval і свій ключ судді)")

def pytest_configure(config):
    # Шум чужих бібліотек на екрані заняття відволікає від власне гейта.
    # deepeval 4.x досі кличе get_event_loop() — це їхнє попередження,
    # не наше, і на роботу тесту воно не впливає.
    config.addinivalue_line(
        "filterwarnings",
        "ignore:There is no current event loop:DeprecationWarning")
