# Quality Gates

Финальная выдача требует PASS либо явного указания, что это draft.

## Структурные проверки
- уникальные ID;
- sourceRef/targetRef существуют;
- laneRef существует;
- Start Event без incoming;
- End Event без outgoing;
- Sequence Flow не пересекает Pool;
- Message Flow используется только между Pools;
- Gateway имеет корректные выходы.

## Геометрические проверки
- endpoints на границах source/target;
- диагональных Sequence Flow = 0;
- последний сегмент входит перпендикулярно;
- flow не проходит через unrelated node;
- task не пересекает lane border;
- коллинеарных наложений разных flow = 0.

## Визуальная проверка
- нет текста под линиями;
- нет стрелок, визуально слитых с Lane border;
- `Да/Нет` читаются;
- возвраты понятны;
- все Task явно принадлежат Lane.
