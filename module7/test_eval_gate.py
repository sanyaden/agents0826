"""
М7 — евали як юніт-тести: червоний тест = реліз не проходить.

Це те саме, що DeepEval робить у CI, тільки на нашому судді й нашому
датасеті. Запускається звичайним pytest, тому лягає в будь-який пайплайн:

    pytest test_eval_gate.py -v          # весь гейт (~28 викликів моделі)
    pytest test_eval_gate.py -v -k tool  # лише детерміновані, без моделі
    pytest test_eval_gate.py -q --deepeval-gate   # ще й через DeepEval

Різниця між двома половинами тут — головна думка заняття про евали:
перевірка інструментів детермінована, безкоштовна і швидка, а перевірка
змісту потребує судді, грошей і терпіння. У CI перші ганяють на кожен
коміт, другі — на кожен реліз.
"""

import json
import os
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from config import DATA_DIR
from modules import m07_evaluation as m07

CASES = m07.load_dataset()          # одне джерело правди з модулем


def test_dataset_files_agree():
    """Якщо поруч лежать .jsonl і .json — вони мають збігатись.

    Дешевий запобіжник: інакше хтось відредагує .json, гейт мовчки
    читатиме .jsonl, і два тижні буде незрозуміло, чому правка «не
    подіяла».
    """
    legacy = DATA_DIR / "evalset.json"
    if not legacy.exists():
        pytest.skip("є лише .jsonl")
    old = {c["id"]: c["query"] for c in json.loads(legacy.read_text(encoding="utf-8"))}
    new = {c["id"]: c["query"] for c in CASES}
    assert old.keys() == new.keys(), (
        f"розійшлись кейси: тільки в .json {old.keys() - new.keys()}, "
        f"тільки в .jsonl {new.keys() - old.keys()}")
    drifted = [k for k in old if old[k] != new[k]]
    assert not drifted, f"той самий кейс, різний текст запиту: {drifted}"


@pytest.fixture(scope="session")
def report(request):
    """Один прогін датасету на всю сесію — не платимо за кожен тест окремо.

    Прогін триває ~2,5 хв, і без цього прогресу pytest увесь цей час
    мовчить, а потім висипає всі крапки разом — виглядає як зависання.
    pytest захоплює stdout, тож на час рядка прогресу захоплення треба
    вимкнути через capmanager.
    """
    capman = request.config.pluginmanager.getplugin("capturemanager")

    def show(i, total, case_id):
        with capman.global_and_fixture_disabled():
            end = "\n" if i == total else ""
            print(f"\r  eval-датасет: кейс {i:>2}/{total}  {case_id:<24}",
                  end=end, flush=True)

    return m07.run(on_case=show)


# ── Дешева половина: інструменти, без моделі ──────────────────

TOOL_ACCURACY = 0.9      # нижче — агент почав губити інструменти


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_tool_choice(case, report):
    """Чи агент узяв той інструмент, який мав.

    Перевірка тут детермінована й безкоштовна — але сам ВИБІР робить
    модель, тож поодинокий промах трапляється. Тому покейсово це сигнал
    подивитись, а не зупинка збірки; блокує агрегат нижче.
    """
    got = next(r for r in report["cases"] if r["id"] == case["id"])
    if not got["tool_ok"]:
        pytest.xfail(
            f"{case['id']}: очікували {case.get('expects_tool')}, не викликано")


def test_tool_accuracy_rate(report):
    """Скільки кейсів узяли правильний інструмент. Це вже блокер."""
    cases = report["cases"]
    rate = sum(c["tool_ok"] for c in cases) / len(cases)
    assert rate >= TOOL_ACCURACY, (
        f"tool accuracy {rate:.2f} < {TOOL_ACCURACY}: "
        f"{[c['id'] for c in cases if not c['tool_ok']]}")


# ── Дорога половина: зміст, через суддю ───────────────────────

@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_answer_meets_criterion(case, report):
    """Чи відповідь задовольняє критерій кейсу. Тут працює LLM-суддя.

    Навмисно НЕ жорсткий тест. Звичайний результат — 14/14, але зрідка
    один кейс перевертається, і щоразу інший: суддя теж модель, і на межі
    він хитається. Саме непередбачуваність того, ЯКИЙ кейс упаде, робить
    покейсовий блокер марним — він ловив би шум, а не погіршення.
    Контракт релізу — агрегований гейт нижче.
    """
    got = next(r for r in report["cases"] if r["id"] == case["id"])
    if not got["judge_pass"]:
        pytest.xfail(f"{case['id']}: {got.get('reason', '—')}")


# ── Власне гейт ───────────────────────────────────────────────

def test_release_gate(report):
    """Один агрегований поріг: нижче — реліз не проходить."""
    rate = report["pass_rate"]
    assert report["gate"] == "PASS", (
        f"гейт {m07.THRESHOLD}: скор {rate:.2f} ({report['score']}) — реліз зупинено. "
        f"Провалені: {[c['id'] for c in report['cases'] if not c['pass']]}")


# ── Те саме через DeepEval (--deepeval-gate) ──────────────────

def test_deepeval_gate(request, report):
    """DeepEval поверх тих самих кейсів — щоб побачити різницю в API.

    Метрики DeepEval потребують своєї моделі-судді, тож за замовчуванням
    тест пропускається: на занятті достатньо власного гейта вище.
    """
    if not request.config.getoption("--deepeval-gate"):
        pytest.skip("вмикається прапорцем --deepeval-gate")

    pytest.importorskip("deepeval", reason="pip install deepeval")
    from deepeval.metrics import AnswerRelevancyMetric
    from deepeval.models import AnthropicModel
    from deepeval.test_case import LLMTestCase

    # За замовчуванням DeepEval бере суддею GPT і просить OPENAI_API_KEY.
    # Нам зайвий ключ не потрібен — суддею ставимо той самий Anthropic.
    judge = AnthropicModel(model=os.getenv("JUDGE_MODEL", "claude-haiku-4-5-20251001"))

    failures = []
    for got in report["cases"][:3]:                # три кейси: DeepEval платний за викликами
        query = next(c["query"] for c in CASES if c["id"] == got["id"])
        case = LLMTestCase(input=query, actual_output=got["answer"])
        metric = AnswerRelevancyMetric(threshold=0.7, model=judge)
        metric.measure(case)
        if not metric.is_successful():
            failures.append(f"{got['id']}: {metric.score:.2f}")
    assert not failures, f"DeepEval завалив: {failures}"
