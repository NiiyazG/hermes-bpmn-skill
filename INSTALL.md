# Установка BPMN Diagramming Skill в Hermes Agent

## Вариант 1 — пользовательский каталог навыков

Скопируйте каталог:

```text
process-modeling/bpmn-diagramming
```

в:

```text
~/.hermes/skills/process-modeling/bpmn-diagramming
```

Затем проверьте окружение:

```bash
python ~/.hermes/skills/process-modeling/bpmn-diagramming/scripts/check_env.py
```

Установите Python-зависимости при необходимости:

```bash
python -m pip install lxml Pillow PyMuPDF
```

Для EPS установите Inkscape.

## Проверка навыка

```bash
python ~/.hermes/skills/process-modeling/bpmn-diagramming/scripts/build_bpmn.py \
  ~/.hermes/skills/process-modeling/bpmn-diagramming/examples/simple-approval.json \
  --out ./bpmn-test
```

Ожидаемый результат:

```text
STATUS: PASS
```

## Проверка из Hermes

После установки попросите Hermes:

> Используй навык bpmn-diagramming. Создай BPMN процесса согласования закупки, сначала задай только критичные вопросы и выдай все форматы.

